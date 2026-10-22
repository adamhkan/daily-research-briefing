import unittest
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

    def test_configured_and_common_aliases_do_not_reintroduce_removed_names(self):
        for path in ['config/filters.yaml', 'config/filters.example.yaml']:
            specs = build_institution_specs([*load_filters(Path(path))['institutions'], *COMMON_ROBOTICS_INSTITUTIONS])
            for text in ['UW', 'UCB', 'FAIR', 'AS', 'HIT']:
                with self.subTest(path=path, text=text):
                    self.assertEqual(alias_hits(text, specs), [])


if __name__ == '__main__':
    unittest.main()
