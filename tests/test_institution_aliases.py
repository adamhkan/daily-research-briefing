import unittest
import json
from pathlib import Path

from daily_robotics_briefing.common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from daily_robotics_briefing.institution_filter import (
    _match_institution, alias_hits, build_institution_specs, extraction_from_evidence,
)
from daily_robotics_briefing.main import load_filters


class InstitutionAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_filters(Path('config/filters.yaml'))
        cls.specs = build_institution_specs([*cls.config['institutions'], *COMMON_ROBOTICS_INSTITUTIONS])

    def test_ordinary_words_and_ambiguous_acronyms_do_not_identify_institutions(self):
        examples = [
            'as a visiting researcher', 'AS', 'fair comparison', 'FAIR principles',
            'hit rate', 'HIT', 'intrinsic reward', 'Intrinsic motivation',
            'Intrinsic', 'rice harvesting', 'Rice', 'Mines', 'UCB exploration',
            'UW', 'NTU', 'OSU', 'USC', 'UCD', 'UNIGE',
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(alias_hits(text, self.specs), [])

    def test_full_names_and_specific_aliases_still_work(self):
        examples = {
            'Academia Sinica': 'Academia Sinica',
            'Facebook AI Research': 'Meta AI',
            'Meta AI': 'Meta AI',
            'Harbin Institute of Technology': 'Harbin Institute of Technology',
            'UC Berkeley': 'UC Berkeley',
            'University of California, Berkeley': 'UC Berkeley',
            'University of Washington': 'University of Washington',
            'UDub': 'University of Washington',
            'Nanyang Technological University': 'Nanyang Technological University',
            'NTU Taiwan': 'National Taiwan University',
            'Ohio State University': 'The Ohio State University',
            'University of Southern California': 'University of Southern California',
            'UC Davis': 'University of California, Davis',
            'University of Genoa': 'University of Genoa',
            'Rice University': 'Rice University',
            'Colorado School of Mines': 'Colorado School of Mines',
            'MPI-IS': 'Max Planck Institute for Intelligent Systems',
            'NVIDIA Research': 'NVIDIA',
            'MIT': 'Massachusetts Institute of Technology',
            'NYU': 'New York University',
            'ETH Zürich': 'ETH Zurich',
        }
        for raw, canonical in examples.items():
            with self.subTest(raw=raw):
                match = _match_institution(raw, self.specs)
                self.assertIsNotNone(match)
                self.assertEqual(match.canonical, canonical)

    def test_distinct_universities_and_company_units_are_not_merged(self):
        names = ['Miami University', 'University of Miami', 'Boston Dynamics AI Institute',
                 'Boston Dynamics', 'Amazon Robotics', 'Amazon Alexa AI', 'Amazon Lab126']
        evidence = [dict(institution=name, role='author_affiliation', authors=[]) for name in names]
        result = extraction_from_evidence([], evidence, self.specs)
        self.assertEqual(set(result.paper_level_institutions), set(names))
        self.assertEqual(result.unmapped_raw_institutions, [])
        for name in names:
            with self.subTest(name=name):
                # In particular, the parent name must not win a substring hit
                # inside the longer name of a distinct research organization.
                self.assertEqual([spec.canonical for _, spec in alias_hits(name, self.specs)], [name])

    def test_generic_max_planck_name_does_not_identify_a_specific_institute(self):
        for text in ['Max Planck Institute', 'Max Planck Institute for Informatics']:
            with self.subTest(text=text):
                self.assertEqual(alias_hits(text, self.specs), [])
        self.assertEqual(_match_institution('Max Planck Institute for Intelligent Systems', self.specs).canonical,
                         'Max Planck Institute for Intelligent Systems')

    def test_model_extracted_ambiguous_names_stay_unmapped(self):
        names = ['UW', 'UCB', 'FAIR', 'AS', 'HIT', 'NTU', 'OSU', 'Intrinsic']
        evidence = [dict(institution=name, role='author_affiliation', authors=['Jane Doe']) for name in names]
        result = extraction_from_evidence(['Jane Doe'], evidence, self.specs)
        self.assertEqual(set(result.unmapped_raw_institutions), set(names))
        self.assertEqual(result.authors[0].institutions, [])
        self.assertFalse(set(result.paper_level_institutions) & {spec.canonical for spec in self.specs})

    def test_affiliation_wrappers_resolve_without_rewriting_source(self):
        raw = 'Department of Architecture, Massachusetts Institute of Technology, United States'
        result = extraction_from_evidence([], [dict(institution=raw, role='author_affiliation', authors=[])], self.specs)
        self.assertEqual(result.paper_level_institutions, ['Massachusetts Institute of Technology'])
        self.assertEqual(result.paper_level_detected_institutions, [raw])
        self.assertEqual(result.unmapped_raw_institutions, [])

    def test_compact_names_and_apostrophes_require_unique_whole_names(self):
        from daily_robotics_briefing.institution_filter import resolve_institution
        for raw, canonical in [('NanyangTechnologicalUniversity', 'Nanyang Technological University'),
                               ('PekingUniversity', 'Peking University'),
                               ('Xi’an Jiaotong University', "Xi'an Jiaotong University")]:
            with self.subTest(raw=raw):
                self.assertEqual(resolve_institution(raw, self.specs).canonical, canonical)
        ambiguous = build_institution_specs(['Alpha Beta University', 'Alphabeta University'])
        self.assertIsNone(resolve_institution('AlphaBetaUniversity', ambiguous))

    def test_embedded_names_do_not_erase_campuses_or_other_identities(self):
        from daily_robotics_briefing.institution_filter import resolve_institution
        for raw in ['The Chinese University of Hong Kong Shenzhen',
                    'The Hong Kong University of Science and Technology (Guangzhou)',
                    'New York University Abu Dhabi', 'Stanford University Hospital',
                    'University of WashingtonProject page: example.org',
                    'PekingUniversityResearch', 'MITPress',
                    'Department of Architecture, MIT and Stanford University',
                    'Department of Architecture, MIT, Unknown Campus']:
            with self.subTest(raw=raw):
                self.assertIsNone(resolve_institution(raw, self.specs))
        for raw in ['New York University Abu Dhabi', 'Stanford University Hospital']:
            self.assertEqual(alias_hits(raw, self.specs), [])

    def test_saved_report_replay_preserves_matches_and_adds_only_verified_identities(self):
        report = json.loads(Path('reports/2026-10-22/2026-10-22.json').read_text())
        specs = build_institution_specs([*report['filters']['institutions'], *COMMON_ROBOTICS_INSTITUTIONS])
        changes = {}
        for paper in report['papers']:
            result = extraction_from_evidence(paper['authors'], paper['affiliation_evidence'], specs)
            before = set(paper['matched_institutions'])
            after = set(result.paper_level_institutions) & set(report['filters']['institutions'])
            self.assertTrue(before <= after, paper['arxiv_id'])
            if after != before:
                changes[paper['arxiv_id']] = after - before
        self.assertEqual(changes, {
            'arXiv:2610.27472': {'Massachusetts Institute of Technology'},
            'arXiv:2610.27039': {'Stanford University'},
        })
        # Washington requires collector cleanup, covered by the HTML regression.

    def test_non_latin_institution_names_are_preserved_as_unresolved(self):
        raw = '北京大学'
        result = extraction_from_evidence([], [dict(institution=raw, role='author_affiliation', authors=[])], self.specs)
        self.assertEqual(result.unmapped_raw_institutions, [raw])

    def test_configured_and_common_aliases_do_not_reintroduce_removed_names(self):
        for path in ['config/filters.yaml', 'config/filters.example.yaml']:
            specs = build_institution_specs([*load_filters(Path(path))['institutions'], *COMMON_ROBOTICS_INSTITUTIONS])
            for text in ['UW', 'UCB', 'FAIR', 'AS', 'HIT']:
                with self.subTest(path=path, text=text):
                    self.assertEqual(alias_hits(text, specs), [])


if __name__ == '__main__':
    unittest.main()
