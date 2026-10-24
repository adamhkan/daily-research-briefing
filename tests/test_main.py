import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
import yaml
from bs4 import BeautifulSoup
from openai import OpenAI

from daily_robotics_briefing.collector import Paper
from daily_robotics_briefing.main import main
from daily_robotics_briefing.response_schemas import AffiliationOutput, ClassificationOutput, ExecutiveOutput, OverviewOutput
from test_briefing_agent import ModelStub


class MainTests(unittest.TestCase):
    def test_cli_writes_reports_when_executive_output_remains_malformed(self):
        model = ModelStub()
        attempts = []
        def respond(*args):
            if args[5] is ExecutiveOutput:
                attempts.append(args[2])
                return '{'
            return model(*args)
        record = Paper('p', 'Robotics paper', ['Jane Doe'], 'cs.RO',
                       'The authors report 73% success on real robots for manipulation.',
                       'https://arxiv.org/abs/p', 'https://arxiv.org/pdf/p',
                       affiliation_text='EPFL', affiliation_status='extracted')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'filters.yaml'
            config.write_text(yaml.safe_dump(dict(institutions=['EPFL'], topics=['manipulation'])))
            paths = [root/'briefing.md', root/'briefing.json', root/'briefing.html', root/'index.html']
            argv = ['briefing', '--filters', str(config), '--submission-date', '2026-10-20',
                    '--affiliation-cache-dir', str(root/'cache')]
            for flag, path in zip(['--out', '--out-json', '--out-html', '--dashboard-out'], paths):
                argv += [flag, str(path)]
            with patch('sys.argv', argv), \
                    patch('daily_robotics_briefing.main.fetch_csro_recent', return_value=[record]), \
                    patch('daily_robotics_briefing.briefing_agent.OpenAI'), \
                    patch('daily_robotics_briefing.briefing_agent._responses_create', side_effect=respond), \
                    self.assertLogs(level='WARNING'):
                main()
            self.assertEqual(len(attempts), 2)
            self.assertTrue(all(p.stat().st_size > 100 for p in paths))
            result = json.loads(paths[1].read_text())
            self.assertEqual(result['briefing']['executive_summary_evidence'], [dict(
                text=record.abstract, paper_ids=['p'])])
            self.assertIn('[p](https://arxiv.org/abs/p)', paths[0].read_text())
            self.assertIn('73% success', paths[2].read_text())

    def test_cli_writes_complete_reports_with_sdk_and_affiliation_statuses(self):
        model = ModelStub()
        schemas = {schema.__name__: schema for schema in (AffiliationOutput, ClassificationOutput, OverviewOutput, ExecutiveOutput)}
        def handler(request):
            body = json.loads(request.content)
            schema = schemas[body['text']['format']['name']]
            payload = json.loads(body['input'][1]['content'])
            if schema is AffiliationOutput:
                text = json.dumps({'papers': [dict(paper_id=p['paper_id'], complete=True, affiliations=[
                    dict(institution='Novel University', authors=[], block_id=p['blocks'][0]['id'],
                         evidence_quote=p['blocks'][0]['text'], role='author_affiliation')
                ]) for p in payload['papers']]})
            else:
                text = model(None, body['model'], '', payload, 'low', schema, body['max_output_tokens'])
            return httpx2.Response(200, json={
                'id': 'resp_offline', 'object': 'response', 'created_at': 0,
                'status': 'completed', 'model': body['model'],
                'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120,
                          'input_tokens_details': {'cached_tokens': 10},
                          'output_tokens_details': {'reasoning_tokens': 5}},
                'output': [{'id': 'msg_offline', 'type': 'message', 'role': 'assistant',
                            'status': 'completed', 'content': [
                                {'type': 'output_text', 'text': text, 'annotations': []}
                            ]}],
            })
        client = OpenAI(api_key='offline-test', http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
        papers = []
        for pid, text, status in [('a-unknown', '', 'unknown'), ('nonmatch', 'Tsinghua University', 'extracted'),
                                  ('late-match', 'EPFL', 'extracted'), ('novel', 'Novel University', 'unknown')]:
            papers.append(Paper(pid, 'Robotics paper', ['Jane Doe'], 'cs.RO',
                                'The authors report 73% success on real robots for manipulation.',
                                f'https://arxiv.org/abs/{pid}', f'https://arxiv.org/pdf/{pid}',
                                affiliation_text=text, affiliation_status=status,
                                affiliation_source='html' if text else 'none'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'filters.yaml'
            config.write_text(yaml.safe_dump({'institutions': ['EPFL'], 'topics': ['manipulation'],
                                             'max_papers_for_llm': 1, 'max_topic_matches': 1}))
            paths = [root/'briefing.md', root/'briefing.json', root/'briefing.html', root/'index.html']
            argv = ['briefing', '--filters', str(config), '--submission-date', '2026-10-20',
                    '--affiliation-cache-dir', str(root / 'cache')]
            for flag, path in zip(['--out', '--out-json', '--out-html', '--dashboard-out'], paths):
                argv += [flag, str(path)]
            with patch('sys.argv', argv), patch('daily_robotics_briefing.main.fetch_csro_recent', return_value=papers), patch(
                'daily_robotics_briefing.briefing_agent.OpenAI', return_value=client
            ):
                main()
            self.assertTrue(all(p.stat().st_size > 100 for p in paths))
            result = json.loads(paths[1].read_text())
            self.assertEqual(result['model'], 'gpt-5.1')
            self.assertEqual(result['affiliation_resolution_counts'], {
                'filter_match': 1, 'no_recognized_filter_match': 2,
                'incomplete_extraction': 0, 'no_usable_evidence': 1,
            })
            self.assertEqual((result['papers_fetched'], result['papers_analyzed']), (4, 4))
            self.assertEqual(result['affiliation_extraction_counts'], {
                'complete': 3, 'incomplete': 0, 'no_usable_evidence': 1,
            })
            self.assertEqual(result['affiliation_coverage'], {'matched': 1, 'no_match': 2, 'unknown': 1})
            self.assertEqual(result['api_usage']['sdk_requests'], 7)
            self.assertEqual(result['api_usage']['input_tokens'], 700)
            self.assertEqual(result['api_usage']['reasoning_tokens'], 35)
            self.assertEqual([p['paper_id'] for p in result['briefing']['institution_matches']], ['late-match'])
            self.assertEqual(result['briefing']['topic_matches'][0]['institution'], 'Unknown affiliation')
            self.assertEqual(len([s for s, _ in model.calls if s is ClassificationOutput]), 4)
            html = BeautifulSoup(paths[2].read_text(), 'html.parser')
            self.assertNotIn('2 unknown', html.get_text())
            self.assertNotIn('Affiliations:', html.get_text())
            self.assertIn('Papers in this briefing: 2', html.get_text())
            self.assertTrue(html.select('li a[href="https://arxiv.org/abs/late-match"]'))
            self.assertIn('[late-match](https://arxiv.org/abs/late-match)', paths[0].read_text())


if __name__ == '__main__':
    unittest.main()
