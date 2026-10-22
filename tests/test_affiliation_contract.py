"""Offline checks for the boundary between model interpretation and code validation."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from daily_robotics_briefing.affiliations import _validate_claim, identify_institutions
from daily_robotics_briefing.briefing_agent import _request_validated
from daily_robotics_briefing.institution_filter import build_institution_specs, extraction_from_evidence
from daily_robotics_briefing.response_schemas import AffiliationClaim


SPECS = build_institution_specs([
    {'canonical': 'Massachusetts Institute of Technology', 'aliases': ['MIT']},
    {'canonical': 'New York University', 'aliases': ['NYU']},
    'Tongji University', 'Shenzhen University',
])


def claim(name, text, **changes):
    values = dict(institution=name, authors=[], block_id='b', evidence_quote=text,
                  role='author_affiliation')
    values.update(changes)
    return AffiliationClaim(**values)


def block(text, **changes):
    value = dict(id='b', text=text, kind='affiliation', authors=[],
                 source_url='https://example.org/paper', locator='#affiliation')
    value.update(changes)
    return value


class AffiliationContractTests(unittest.TestCase):
    def test_clean_names_accept_postal_addresses_without_city_rules(self):
        for name, text in [
            ('Tongji University', 'Tongji University, Shanghai, 201804, China'),
            ('Shenzhen University', 'Shenzhen University, Shenzhen, Guangdong, China'),
            ('Hong Kong University of Science and Technology (Guangzhou)',
             'Hong Kong University of Science and Technology (Guangzhou), Guangzhou, China'),
        ]:
            with self.subTest(name=name):
                _validate_claim(claim(name, text), {'b': block(text)}, [])

    def test_clean_source_name_maps_only_through_explicit_aliases(self):
        text = 'Department of Architecture, MIT, United States'
        item = claim('MIT', text)
        _validate_claim(item, {'b': block(text)}, [])
        result = extraction_from_evidence([], [item.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, ['Massachusetts Institute of Technology'])
        self.assertEqual(result.paper_level_detected_institutions, ['MIT'])
        self.assertEqual(item.evidence_quote, text)

    def test_unknown_and_qualified_organizations_are_not_forced_to_parent_identities(self):
        names = ['Novel Robotics Laboratory', 'New York University Abu Dhabi',
                 'New York University, Paris', 'Department of Architecture, MIT']
        items = [claim(name, name).model_dump() for name in names]
        result = extraction_from_evidence([], items, SPECS)
        self.assertEqual(set(result.paper_level_institutions), set(names))
        self.assertEqual(set(result.unmapped_raw_institutions), set(names))
        self.assertNotIn('New York University', result.paper_level_institutions)
        self.assertNotIn('Massachusetts Institute of Technology', result.paper_level_institutions)

    def test_complete_name_boundaries_reject_embedded_acronyms(self):
        with self.assertRaises(ValueError):
            _validate_claim(claim('MIT', 'COMMITTEE'), {'b': block('COMMITTEE')}, [])
        _validate_claim(claim('MIT', 'MIT, United States'),
                        {'b': block('MIT, United States')}, [])
        with self.assertRaises(ValueError):
            _validate_claim(claim('MIT', 'MIT'), {'b': block('COMMITTEE')}, [])
        _validate_claim(claim('Tsinghua University', '1Tsinghua University'),
                        {'b': block('1Tsinghua University')}, [])

    def test_parenthesized_name_can_end_at_joined_source_boundary(self):
        text = 'Singapore Institute of Manufacturing Technology (SIMTech)Agency for Science'
        name = 'Singapore Institute of Manufacturing Technology (SIMTech)'
        _validate_claim(claim(name, text), {'b': block(text)}, [])

    def test_model_can_restore_pdf_spaces_without_code_guessing_the_name(self):
        item = claim('New York University', 'NewYorkUniversity')
        _validate_claim(item, {'b': block('NewYorkUniversity')}, [])
        result = extraction_from_evidence([], [item.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, ['New York University'])
        self.assertEqual(item.evidence_quote, 'NewYorkUniversity')

    def test_whitespace_only_names_and_quotes_fail_cleanly(self):
        for item in [claim(' ', 'MIT'), claim('MIT', ' ')]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                _validate_claim(item, {'b': block('MIT')}, [])

    def test_non_latin_author_and_institution_names_do_not_collide(self):
        text = '张伟，北京大学'
        item = claim('北京大学', text)
        _validate_claim(item, {'b': block(text)}, ['张伟'])
        result = extraction_from_evidence(['张伟'], [item.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, ['北京大学'])
        self.assertEqual(result.unmapped_raw_institutions, ['北京大学'])

    def test_model_reported_funder_is_excluded_from_current_affiliations(self):
        items = [claim('MIT', 'MIT', role='funder').model_dump(),
                 claim('Novel Robotics Laboratory', 'Novel Robotics Laboratory').model_dump()]
        result = extraction_from_evidence([], items, SPECS)
        self.assertEqual(result.paper_level_institutions, ['Novel Robotics Laboratory'])
        self.assertNotIn('Massachusetts Institute of Technology', result.paper_level_institutions)

    def test_source_reference_and_quote_checks_remain_strict(self):
        item = claim('MIT', 'MIT')
        with self.assertRaises(ValueError):
            _validate_claim(item.model_copy(update={'block_id': 'missing'}), {'b': block('MIT')}, [])
        with self.assertRaises(ValueError):
            _validate_claim(item.model_copy(update={'evidence_quote': 'invented quote'}), {'b': block('MIT')}, [])

    def test_author_references_must_belong_to_supplied_paper(self):
        with self.assertRaises(ValueError):
            _validate_claim(claim('MIT', 'Jane Doe is with MIT.', authors=['Unknown Author']),
                            {'b': block('Jane Doe is with MIT.')}, ['Jane Doe'])

    def test_affiliation_paper_coverage_remains_strict_after_two_responses(self):
        paper = dict(arxiv_id='paper-1', authors=[], abs_url='https://example.org/paper',
                     affiliation_blocks=[block('Novel Robotics Laboratory', kind='header_context')])
        # Real orchestration and repair execute, while model transport is offline.
        with patch('daily_robotics_briefing.briefing_agent._responses_create',
                   return_value=json.dumps({'papers': [dict(paper_id='wrong-paper', complete=True,
                                                            affiliations=[])]})) as request:
            with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING'):
                identify_institutions([paper], [], [], SimpleNamespace(api_key=None), 'offline',
                                      _request_validated)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(paper['affiliation_evidence'], [])
        self.assertFalse(paper['affiliation_complete'])
        self.assertIn('affiliation_model_fallback_failed', paper['affiliation_issues'])


if __name__ == '__main__':
    unittest.main()
