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
    values = dict(institution=name, authors=[], block_id='b',
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

    def test_unknown_and_qualified_organizations_are_not_forced_to_parent_identities(self):
        names = ['Novel Robotics Laboratory', 'New York University Abu Dhabi',
                 'New York University, Paris', 'Department of Architecture, MIT']
        items = [claim(name, name).model_dump() for name in names]
        result = extraction_from_evidence([], items, SPECS)
        self.assertEqual(set(result.paper_level_institutions), set(names))
        self.assertEqual(set(result.unmapped_raw_institutions), set(names))
        self.assertNotIn('New York University', result.paper_level_institutions)
        self.assertNotIn('Massachusetts Institute of Technology', result.paper_level_institutions)


    def test_parenthesized_name_can_end_at_joined_source_boundary(self):
        text = 'Singapore Institute of Manufacturing Technology (SIMTech)Agency for Science'
        name = 'Singapore Institute of Manufacturing Technology (SIMTech)'
        _validate_claim(claim(name, text), {'b': block(text)}, [])

    def test_model_can_restore_pdf_spaces_without_code_guessing_the_name(self):
        item = claim('New York University', 'NewYorkUniversity')
        _validate_claim(item, {'b': block('NewYorkUniversity')}, [])
        result = extraction_from_evidence([], [item.model_dump()], SPECS)
        self.assertEqual(result.paper_level_institutions, ['New York University'])


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


    def test_author_name_spelling_is_not_a_fatal_reference_check(self):
        _validate_claim(claim('MIT', 'Jane Doe is with MIT.', authors=['J. Doe']),
                        {'b': block('Jane Doe is with MIT.')}, ['Jane Doe'])

    def test_extraction_completeness_is_independent_of_catalog_and_filter_matches(self):
        cases = [
            ('Idealworks', True, 'no_match', 'complete', 'no_recognized_filter_match'),
            ('Idealworks', False, 'unresolved', 'incomplete', 'incomplete_extraction'),
            ('MIT', False, 'matched', 'incomplete', 'filter_match'),
            ('', False, 'unresolved', 'no_usable_evidence', 'no_usable_evidence'),
        ]
        for name, complete, match_status, extraction_status, resolution_status in cases:
            with self.subTest(name=name, complete=complete):
                text = name or 'Title and authors only'
                paper = dict(arxiv_id='p', authors=[], abs_url='https://example.org/p',
                             affiliation_blocks=[block(text, kind='header_context')])
                rows = [claim(name, text).model_dump()] if name else []
                response = dict(papers=[dict(paper_id='p', complete=complete, affiliations=rows)])
                with patch('daily_robotics_briefing.briefing_agent._responses_create',
                           return_value=json.dumps(response)) as request:
                    identify_institutions([paper], [dict(canonical='Massachusetts Institute of Technology',
                                                        aliases=['MIT'])],
                                          ['Massachusetts Institute of Technology'], None, 'offline',
                                          _request_validated)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(paper['institution_match_status'], match_status)
                self.assertEqual(paper['affiliation_extraction_status'], extraction_status)
                self.assertEqual(paper['affiliation_resolution_status'], resolution_status)
                self.assertEqual(paper['affiliation_complete'], complete)
                if name == 'Idealworks':
                    self.assertEqual(paper['manual_institution_extraction']['paper_level_institutions'], [name])
                    self.assertFalse(paper['affiliation_identity_complete'])
                    self.assertEqual(paper['manual_institution_extraction']['filter_match_institutions'], [])


if __name__ == '__main__':
    unittest.main()
