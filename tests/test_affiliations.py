import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx2
from bs4 import BeautifulSoup
from openai import AuthenticationError

from daily_robotics_briefing.affiliations import (
    _exception_details, _validate_claim, deterministic_evidence, identify_institutions,
)
from daily_robotics_briefing.briefing_agent import _request_validated
from daily_robotics_briefing.collector import _html_affiliation_blocks, _pdf_affiliation_text
from daily_robotics_briefing.common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from daily_robotics_briefing.institution_filter import (
    _cleanup_affiliation_fragment, _match_institution, build_institution_specs,
    extraction_from_evidence,
)
from daily_robotics_briefing.response_schemas import AffiliationClaim, AffiliationOutput

FIXTURES = Path(__file__).parent / 'fixtures' / 'affiliations'
FILTERS = ['Stanford University', 'Massachusetts Institute of Technology', 'New York University', 'ETH Zurich', 'EPFL']
ENTRIES = [*FILTERS, {'canonical': 'New York University', 'aliases': ['NYU']}, *COMMON_ROBOTICS_INSTITUTIONS]
SPECS = build_institution_specs(ENTRIES)


def record(text='', *, kind='affiliation', authors=None, pid='p'):
    authors = authors or ['Jane Doe', 'John Smith']
    return dict(arxiv_id=pid, authors=authors, abs_url='https://arxiv.org/abs/p', paper_version='pv1',
                affiliation_blocks=[dict(id='b', text=text, kind=kind, authors=[],
                                         source_url='https://arxiv.org/html/pv1', locator='#authors')] if text else [])


def fixture_record(pid, authors=None):
    value = record(authors=authors, pid=pid)
    soup = BeautifulSoup((FIXTURES / (pid + '.html')).read_text(), 'html.parser')
    value['affiliation_blocks'] = _html_affiliation_blocks(soup, f'https://arxiv.org/html/{pid}v1', value['authors'])
    return value


class SourceRegressionTests(unittest.TestCase):
    def extract(self, value):
        evidence, complete = deterministic_evidence(value, SPECS)
        extraction = extraction_from_evidence(value['authors'], evidence, SPECS)
        return evidence, complete, extraction

    def test_three_previously_missed_filter_matches(self):
        cases = [
            ('2610.24512', ['Jingyi Xiang', 'Yixuan Wang', 'Jeannette Bohg', 'Wenzhen Yuan'], {'Stanford University'}),
            ('2610.24267', ['Sebastian Sartor', 'Robert Seamans', 'Neil C. Thompson'],
             {'Massachusetts Institute of Technology', 'New York University'}),
            ('2610.24610', ['Lukas Amiet', 'Mayank Mittal'], {'ETH Zurich'}),
        ]
        for pid, authors, expected in cases:
            with self.subTest(pid=pid):
                value = fixture_record(pid, authors)
                evidence, _, extraction = self.extract(value)
                self.assertTrue(expected <= set(extraction.paper_level_institutions), extraction)
                for item in evidence:
                    self.assertIn(item['evidence_quote'], ' '.join(next(b['text'] for b in value['affiliation_blocks'] if b['id'] == item['block_id']).split()))
                if pid == '2610.24512':
                    mappings = {a.name: [i.canonical for i in a.institutions] for a in extraction.authors}
                    self.assertIn('Stanford University', mappings['Jeannette Bohg'])
                    self.assertNotIn('Stanford University', mappings['Jingyi Xiang'])

    def test_later_author_groups_and_specific_author_mapping(self):
        _, _, coop = self.extract(fixture_record('2610.26852'))
        self.assertIn('New York University', coop.paper_level_institutions)
        _, _, dex = self.extract(fixture_record('2610.26762', ['Federica Spinola', 'Robert Katzschmann', 'Cordelia Schmid']))
        mappings = {a.name: [i.canonical for i in a.institutions] for a in dex.authors}
        self.assertIn('ETH Zurich', mappings['Robert Katzschmann'])
        self.assertNotIn('ETH Zurich', mappings['Federica Spinola'])

    def test_nonmatch_and_bristol_footnote(self):
        _, _, hands = self.extract(fixture_record('2610.26765'))
        self.assertFalse(set(hands.paper_level_institutions) & set(FILTERS))
        _, _, bristol = self.extract(fixture_record('2610.26759'))
        self.assertIn('University of Bristol', bristol.paper_level_institutions)

    def test_distinct_universities_are_never_merged(self):
        raw = 'University of Electronic Science and Technology of China'
        specs = build_institution_specs(['University of Science and Technology of China'])
        self.assertIsNone(_match_institution(raw, specs))
        self.assertIsNone(_match_institution('Columbia University, New York, USA', build_institution_specs(['New York University'])))
        self.assertIsNone(_match_institution('University of California, Irvine', build_institution_specs(['UC Berkeley'])))
        _, _, actual = self.extract(fixture_record('2610.23896'))
        self.assertNotIn('University of Science and Technology of China', actual.paper_level_institutions)

    def test_project_page_is_not_part_of_html_affiliation(self):
        soup = BeautifulSoup('<article class="ltx_document"><span class="ltx_role_affiliation">University of WashingtonProject page: <a href="https://example.org">example.org</a></span><section class="ltx_abstract"></section></article>', 'html.parser')
        blocks = _html_affiliation_blocks(soup, 'https://arxiv.org/html/pv1', [])
        self.assertEqual(blocks[0]['text'], 'University of Washington')
        evidence, _ = deterministic_evidence(dict(authors=[], affiliation_blocks=blocks), SPECS)
        self.assertIn('University of Washington', [e['institution'] for e in evidence])

    def test_all_with_affiliation_survives_separate_funding_statement(self):
        text = 'Authors are all with Massachusetts Institute of Technology. † thanks: Financial support: funded by Stanford University.'
        value = record(text, kind='author_note')
        evidence, _, result = self.extract(value)
        self.assertIn('Massachusetts Institute of Technology', result.paper_level_institutions)
        self.assertNotIn('Stanford University', result.paper_level_institutions)
        claim = AffiliationClaim(institution='Massachusetts Institute of Technology', authors=[],
                                 block_id='b', evidence_quote='Massachusetts Institute of Technology', role='author_affiliation')
        _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        claim = claim.model_copy(update={'institution': 'Stanford University', 'evidence_quote': 'Stanford University'})
        with self.assertRaisesRegex(ValueError, 'Funding'):
            _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])

    def test_campus_affiliation_quote_is_not_rejected_by_later_funding(self):
        text = ('Authors are all with the Hong Kong University of Science and Technology (Guangzhou), China. '
                '(Emails: author@example.org). † thanks: Financial support: funded by a research grant.')
        value = record(text, kind='header_context')
        claim = AffiliationClaim(institution='Hong Kong University of Science and Technology (Guangzhou)',
                                 authors=[], block_id='b', evidence_quote='Hong Kong University of Science and Technology (Guangzhou)',
                                 role='author_affiliation')
        _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        result = extraction_from_evidence([], [claim.model_dump()], SPECS)
        self.assertEqual(result.unmapped_raw_institutions, [claim.institution])
        self.assertNotIn('Hong Kong University of Science and Technology', result.paper_level_institutions)

    def test_placeholder_and_punctuation_are_not_institution_evidence(self):
        for raw in ['[', 'Your Institution', 'Your University']:
            value = record(raw)
            claim = AffiliationClaim(institution=raw, authors=[], block_id='b', evidence_quote=raw, role='author_affiliation')
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'placeholder'):
                _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
            self.assertEqual(extraction_from_evidence([], [claim.model_dump()], SPECS).paper_level_institutions, [])

    def test_clean_names_keep_separate_source_evidence_and_unknown_organizations(self):
        text = ('Department of Architecture, Massachusetts Institute of Technology, United States; '
                'Novel Robotics Laboratory, United Kingdom')
        value = record(text)
        claims = [AffiliationClaim(institution=name, authors=[], block_id='b',
                                   evidence_quote=text, role='author_affiliation')
                  for name in ['Massachusetts Institute of Technology', 'Novel Robotics Laboratory']]
        for claim in claims:
            _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        result = extraction_from_evidence([], [c.model_dump() for c in claims], SPECS)
        self.assertEqual(result.paper_level_institutions,
                         ['Massachusetts Institute of Technology', 'Novel Robotics Laboratory'])
        self.assertEqual(result.unmapped_raw_institutions, ['Novel Robotics Laboratory'])
        self.assertEqual(claims[0].evidence_quote, text)

    def test_clean_names_cannot_drop_campus_qualifiers_or_invent_expansions(self):
        for source, shortened in [('Amazon Robotics', 'Amazon'),
                                  ('Boston Dynamics AI Institute', 'Boston Dynamics'),
                                  ('New York University Abu Dhabi', 'New York University'),
                                  ('The Hong Kong University of Science and Technology (Guangzhou)',
                                   'Hong Kong University of Science and Technology'),
                                  ('The Chinese University of Hong Kong, Shenzhen',
                                   'The Chinese University of Hong Kong')]:
            value = record(source)
            claim = AffiliationClaim(institution=shortened, authors=[], block_id='b',
                                     evidence_quote=source, role='author_affiliation')
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'qualifier'):
                _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
            _validate_claim(claim.model_copy(update={'institution': source}),
                            {'b': value['affiliation_blocks'][0]}, value['authors'])
        value = record('MIT')
        claim = AffiliationClaim(institution='Massachusetts Institute of Technology', authors=[],
                                 block_id='b', evidence_quote='MIT', role='author_affiliation')
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])

    def test_cleanup_does_not_consume_name_letters(self):
        for name in ['Xi’an University of Architecture and Technology', 'Stanford University',
                     'Carnegie Mellon University', 'University of Electronic Science and Technology of China']:
            self.assertEqual(_cleanup_affiliation_fragment(name), name)
        self.assertEqual(_cleanup_affiliation_fragment('1Stanford University'), 'Stanford University')

    def test_pdf_layout_and_wrapped_footnote(self):
        duet = _pdf_affiliation_text((FIXTURES / '2610.23872-firstpage.txt').read_text())
        self.assertIn('North Carolina State University', duet)
        self.assertNotIn('reinforcement-learning locomotion policy', duet)
        bristol = _pdf_affiliation_text((FIXTURES / '2610.26759-firstpage.txt').read_text())
        self.assertIn('University of Bristol', bristol)

    def test_body_mentions_and_funders_cannot_create_matches(self):
        soup = BeautifulSoup('''<article class="ltx_document"><div class="ltx_authors">
          <div class="ltx_affiliation">Tsinghua University</div>
          <span class="ltx_note_content">This work was supported by Stanford University.</span>
          </div><div class="ltx_abstract">We used a dataset from MIT.</div>
          <section class="ltx_section"><div class="ltx_affiliation">EPFL</div></section></article>''', 'html.parser')
        value = record()
        value['affiliation_blocks'] = _html_affiliation_blocks(soup, 'https://arxiv.org/html/pv1', value['authors'])
        evidence, _, extraction = self.extract(value)
        self.assertFalse(set(extraction.paper_level_institutions) & set(FILTERS))
        self.assertTrue(any(e['role'] == 'funder' for e in evidence))

    def test_no_author_assignment_from_sole_paper_institution(self):
        _, _, extraction = self.extract(record('EPFL'))
        self.assertEqual(extraction.paper_level_institutions, ['EPFL'])
        self.assertTrue(all(not a.institutions for a in extraction.authors))


class FallbackTests(unittest.TestCase):
    def resolve(self, value, request, **kwargs):
        identify_institutions([value], ENTRIES, FILTERS, None, 'model', request, **kwargs)
        return value

    def model(self, raw, *, complete=True, authors=None):
        def request(client, model, prompt, payload, schema, validate, **kwargs):
            block = payload['papers'][0]['blocks'][0]
            output = schema.model_validate({'papers': [{
                'paper_id': payload['papers'][0]['paper_id'], 'complete': complete,
                'affiliations': [dict(institution=raw, authors=authors or [], block_id=block['id'],
                                      evidence_quote=block['text'], role='author_affiliation')],
            }]})
            validate(output)
            return output
        return request

    def test_unknown_name_retained_without_fuzzy_identity(self):
        raw = 'University of Electronic Science and Technology of China'
        value = self.resolve(record(raw), self.model(raw))
        self.assertEqual(value['institution_match_status'], 'no_match')
        self.assertEqual(value['manual_institution_extraction']['paper_level_institutions'], [raw])

    def test_invalid_quote_and_unsupported_author_link_are_rejected(self):
        block = record('Tsinghua University')['affiliation_blocks'][0]
        for changes in [dict(evidence_quote='Invented University'), dict(authors=['Jane Doe'])]:
            claim = AffiliationClaim(institution='Tsinghua University', authors=[], block_id='b',
                                     evidence_quote='Tsinghua University', role='author_affiliation')
            claim = claim.model_copy(update=changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _validate_claim(claim, {'b': block}, ['Jane Doe'])

    def test_unproven_author_link_does_not_discard_a_verified_institution(self):
        value = record('Stanford University', kind='header_context')
        with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
            self.resolve(value, self.model('Stanford University', authors=['Jane Doe', 'Invented Author']))
        self.assertEqual(value['institution_match_status'], 'matched')
        self.assertTrue(value['affiliation_complete'])
        self.assertIn('affiliation_author_mappings_omitted', value['affiliation_issues'])
        self.assertTrue(all(e['authors'] == [] for e in value['affiliation_evidence']))

    def test_a_bad_claim_cannot_discard_other_papers_or_verified_claims_from_its_own_paper(self):
        papers = [record('Stanford University', kind='header_context', pid='good'),
                  record('ETH Zurich', kind='header_context', pid='mixed')]
        rows = []
        for paper in papers:
            institution = 'Stanford University' if paper['arxiv_id'] == 'good' else 'ETH Zurich'
            claims = [dict(institution=institution, authors=[], block_id='b',
                           evidence_quote=institution, role='author_affiliation')]
            if paper['arxiv_id'] == 'mixed':
                claims.append(dict(institution='MIT', authors=[], block_id='b',
                                   evidence_quote='invented MIT source', role='author_affiliation'))
            rows.append(dict(paper_id=paper['arxiv_id'], complete=True, affiliations=claims))
        raw = json.dumps({'papers': rows})
        with patch('daily_robotics_briefing.briefing_agent._responses_create', return_value=raw) as create:
            with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
                identify_institutions(papers, ENTRIES, FILTERS, None, 'model', _request_validated)
        self.assertEqual(create.call_count, 2)
        self.assertTrue(papers[0]['affiliation_complete'])
        self.assertFalse(papers[1]['affiliation_complete'])
        for paper in papers:
            self.assertEqual(paper['institution_match_status'], 'matched')
            self.assertNotIn('affiliation_model_fallback_failed', paper.get('affiliation_issues', []))
            self.assertNotIn('Massachusetts Institute of Technology',
                             paper['manual_institution_extraction']['filter_match_institutions'])
        self.assertIn('affiliation_model_claim_rejected', papers[1]['affiliation_issues'])

    def test_saved_diagnostic_author_mappings_and_funding_context_regression(self):
        fixture = json.loads((FIXTURES / 'diagnostic-author-mappings.json').read_text())
        papers = []
        for row in fixture['input_papers']:
            paper = record(pid=row['paper_id'], authors=row['authors'])
            paper['affiliation_blocks'] = row['blocks']
            papers.append(paper)
        with patch('daily_robotics_briefing.briefing_agent._responses_create',
                   return_value=json.dumps(fixture['model_response'])) as create:
            with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
                identify_institutions(papers, ENTRIES, FILTERS, None, 'model', _request_validated)
        self.assertEqual(create.call_count, 1)
        by_id = {p['arxiv_id']: p for p in papers}
        for paper in papers:
            self.assertTrue(paper['affiliation_complete'])
            self.assertNotIn('affiliation_model_fallback_failed', paper.get('affiliation_issues', []))
            self.assertNotIn('affiliation_model_claim_rejected', paper.get('affiliation_issues', []))
        dex = by_id['arXiv:2610.26762']['affiliation_evidence']
        for author in ['Federica Spinola', 'Cordelia Schmid']:
            self.assertTrue(any(e['institution'] == 'Inria' and e['authors'] == [author]
                                and e['block_id'] != 'html-3' for e in dex))
        memphis = by_id['arXiv:2610.26717']['affiliation_evidence']
        self.assertTrue(any('University of Memphis' in e['institution']
                            and e['role'] == 'author_affiliation' and e['block_id'] in {'html-0', 'html-2'}
                            for e in memphis))
        self.assertTrue(any(e['role'] == 'funder' and 'National Science Foundation' in e['institution']
                            for e in memphis))
        numbered = by_id['arXiv:2610.26663']['affiliation_evidence']
        self.assertTrue(all(not e['authors'] for e in numbered if e['method'] == 'model_extraction'))

    def test_funder_cannot_be_laundered_using_short_quote(self):
        block = record('This work was funded by Stanford University.', kind='author_note')['affiliation_blocks'][0]
        claim = AffiliationClaim(institution='Stanford University', authors=[], block_id='b',
                                 evidence_quote='Stanford University', role='author_affiliation')
        with self.assertRaises(ValueError):
            _validate_claim(claim, {'b': block}, [])

    def test_cache_reuses_raw_evidence_and_refilters(self):
        value = record('Novel University')
        with tempfile.TemporaryDirectory() as tmp:
            first = self.resolve(copy.deepcopy(value), self.model('Novel University'), cache_dir=Path(tmp))
            self.assertFalse(first.get('affiliation_cache_hit', False))
            request = Mock(side_effect=AssertionError('cache should avoid model call'))
            changed = copy.deepcopy(value)
            identify_institutions([changed], [*ENTRIES, 'Novel University'], ['Novel University'], None,
                                  'model', request, cache_dir=Path(tmp))
            self.assertTrue(changed['affiliation_cache_hit'])
            self.assertEqual(changed['institution_match_status'], 'matched')
            self.assertFalse(request.called)
            changed['paper_version'] = 'pv2'
            self.resolve(changed, self.model('Novel University'), cache_dir=Path(tmp))
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 2)

    def test_partial_match_survives_failed_model_fallback(self):
        value = record('EPFL and Novel University')
        with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
            self.resolve(value, Mock(side_effect=ValueError('bad model result')))
        self.assertEqual(value['institution_match_status'], 'matched')
        self.assertFalse(value['affiliation_complete'])
        self.assertIn('affiliation_model_fallback_failed', value['affiliation_issues'])

    def test_fallback_logs_underlying_validation_failure_and_paper_id(self):
        value = record('Novel University', pid='arXiv:example')
        # Exercise the real two-attempt repair wrapper, which chains the cause.
        invalid = json.dumps({'papers': [{
            'paper_id': value['arxiv_id'], 'complete': True, 'affiliations': [{
                'institution': 'Novel University', 'authors': [], 'block_id': 'b',
                'evidence_quote': 'Fabricated evidence', 'role': 'author_affiliation',
            }],
        }]})
        with patch('daily_robotics_briefing.briefing_agent._responses_create', return_value=invalid) as create:
            with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING') as logs:
                self.resolve(value, _request_validated)
        message = '\n'.join(logs.output)
        self.assertIn('AffiliationOutput failed validation after two attempts', message)
        self.assertIn('arXiv:example: Affiliation quote must be verbatim supplied source text', message)
        self.assertIn('model=model', message)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(value['institution_match_status'], 'unresolved')

    def test_api_error_logs_status_and_request_id_without_credentials(self):
        key = 'custom-api-credential-for-test'
        token = 'custom-github-credential-for-test'
        response = httpx2.Response(401, request=httpx2.Request('POST', 'https://api.openai.com/v1/responses'),
                                   headers={'x-request-id': 'req-test'})
        error = AuthenticationError(f'Invalid API key: {key}; token={token}; Bearer unconfigured-token',
                                    response=response, body={'code': 'invalid_api_key'})
        with patch.dict('os.environ', {'OPENAI_API_KEY': key, 'GH_TOKEN': token}):
            with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING') as logs:
                self.resolve(record('EPFL and Novel University'), Mock(side_effect=error))
        message = '\n'.join(logs.output)
        self.assertIn('AuthenticationError', message)
        self.assertIn('status_code=401', message)
        self.assertIn('request_id=req-test', message)
        self.assertIn('code=invalid_api_key', message)
        for credential in [key, token, 'unconfigured-token']:
            self.assertNotIn(credential, message)

    def test_error_diagnostics_are_bounded_and_redact_client_and_prefixed_keys(self):
        key = 'credential-only-on-the-client'
        error = ValueError(f'{key}\nsk-proj-unconfigured-example-key ' + 'x' * 3000)
        message = _exception_details(error, api_key=key)
        self.assertNotIn(key, message)
        self.assertNotIn('sk-proj-unconfigured-example-key', message)
        self.assertNotIn('\n', message)
        self.assertLessEqual(len(message), 2000)

    def test_input_budget_keeps_unresolved_evidence_without_model_call(self):
        request = Mock(side_effect=AssertionError('zero budget'))
        value = self.resolve(record('Novel University'), request, max_input_chars=0)
        self.assertEqual(value['institution_match_status'], 'unresolved')
        self.assertFalse(request.called)
        missing = self.resolve(record(), request)
        self.assertEqual(missing['institution_match_status'], 'source_unavailable')

    def test_former_and_work_done_at_do_not_count(self):
        value = record('Previously with Stanford University. Work was done at MIT.', kind='author_note')
        request = Mock(side_effect=ValueError('remain unresolved'))
        with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
            self.resolve(value, request)
        self.assertFalse(value['manual_institution_extraction']['filter_match'])

    def test_run_wide_budget_and_truncation_are_enforced(self):
        papers = [record('Novel University with additional context', pid=str(i)) for i in range(3)]
        captured = []
        def request(client, model, prompt, payload, schema, validate, **kwargs):
            captured.extend(payload['papers'])
            result = schema.model_validate({'papers': [
                dict(paper_id=p['paper_id'], complete=False, affiliations=[]) for p in payload['papers']
            ]})
            validate(result)
            return result
        identify_institutions(papers, ENTRIES, FILTERS, None, 'model', request,
                              max_input_chars=30, snippet_chars=20)
        self.assertEqual(sum(len(b['text']) for p in captured for b in p['blocks']), 30)
        self.assertTrue(all(p['truncated'] for p in captured))
        self.assertTrue(all(not p['affiliation_complete'] for p in papers))
        self.assertIn('affiliation_input_budget_exceeded', papers[-1]['affiliation_issues'])

    def test_malformed_cache_is_ignored(self):
        value = record('Novel University')
        with tempfile.TemporaryDirectory() as tmp:
            self.resolve(copy.deepcopy(value), self.model('Novel University'), cache_dir=Path(tmp))
            path = next(Path(tmp).glob('*.json'))
            path.write_text('[]')
            request = Mock(side_effect=self.model('Novel University'))
            fresh = self.resolve(copy.deepcopy(value), request, cache_dir=Path(tmp))
            self.assertTrue(request.called)
            self.assertFalse(fresh['affiliation_cache_hit'])


if __name__ == '__main__':
    unittest.main()
