import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
from openai import OpenAI

from daily_robotics_briefing.diagnose_affiliations import diagnose


class AffiliationDiagnosticTests(unittest.TestCase):
    def exercise(self, *, valid, sample_size=12, api_error=False):
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            self.assertEqual(body['text']['format']['name'], 'AffiliationOutput')
            payload = json.loads(body['input'][1]['content'])
            if api_error:
                return httpx2.Response(429, json={'error': {'message': 'rate limited', 'type': 'rate_limit_error'}})
            text = json.dumps({'papers': [dict(paper_id=p['paper_id'], complete=True, affiliations=[
                dict(institution='Novel University', authors=[], block_id='b',
                     evidence_quote='Novel University' if valid else 'fabricated source', role='author_affiliation')
            ]) for p in payload['papers']]})
            return httpx2.Response(200, json={
                'id': f'resp-{len(calls)}', 'object': 'response', 'created_at': 0,
                'status': 'completed', 'model': 'offline-model',
                'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120,
                          'input_tokens_details': {'cached_tokens': 0},
                          'output_tokens_details': {'reasoning_tokens': 0}},
                'output': [{'id': 'msg-test', 'type': 'message', 'role': 'assistant',
                            'status': 'completed', 'content': [
                                {'type': 'output_text', 'text': text, 'annotations': []}
                            ]}],
            })
        client = OpenAI(api_key='offline-test', max_retries=0,
                        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
        papers = [dict(
            arxiv_id=f'p{i}', authors=['Jane Doe'], abs_url='https://arxiv.org/abs/test',
            affiliation_issues=['affiliation_model_fallback_failed'],
            affiliation_blocks=[dict(id='b', text='Novel University', kind='affiliation',
                                     source_url='https://arxiv.org/html/test', locator='#authors')],
        ) for i in range(13)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / 'report.json'
            report.write_text(json.dumps({'papers': papers, 'model': 'offline-model',
                                          'filters': {'institutions': ['EPFL']}}))
            original = report.read_text()
            config = root / 'filters.yaml'
            config.write_text('institutions: [EPFL]\n')
            output = root / 'logs'
            with patch('daily_robotics_briefing.diagnose_affiliations.OpenAI', return_value=client):
                with self.assertLogs('daily_robotics_briefing.affiliations', level='WARNING') if not valid else self.assertNoLogs('daily_robotics_briefing.affiliations'):
                    passed = diagnose(report, config, output, sample_size=sample_size)
            result = json.loads((output / 'results.json').read_text())
            responses = [json.loads(p.read_text()) for p in sorted(output.glob('response-*.json'))]
            selected = json.loads((output / 'input-papers.json').read_text())
            self.assertEqual(report.read_text(), original)
        return passed, result, responses, selected, calls

    def test_failure_reproduces_only_one_batch_and_persists_both_model_responses(self):
        passed, result, responses, selected, calls = self.exercise(valid=False)
        self.assertFalse(passed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(selected), 12)
        self.assertEqual(len(result['failed_paper_ids']), 12)
        self.assertEqual(len(responses), 2)
        self.assertIn('fabricated source', responses[0]['output_text'])
        self.assertEqual(responses[0]['input_payload']['papers'][0]['blocks'][0]['text'], 'Novel University')
        self.assertEqual(result['api_usage']['sdk_requests'], 2)

    def test_successful_single_paper_replay_clears_previous_failure(self):
        passed, result, responses, selected, calls = self.exercise(valid=True, sample_size=1)
        self.assertTrue(passed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(result['failed_paper_ids'], [])
        self.assertNotIn('affiliation_model_fallback_failed', result['papers'][0]['affiliation_issues'])

    def test_api_failure_has_no_automatic_network_retries_and_still_saves_results(self):
        passed, result, responses, selected, calls = self.exercise(valid=False, api_error=True)
        self.assertFalse(passed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(responses, [])
        self.assertEqual(len(result['failed_paper_ids']), 12)

    def test_sample_limit_prevents_accidental_full_report_replay(self):
        with self.assertRaisesRegex(ValueError, 'between 1 and 12'):
            diagnose(Path('unused'), Path('unused'), Path('unused'), sample_size=13)


if __name__ == '__main__':
    unittest.main()
