"""The pilot queues real model tasks while keeping the paid SDK unreachable."""
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daily_robotics_briefing.briefing_agent import _request_validated, create_daily_briefing
from daily_robotics_briefing.codex_transport import (
    FileResponseProvider, PendingModelRequest, RequestLimitExceeded,
    request_envelope, request_identifier,
)
from daily_robotics_briefing.response_schemas import (
    AffiliationOutput, ClassificationOutput, ExecutiveOutput, OverviewOutput,
)
from test_briefing_agent import ModelStub, paper


class FileResponseProviderTests(unittest.TestCase):
    def invoke(self, provider, prompt='Classify.', schema=ClassificationOutput):
        return provider('codex-session', prompt, {'papers': [{'paper_id': 'p'}]},
                        'low', schema, 2000)

    def test_request_is_saved_once_and_pauses_without_entering_repair(self):
        with TemporaryDirectory() as tmp:
            provider = FileResponseProvider(tmp)
            client = SimpleNamespace(briefing_response_provider=provider)
            with self.assertRaises(PendingModelRequest) as pending:
                _request_validated(client, 'codex-session', 'Classify.',
                                   {'papers': [{'paper_id': 'p'}]}, ClassificationOutput,
                                   lambda result: None, 2000)
            request = json.loads(pending.exception.request_path.read_text())
            self.assertEqual(pending.exception.request_id, request_identifier(request))
            self.assertEqual(request['model'], 'codex-session')
            self.assertEqual(request['input'][0], {'role': 'system', 'content': 'Classify.'})
            self.assertEqual(json.loads(request['input'][1]['content']), {'papers': [{'paper_id': 'p'}]})
            self.assertEqual(request['text']['format']['schema'], ClassificationOutput.model_json_schema())
            self.assertEqual(request['reasoning'], {'effort': 'low'})
            self.assertEqual(request['max_output_tokens'], 2000)
            with self.assertRaises(PendingModelRequest) as repeated:
                self.invoke(provider)
            self.assertEqual(repeated.exception.request_id, pending.exception.request_id)
            self.assertEqual(len(list(provider.requests_dir.glob('*.json'))), 1)
            self.assertEqual(list(provider.requests_dir.glob('*.tmp')), [])

    def test_response_is_replayed_raw_for_production_validation(self):
        with TemporaryDirectory() as tmp:
            provider = FileResponseProvider(tmp)
            with self.assertRaises(PendingModelRequest) as pending:
                self.invoke(provider)
            response = '{"papers": []}'
            (provider.responses_dir / (pending.exception.request_id + '.json')).write_text(response)
            self.assertEqual(self.invoke(provider), response)
            # A malformed saved response also reaches production's normal repair
            # handling rather than being mistaken for another pending request.
            (provider.responses_dir / (pending.exception.request_id + '.json')).write_text('{')
            self.assertEqual(self.invoke(provider), '{')

    def test_prompt_schema_and_settings_are_part_of_content_identity(self):
        base = request_envelope('codex-session', 'Classify.', {'papers': []},
                                'low', ClassificationOutput, 2000)
        self.assertEqual(request_identifier(base), request_identifier(dict(reversed(list(base.items())))))
        variants = [request_envelope('codex-session', 'Repair.', {'papers': []}, 'low', ClassificationOutput, 2000),
                    request_envelope('codex-session', 'Classify.', {'papers': []}, 'low', ExecutiveOutput, 2000),
                    request_envelope('codex-session', 'Classify.', {'papers': []}, 'low', ClassificationOutput, 3000)]
        self.assertTrue(all(request_identifier(v) != request_identifier(base) for v in variants))

    def test_cap_blocks_only_new_distinct_requests(self):
        with TemporaryDirectory() as tmp:
            provider = FileResponseProvider(tmp, max_requests=1)
            with self.assertRaises(PendingModelRequest) as pending:
                self.invoke(provider)
            with self.assertRaises(PendingModelRequest):
                self.invoke(provider)
            with self.assertRaises(RequestLimitExceeded):
                self.invoke(provider, prompt='Repair.')
            (provider.responses_dir / (pending.exception.request_id + '.json')).write_text('{"papers": []}')
            self.assertEqual(self.invoke(provider), '{"papers": []}')
            self.assertEqual(len(list(provider.requests_dir.glob('*.json'))), 1)

    def test_pending_signal_is_not_treated_as_invalid_model_output(self):
        self.assertFalse(issubclass(PendingModelRequest, ValueError))
        self.assertFalse(issubclass(RequestLimitExceeded, ValueError))
        with self.assertRaises(ValueError):
            FileResponseProvider('unused', max_requests=0)

    def test_changed_saved_request_fails_instead_of_silently_overwriting(self):
        with TemporaryDirectory() as tmp:
            provider = FileResponseProvider(tmp)
            with self.assertRaises(PendingModelRequest) as pending:
                self.invoke(provider)
            pending.exception.request_path.write_text('{"changed": true}')
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                self.invoke(provider)
            self.assertEqual(json.loads(pending.exception.request_path.read_text()), {'changed': True})

    def test_provider_path_runs_every_stage_without_constructing_openai(self):
        stub = ModelStub()
        calls = []
        def provider(model, prompt, payload, effort, schema, limit):
            calls.append(schema)
            if schema is AffiliationOutput:
                return json.dumps({'papers': [dict(
                    paper_id=p['paper_id'], complete=True,
                    affiliations=[dict(institution='EPFL', authors=[], block_id=p['blocks'][0]['id'],
                                       evidence_quote='EPFL', role='author_affiliation')],
                ) for p in payload['papers']]})
            return stub(None, model, prompt, payload, effort, schema, limit)
        record = paper('p')
        record.update(authors=[], affiliation_blocks=[dict(id='b', kind='header_context', text='EPFL',
                                                           authors=[], source_url='https://example.org', locator='#header')])
        with patch('daily_robotics_briefing.briefing_agent.OpenAI',
                   side_effect=AssertionError('paid SDK must not be constructed')):
            result = create_daily_briefing([record], ['EPFL'], ['manipulation'], date(2026, 10, 20),
                                           institution_entries=['EPFL'], model='codex-session',
                                           response_provider=provider)
        self.assertEqual(calls, [AffiliationOutput, ClassificationOutput, OverviewOutput, ExecutiveOutput])
        self.assertEqual(result['selected_paper_count'], 1)
        self.assertEqual(result['briefing']['institution_matches'][0]['paper_id'], 'p')
        self.assertIn('73%', result['briefing']['executive_summary'][0])


if __name__ == '__main__':
    unittest.main()
