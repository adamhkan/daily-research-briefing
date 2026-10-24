"""Historical outputs retain their names/references after dropping obsolete quote fields.

These fixtures do not exercise the current prompt or prove factual accuracy.
"""
import json
import unittest
from pathlib import Path

from daily_robotics_briefing.affiliations import _validate_claim
from daily_robotics_briefing.institution_filter import build_institution_specs, extraction_from_evidence
from daily_robotics_briefing.common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from daily_robotics_briefing.response_schemas import AffiliationOutput

FIXTURES = Path(__file__).parent / 'fixtures' / 'affiliations'
CURRENT = FIXTURES / 'prompt-formatting-v8'

def historical_response(path):
    data = json.loads(path.read_text())
    for row in data['papers']:
        for item in row['affiliations']:
            item.pop('evidence_quote', None)
    return AffiliationOutput.model_validate(data)



class AffiliationEmulationTests(unittest.TestCase):
    def check_captured_responses(self, directory, expected_papers, expected_claims, *, current):
        papers = claims = 0
        for path in sorted(directory.glob('*.request.json')):
            request = json.loads(path.read_text())
            self.assertEqual(request['model'], 'gpt-5.1')
            self.assertEqual(request['reasoning'], {'effort': 'low'})
            payload = json.loads(request['input'][1]['content'])
            submitted = {p['paper_id']: p for p in payload['papers']}
            output = historical_response(path.with_name(path.name.replace('.request.', '.response.')))
            self.assertEqual(len(output.papers), len(submitted))
            self.assertEqual({p.paper_id for p in output.papers}, set(submitted))
            for row in output.papers:
                papers += 1
                paper = submitted[row.paper_id]
                blocks = {b['id']: b for b in paper['blocks']}
                for item in row.affiliations:
                    with self.subTest(batch=path.name, paper=row.paper_id, institution=item.institution):
                        _validate_claim(item, blocks, paper['authors'])
                    claims += 1
        self.assertEqual(papers, expected_papers)
        self.assertEqual(claims, expected_claims)

    def test_historical_model_led_responses_preserve_structure_and_references(self):
        # Historical prompts/schemas are preserved as evidence, not rewritten
        # to claim those responses were generated using today's instructions.
        self.check_captured_responses(FIXTURES / 'model-led', 36, 138, current=False)

    def test_historical_v8_corpus_preserves_structure_and_references(self):
        self.check_captured_responses(CURRENT, 88, 304, current=True)

    def test_historical_v8_responses_keep_names_and_qualified_identities(self):
        rows = {}
        for path in sorted(CURRENT.glob('*.response.json')):
            result = historical_response(path)
            rows.update({row.paper_id: row for row in result.papers})
        def names(pid):
            return {claim.institution for claim in rows['arXiv:' + pid].affiliations
                    if claim.role == 'author_affiliation'}
        self.assertIn('Tohoku University', names('2610.28127'))
        self.assertNotIn('The Space Robotics Lab, Tohoku University', names('2610.28127'))
        self.assertTrue({'Stanford University', 'Tsinghua University',
                         'University of North Carolina at Chapel Hill'} <= names('2610.27039'))
        self.assertEqual(names('2610.26914'),
                         {'University of Utah', 'U.S. Army DEVCOM Army Research Laboratory'})
        self.assertIn('Electronics and Telecommunications Research Institute (ETRI)', names('2610.27995'))
        self.assertTrue({'The Chinese University of Hong Kong Shenzhen',
                         'The Hong Kong University of Science and Technology (Guangzhou)'} <= names('2610.28431'))
        self.assertIn('Keio AI Research Center', names('2610.28523'))
        self.assertIn('Centro di Ricerca “Enrico Piaggio”, Università di Pisa', names('2610.28329'))
        specs = build_institution_specs(['Stanford University', *COMMON_ROBOTICS_INSTITUTIONS])
        result = extraction_from_evidence([], [c.model_dump() for c in rows['arXiv:2610.27039'].affiliations], specs)
        self.assertIn('Stanford University', result.paper_level_institutions)
