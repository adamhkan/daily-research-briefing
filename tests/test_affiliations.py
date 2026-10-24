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

    def test_complex_real_sources_are_sent_to_model_without_guessed_matches(self):
        cases = [
            ('2610.24512', 'Stanford University'),
            ('2610.24267', 'MIT'),
            ('2610.24610', 'ETH Zürich'),
            ('2610.26852', 'New York University'),
            ('2610.26762', 'ETH Zürich'),
            ('2610.26765', 'Tsinghua University'),
            ('2610.26759', 'University of Bristol'),
        ]
        for pid, institution_in_source in cases:
            with self.subTest(pid=pid):
                value = fixture_record(pid)
                self.assertIn(institution_in_source, ' '.join(b['text'] for b in value['affiliation_blocks']))
                evidence, complete = deterministic_evidence(value, SPECS)
                self.assertEqual(evidence, [])
                self.assertFalse(complete)

    def test_mixed_known_and_unfamiliar_organizations_are_not_silently_truncated(self):
        for text in ['Stanford University; Novel Robotics Lab', 'Stanford University; Luma AI']:
            with self.subTest(text=text):
                evidence, complete = deterministic_evidence(record(text), SPECS)
                self.assertEqual(evidence, [])
                self.assertFalse(complete)

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
        evidence, complete = deterministic_evidence(dict(authors=[], affiliation_blocks=blocks), SPECS)
        self.assertEqual(evidence, [])
        self.assertFalse(complete)  # Header context is interpreted by the model.

    def test_model_role_keeps_affiliation_separate_from_funding(self):
        text = 'Authors are all with Massachusetts Institute of Technology. † thanks: Financial support: funded by Stanford University.'
        value = record(text, kind='author_note')
        self.assertEqual(deterministic_evidence(value, SPECS), ([], False))
        current = AffiliationClaim(institution='Massachusetts Institute of Technology', authors=[],
                                   block_id='b',  role='author_affiliation')
        funder = AffiliationClaim(institution='Stanford University', authors=[], block_id='b',
                                   role='funder')
        for claim in [current, funder]:
            _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        result = extraction_from_evidence([], [current.model_dump(), funder.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, ['Massachusetts Institute of Technology'])

    def test_model_reported_campus_and_role_are_preserved(self):
        text = ('Authors are all with the Hong Kong University of Science and Technology (Guangzhou), China. '
                '(Emails: author@example.org). † thanks: Financial support: funded by a research grant.')
        value = record(text, kind='header_context')
        claim = AffiliationClaim(institution='Hong Kong University of Science and Technology (Guangzhou)',
                                 authors=[], block_id='b',
                                 role='author_affiliation')
        _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        result = extraction_from_evidence([], [claim.model_dump()], SPECS)
        self.assertEqual(result.unmapped_raw_institutions, [claim.institution])
        self.assertNotIn('Hong Kong University of Science and Technology', result.paper_level_institutions)


    def test_model_names_and_unknown_organizations_are_preserved(self):
        text = ('Department of Architecture, Massachusetts Institute of Technology, United States; '
                'Novel Robotics Laboratory, United Kingdom')
        value = record(text)
        claims = [AffiliationClaim(institution=name, authors=[], block_id='b',
                                    role='author_affiliation')
                  for name in ['Massachusetts Institute of Technology', 'Novel Robotics Laboratory']]
        for claim in claims:
            _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
        result = extraction_from_evidence([], [c.model_dump() for c in claims], SPECS)
        self.assertEqual(result.paper_level_institutions,
                         ['Massachusetts Institute of Technology', 'Novel Robotics Laboratory'])
        self.assertEqual(result.unmapped_raw_institutions, ['Novel Robotics Laboratory'])

    def test_model_returned_qualified_names_remain_separate_from_parent_aliases(self):
        for source in ['Amazon Robotics', 'Boston Dynamics AI Institute', 'New York University Abu Dhabi',
                       'The Hong Kong University of Science and Technology (Guangzhou)',
                       'The Chinese University of Hong Kong, Shenzhen']:
            value = record(source)
            claim = AffiliationClaim(institution=source, authors=[], block_id='b',
                                      role='author_affiliation')
            with self.subTest(source=source):
                _validate_claim(claim, {'b': value['affiliation_blocks'][0]}, value['authors'])
                result = extraction_from_evidence([], [claim.model_dump()], SPECS)
                self.assertNotIn('New York University', result.paper_level_institutions)
                self.assertNotIn('Hong Kong University of Science and Technology', result.paper_level_institutions)
                self.assertNotIn('The Chinese University of Hong Kong', result.paper_level_institutions)
        value = record('MIT')
        claim = AffiliationClaim(institution='Massachusetts Institute of Technology', authors=[],
                                 block_id='b',  role='author_affiliation')
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

    def test_collector_excludes_body_mentions_and_leaves_front_matter_for_model(self):
        soup = BeautifulSoup('''<article class="ltx_document"><div class="ltx_authors">
          <div class="ltx_affiliation">Tsinghua University</div>
          <span class="ltx_note_content">This work was supported by Stanford University.</span>
          </div><div class="ltx_abstract">We used a dataset from MIT.</div>
          <section class="ltx_section"><div class="ltx_affiliation">EPFL</div></section></article>''', 'html.parser')
        value = record()
        value['affiliation_blocks'] = _html_affiliation_blocks(soup, 'https://arxiv.org/html/pv1', value['authors'])
        source = ' '.join(b['text'] for b in value['affiliation_blocks'])
        self.assertIn('Tsinghua University', source)
        self.assertIn('supported by Stanford University', source)
        self.assertNotIn('dataset from MIT', source)
        self.assertNotIn('EPFL', source)
        self.assertEqual(deterministic_evidence(value, SPECS), ([], False))

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
                                       role='author_affiliation')],
            }]})
            validate(output)
            return output
        return request

    def test_unknown_name_retained_without_fuzzy_identity(self):
        raw = 'University of Electronic Science and Technology of China'
        value = self.resolve(record(raw), self.model(raw))
        self.assertEqual(value['institution_match_status'], 'no_match')
        self.assertEqual(value['manual_institution_extraction']['paper_level_institutions'], [raw])


    def test_model_funder_role_does_not_create_filter_match(self):
        block = record('This work was funded by Stanford University.', kind='author_note')['affiliation_blocks'][0]
        claim = AffiliationClaim(institution='Stanford University', authors=[], block_id='b',
                                  role='funder')
        _validate_claim(claim, {'b': block}, [])
        result = extraction_from_evidence([], [claim.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, [])

    def test_cache_reuses_raw_evidence_and_refilters(self):
        value = record('Novel University')
        with tempfile.TemporaryDirectory() as tmp:
            first = self.resolve(copy.deepcopy(value), self.model('Novel University'), cache_dir=Path(tmp))
            self.assertFalse(first.get('affiliation_cache_hit', False))
            self.assertEqual(first['institution_match_status'], 'no_match')
            self.assertEqual(first['affiliation_extraction_status'], 'complete')
            self.assertEqual(first['affiliation_resolution_status'], 'no_recognized_filter_match')
            self.assertFalse(first['affiliation_identity_complete'])
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
