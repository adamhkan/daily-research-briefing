"""Replay low-reasoning stand-ins given captured API requests, without live calls."""
import json
import unittest
from pathlib import Path

from daily_robotics_briefing.affiliations import AFFILIATION_PROMPT, _supported_claims
from daily_robotics_briefing.response_schemas import AffiliationOutput

FIXTURES = Path(__file__).parent / 'fixtures' / 'affiliations' / 'model-led'


class AffiliationEmulationTests(unittest.TestCase):
    def test_captured_requests_and_responses_satisfy_production_contract(self):
        papers = claims = 0
        for path in sorted(FIXTURES.glob('*.request.json')):
            request = json.loads(path.read_text())
            self.assertEqual(request['input'][0], dict(role='system', content=AFFILIATION_PROMPT))
            self.assertEqual(request['model'], 'gpt-5.1')
            self.assertEqual(request['reasoning'], {'effort': 'low'})
            self.assertEqual(request['text']['format']['schema'], AffiliationOutput.model_json_schema())
            payload = json.loads(request['input'][1]['content'])
            submitted = {p['paper_id']: p for p in payload['papers']}
            output = AffiliationOutput.model_validate_json(
                path.with_name(path.name.replace('.request.', '.response.')).read_text())
            self.assertEqual(len(output.papers), len(submitted))
            self.assertEqual({p.paper_id for p in output.papers}, set(submitted))
            for row in output.papers:
                papers += 1
                paper = submitted[row.paper_id]
                blocks = {b['id']: b for b in paper['blocks']}
                for item in row.affiliations:
                    with self.subTest(batch=path.name, paper=row.paper_id, institution=item.institution):
                        supported, omitted = _supported_claims(item, blocks, paper['authors'])
                        self.assertEqual(len(supported), 1)
                        self.assertEqual(supported[0].model_dump(), item.model_dump())
                        self.assertEqual(omitted, [])
                    claims += 1
        self.assertEqual(papers, 36)
        self.assertEqual(claims, 138)
