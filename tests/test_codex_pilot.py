"""Integration coverage for resumable file-driven briefings, with API construction forbidden."""
import copy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import yaml

from daily_robotics_briefing import codex_pilot as pilot
from daily_robotics_briefing.collector import Paper


class CodexPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run'
        self.filters = self.root / 'filters.yaml'
        self.filters.write_text(yaml.safe_dump(dict(institutions=['EPFL'], topics=['manipulation'])))
        self.source = self.root / 'baseline.json'
        papers = []
        for pid, institution in [('one', 'EPFL'), ('two', 'Novel Robotics Laboratory')]:
            paper = Paper(pid, 'Robotics ' + pid, ['Jane Doe'], 'cs.RO',
                          'The authors report 73% success on real robots for manipulation.',
                          'https://arxiv.org/abs/' + pid, 'https://arxiv.org/pdf/' + pid,
                          affiliation_blocks=[dict(id='b', text=institution, kind='header_context',
                              authors=[], source_url='https://example.org/' + pid, locator='#authors')],
                          affiliation_issues=['html_link_missing', 'affiliation_model_claim_rejected'])
            papers.append(paper.to_dict())
        self.source.write_text(json.dumps(dict(submission_date='2026-10-22', papers=papers,
            briefing=dict(institution_matches=[dict(paper_id='one')], topic_matches=[]))))
        self.forbid_sdk = patch('daily_robotics_briefing.briefing_agent.OpenAI',
                                side_effect=AssertionError('Pilot must never construct OpenAI'))
        self.sdk = self.forbid_sdk.start()
        self.addCleanup(self.forbid_sdk.stop)

    def prepare(self, **kwargs):
        return pilot.prepare(self.run, date(2026, 10, 23), self.filters, self.source, **kwargs)

    def read(self, name):
        return json.loads((self.run / name).read_text())

    def response(self, request):
        schema = request['text']['format']['name']
        payload = json.loads(request['input'][1]['content'])
        if schema == 'AffiliationOutput':
            return dict(papers=[dict(paper_id=p['paper_id'], complete=True, affiliations=[dict(
                institution=p['blocks'][0]['text'], authors=[], block_id=p['blocks'][0]['id'],
                evidence_quote=p['blocks'][0]['text'], role='author_affiliation')]) for p in payload['papers']])
        if schema == 'ClassificationOutput':
            return dict(papers=[dict(paper_id=p['paper_id'], topic_relevance=3,
                contribution_score=2, rationale='Direct manipulation contribution.') for p in payload['papers']])
        if schema == 'OverviewOutput':
            return dict(papers=[dict(paper_id=p['paper_id'], claims=[dict(
                claim=p['abstract'], evidence_quote=p['abstract'])]) for p in payload['papers']])
        if schema == 'ExecutiveOutput':
            return dict(bullets=[dict(text=p['overview'], paper_ids=[p['paper_id']]) for p in payload['papers']])
        self.fail('Unexpected schema: ' + schema)

    def submit(self, state, value):
        scratch = self.root / 'response.json'
        scratch.write_text(json.dumps(value))
        return pilot.submit(self.run, state['request_id'], scratch)

    def finish(self):
        schemas = []
        for _ in range(12):
            state = pilot.advance(self.run)
            if state['status'] != 'waiting':
                return state, schemas
            request = json.loads(Path(state['request_path']).read_text())
            schemas.append(request['text']['format']['name'])
            self.submit(state, self.response(request))
        self.fail('Pilot did not finish within the expected bounded requests')

    def test_full_pipeline_resumes_and_renders_without_api_or_mutating_source(self):
        self.assertEqual(self.prepare()['status'], 'ready')
        frozen = (self.run / 'source.json').read_bytes()
        first = pilot.advance(self.run)
        second = pilot.advance(self.run)
        self.assertEqual(first['status'], 'waiting')
        self.assertEqual(first['request_id'], second['request_id'])
        self.assertEqual(len(list((self.run / 'requests').glob('*.json'))), 1)
        # A changed user config must not silently change this run's frozen input.
        self.filters.write_text(yaml.safe_dump(dict(institutions=[], topics=[])))
        final, schemas = self.finish()
        self.assertEqual(final['status'], 'complete')
        self.assertEqual(schemas, ['AffiliationOutput', 'ClassificationOutput', 'OverviewOutput', 'ExecutiveOutput'])
        self.assertEqual((self.run / 'source.json').read_bytes(), frozen)
        self.assertEqual(self.read('source.json')['papers'][0]['affiliation_issues'], ['html_link_missing'])
        for path in ['report/briefing.json', 'report/briefing.md', 'report/briefing.html', 'report/index.html']:
            self.assertGreater((self.run / path).stat().st_size, 100)
        report = self.read('report/briefing.json')
        self.assertEqual(report['api_usage']['sdk_requests'], 0)
        self.assertEqual(report['codex_pilot']['request_count'], 4)
        self.assertIsNone(report['codex_pilot']['codex_token_usage'])
        metrics = self.read('metrics.json')
        self.assertEqual(metrics['api_requests'], 0)
        self.assertEqual(metrics['paper_count'], 2)
        self.assertEqual(metrics['selected_paper_count'], 2)
        self.assertEqual(metrics['summaries_without_evidence'], 0)
        self.assertEqual(metrics['repair_request_count'], 0)
        self.assertEqual(metrics['requests_by_stage']['AffiliationOutput'], 1)
        self.assertIsNone(metrics['codex_token_usage'])
        comparison = self.read('comparison.json')
        self.assertEqual(comparison['selected_added'], ['two'])
        self.assertEqual(comparison['selected_removed'], [])
        self.assertIn('neither run is ground truth', comparison['note'])
        self.assertEqual(pilot.advance(self.run)['status'], 'complete')
        self.assertEqual(self.prepare()['status'], 'complete')
        self.assertEqual(len(list((self.run / 'requests').glob('*.json'))), 4)
        self.sdk.assert_not_called()

    def test_submit_is_idempotent_but_rejects_schema_errors_and_overwrites(self):
        self.prepare()
        state = pilot.advance(self.run)
        request = json.loads(Path(state['request_path']).read_text())
        valid = self.response(request)
        with self.assertRaises(ValueError):
            self.submit(state, dict(papers='invalid'))
        self.assertFalse((self.run / 'responses' / (state['request_id'] + '.json')).exists())
        self.assertEqual(self.submit(state, valid)['status'], 'submitted')
        self.assertEqual(self.submit(state, valid)['status'], 'submitted')
        changed = copy.deepcopy(valid)
        changed['papers'][0]['complete'] = False
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.submit(state, changed)
        self.assertEqual(self.read('responses/' + state['request_id'] + '.json'), valid)
        with self.assertRaisesRegex(ValueError, 'Invalid request ID'):
            pilot.submit(self.run, '../escape', self.root / 'response.json')

    def test_coverage_failure_creates_distinct_real_repair_request_then_recovers(self):
        self.prepare()
        initial = pilot.advance(self.run)
        first_request = json.loads(Path(initial['request_path']).read_text())
        valid = self.response(first_request)
        wrong = copy.deepcopy(valid)
        wrong['papers'][0]['paper_id'] = 'wrong-id'
        self.submit(initial, wrong)
        repair = pilot.advance(self.run)
        self.assertEqual(repair['status'], 'waiting')
        self.assertNotEqual(initial['request_id'], repair['request_id'])
        repair_request = json.loads(Path(repair['request_path']).read_text())
        self.assertIn('Correct this validation error', repair_request['input'][0]['content'])
        self.assertIn('paper_id', repair_request['input'][0]['content'])
        self.assertEqual(repair_request['input'][1], first_request['input'][1])
        self.submit(repair, valid)
        final, schemas = self.finish()
        self.assertEqual(final['status'], 'complete')
        self.assertEqual(schemas, ['ClassificationOutput', 'OverviewOutput', 'ExecutiveOutput'])
        self.assertEqual(self.read('metrics.json')['request_count'], 5)
        self.assertEqual(self.read('metrics.json')['repair_request_count'], 1)
        self.sdk.assert_not_called()

    def test_request_cap_fails_without_new_request_or_sdk_call(self):
        self.prepare(max_requests=1)
        state = pilot.advance(self.run)
        request = json.loads(Path(state['request_path']).read_text())
        self.submit(state, self.response(request))
        failed = pilot.advance(self.run)
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('limit', failed['error'])
        self.assertEqual(len(list((self.run / 'requests').glob('*.json'))), 1)
        self.assertEqual(pilot.advance(self.run)['status'], 'failed')
        self.assertEqual(self.read('metrics.json')['status'], 'failed')
        self.assertEqual(self.read('metrics.json')['request_count'], 1)
        self.sdk.assert_not_called()

    def test_interrupted_preparation_does_not_publish_partial_checkpoint(self):
        original_write = pilot._write

        def interrupted(path, value):
            if path.name == 'status.json':
                raise OSError('Simulated interruption')
            original_write(path, value)

        with patch.object(pilot, '_write', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'Simulated interruption'):
                self.prepare()
        self.assertFalse(self.run.exists())
        self.assertEqual(list(self.root.glob('.run.prepare-*')), [])
        self.assertEqual(self.prepare()['status'], 'ready')

    def test_no_papers_finishes_without_requests_and_does_not_collect_twice(self):
        with patch('daily_robotics_briefing.codex_pilot.fetch_csro_recent', return_value=[]) as collect:
            initial = pilot.prepare(self.run, date(2026, 10, 23), self.filters)
            self.assertEqual(initial['status'], 'no_papers')
            self.assertEqual(pilot.advance(self.run)['status'], 'no_papers')
            self.assertEqual(pilot.prepare(self.run, date(2026, 10, 23), self.filters)['status'], 'no_papers')
        collect.assert_called_once()
        self.assertEqual(self.read('metrics.json')['api_requests'], 0)
        self.assertEqual(self.read('metrics.json')['request_count'], 0)
        self.assertFalse((self.run / 'report').exists())
        self.sdk.assert_not_called()

    def test_wake_outside_pilot_window_does_not_collect(self):
        config = self.root / 'pilot.json'
        config.write_text(json.dumps(dict(start_date='2026-10-23', end_date='2026-10-25',
            timezone='America/New_York', hour=8, minute=30, pause_paid_api=True,
            output_root=str(self.root / 'scheduled'), max_requests=64, publish=False)))
        with patch('daily_robotics_briefing.codex_pilot.fetch_csro_recent',
                   side_effect=AssertionError('Inactive wake must not collect')):
            for today in [date(2026, 10, 22), date(2026, 10, 26)]:
                self.assertEqual(pilot.wake(config, today=today)['status'], 'inactive')
        self.assertFalse((self.root / 'scheduled').exists())
        self.sdk.assert_not_called()

    def test_frozen_source_tampering_is_detected_and_existing_user_files_preserved(self):
        self.prepare()
        frozen = self.read('source.json')
        frozen['papers'][0]['title'] = 'Tampered title'
        (self.run / 'source.json').write_text(json.dumps(frozen))
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            pilot.advance(self.run)
        other = self.root / 'user-files'
        other.mkdir()
        (other / 'notes.txt').write_text('keep me')
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            pilot.prepare(other, date(2026, 10, 23), self.filters, self.source)
        self.assertEqual((other / 'notes.txt').read_text(), 'keep me')

    def test_status_cli_reports_pending_request_without_mutation(self):
        self.prepare()
        pending = pilot.advance(self.run)
        before = (self.run / 'status.json').read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            code = pilot.main(['status', '--run-dir', str(self.run)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['request_id'], pending['request_id'])
        self.assertEqual((self.run / 'status.json').read_bytes(), before)
