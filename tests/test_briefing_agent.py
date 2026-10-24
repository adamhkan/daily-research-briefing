import json
import unittest
from datetime import date
from unittest.mock import patch

import httpx2
from openai import OpenAI, OpenAIError

from daily_robotics_briefing.briefing_agent import (
    _check_evidence, _responses_create, create_daily_briefing,
)
from daily_robotics_briefing.response_schemas import (
    ClassificationOutput, ExecutiveOutput, OverviewOutput,
)


def paper(pid, *, institution=False, abstract=None):
    return {
        'arxiv_id': pid, 'title': f'Title for {pid}',
        'abs_url': f'https://arxiv.org/abs/{pid}', 'subjects': 'Robotics',
        'abstract': abstract if abstract is not None else 'The authors report 73% success on real robots for manipulation.',
        'manual_institution_extraction': {
            'filter_match': institution,
            'filter_match_institutions': ['EPFL'] if institution else [],
            'paper_level_institutions': ['EPFL' if institution else 'Tsinghua University'],
        },
    }


class ModelStub:
    """Deterministic model substitute; actual task selection still runs in production code."""
    def __init__(self, scores=None):
        self.calls = []
        self.scores = scores or {}

    def __call__(self, client, model, prompt, payload, effort, schema, limit):
        self.calls.append((schema, payload))
        if schema is ClassificationOutput:
            rows = []
            for p in payload['papers']:
                relevance, contribution = self.scores.get(p['paper_id'], (3, 2))
                rows.append(dict(paper_id=p['paper_id'], topic_relevance=relevance,
                                 contribution_score=contribution, rationale='Relevant robotics work.'))
            return json.dumps({'papers': rows})
        if schema is OverviewOutput:
            return json.dumps({'papers': [
                {'paper_id': p['paper_id'], 'claims': [
                    {'claim': p['abstract'], 'evidence_quote': p['abstract']}
                ]} for p in payload['papers']
            ]})
        return json.dumps({'bullets': [
            {'text': p['overview'], 'paper_ids': [p['paper_id']]}
            for p in payload['papers'][:6]
        ]})


class BriefingTests(unittest.TestCase):
    def generate(self, papers, stub=None, **kwargs):
        stub = stub or ModelStub()
        with patch('daily_robotics_briefing.briefing_agent.OpenAI'), patch(
            'daily_robotics_briefing.briefing_agent._responses_create', side_effect=stub
        ):
            result = create_daily_briefing(papers, ['EPFL'], ['manipulation'], date(2026, 10, 20), **kwargs)
        return result, stub

    def test_all_160_papers_classified_including_late_institution_match(self):
        papers = [paper(f'{i:03}') for i in range(159)] + [paper('last', institution=True)]
        result, stub = self.generate(papers, max_topic_matches=2, classification_batch_size=25)
        classified = [p['paper_id'] for schema, payload in stub.calls
                      if schema is ClassificationOutput for p in payload['papers']]
        self.assertEqual(classified, [p['arxiv_id'] for p in papers])
        self.assertEqual(result['paper_count'], 160)
        self.assertEqual(len(result['papers']), 160)
        self.assertEqual([p['paper_id'] for p in result['briefing']['institution_matches']], ['last'])
        self.assertEqual(result['selected_paper_count'], 3)

    def test_ranking_precedes_summarization_and_executive_sees_only_displayed_rows(self):
        stub = ModelStub({'low': (2, 3), 'high': (3, 3), 'middle': (3, 1), 'inst': (0, 0)})
        result, _ = self.generate([paper('low'), paper('middle'), paper('high'), paper('inst', institution=True)],
                                  stub, max_topic_matches=1, summary_batch_size=1)
        briefing = result['briefing']
        self.assertEqual([r['paper_id'] for r in briefing['topic_matches']], ['high'])
        self.assertEqual([r['paper_id'] for r in briefing['institution_matches']], ['inst'])
        for schema, payload in stub.calls:
            if schema in (OverviewOutput, ExecutiveOutput):
                self.assertTrue({p['paper_id'] for p in payload['papers']} <= {'high', 'inst'})
        self.assertEqual(briefing['institution_matches'][0]['institution'], 'EPFL')
        self.assertEqual(briefing['topic_matches'][0]['institution'], 'Tsinghua University')
        self.assertTrue(briefing['topic_matches'][0]['evidence'])

    def test_classification_uses_full_abstract(self):
        abstract = 'Background. ' * 100 + 'The authors report 73% success for manipulation.'
        result, stub = self.generate([paper('p', abstract=abstract)])
        self.assertEqual(stub.calls[0][1]['papers'][0]['abstract'], abstract)
        self.assertIn('73%', result['briefing']['topic_matches'][0]['overview'])

    def test_classification_needs_only_scores_and_a_short_rationale(self):
        result, stub = self.generate([paper('p')])
        row = result['papers'][0]
        self.assertEqual(row['topic_relevance'], 3)
        self.assertEqual(row['contribution_score'], 2)
        self.assertEqual(row['topic_rationale'], 'Relevant robotics work.')
        self.assertNotIn(row['topic_rationale'], paper('p')['abstract'])
        self.assertNotIn('topic_evidence_quote', row)
        self.assertEqual(sum(schema is ClassificationOutput for schema, _ in stub.calls), 1)

    def test_equal_scores_are_ordered_by_id_not_model_or_input_order(self):
        first, _ = self.generate([paper('b'), paper('a')], max_topic_matches=1)
        second, _ = self.generate([paper('a'), paper('b')], max_topic_matches=1)
        self.assertEqual(first['briefing'], second['briefing'])

    def test_zero_topic_limit_preserves_institutions(self):
        result, _ = self.generate([paper('topic'), paper('inst', institution=True)], max_topic_matches=0)
        self.assertEqual(result['briefing']['topic_matches'], [])
        self.assertEqual(len(result['briefing']['institution_matches']), 1)

    def test_missing_unknown_or_duplicate_classifications_fail_after_one_repair(self):
        stub = ModelStub()
        valid = json.loads(stub(None, '', '', {'papers': [{**paper('p'), 'paper_id': 'p'}]}, '', ClassificationOutput, 100))
        for rows in [[], valid['papers'] * 2, [{**valid['papers'][0], 'paper_id': 'unknown'}]]:
            with self.subTest(rows=rows):
                with patch('daily_robotics_briefing.briefing_agent.OpenAI'), patch(
                    'daily_robotics_briefing.briefing_agent._responses_create',
                    return_value=json.dumps({'papers': rows})
                ) as request:
                    with self.assertRaisesRegex(ValueError, 'after two attempts'):
                        create_daily_briefing([paper('p')], [], [], date(2026, 10, 20))
                    self.assertEqual(request.call_count, 2)

    def test_invalid_response_is_repaired_with_bounded_retry(self):
        stub = ModelStub()
        count = 0
        def respond(*args):
            nonlocal count
            count += 1
            return '{' if count == 1 else stub(*args)
        result, _ = self.generate([paper('p')], respond)
        self.assertEqual(result['selected_paper_count'], 1)
        self.assertEqual(count, 4)

    def test_unquoted_evidence_and_unsupported_numbers_are_rejected(self):
        for claim, quote in [('Reported 99% success.', '73% success'), ('A claim.', 'made up quote')]:
            with self.subTest(claim=claim):
                with self.assertRaises(ValueError):
                    _check_evidence(claim, quote, 'The authors report 73% success.')
        _check_evidence('Reported 73% success.', '73% success', 'The authors report 73% success.')

    def test_executive_cannot_cite_hidden_papers_or_duplicate_citations(self):
        for bullet in [dict(text='A finding.', paper_ids=['hidden']),
                       dict(text='Reported 73% success.', paper_ids=['p', 'p'])]:
            stub = ModelStub()
            attempts = []
            def respond(*args):
                if args[5] is ExecutiveOutput:
                    attempts.append(args[2])
                    return json.dumps({'bullets': [bullet]})
                return stub(*args)
            with self.subTest(bullet=bullet), self.assertLogs(level='WARNING'):
                result, _ = self.generate([paper('p')], respond)
            briefing = result['briefing']
            self.assertEqual(len(attempts), 2)
            self.assertEqual(briefing['executive_summary_evidence'], [dict(
                text=briefing['topic_matches'][0]['overview'], paper_ids=['p'])])

    def test_executive_repair_retains_bullets_with_valid_citations(self):
        stub = ModelStub()
        prompts = []
        valid = dict(text='The authors report 73% success.', paper_ids=['p'])
        invalid = dict(text='A finding from another paper.', paper_ids=['hidden'])
        def respond(*args):
            if args[5] is ExecutiveOutput:
                prompts.append(args[2])
                return json.dumps({'bullets': [valid, invalid]})
            return stub(*args)
        with self.assertLogs(level='WARNING') as logs:
            result, _ = self.generate([paper('p')], respond)
        self.assertEqual(len(prompts), 2)
        self.assertIn('bullet 2 (hidden)', prompts[1])
        self.assertIn('hidden', '\n'.join(logs.output))
        self.assertEqual(result['briefing']['executive_summary_evidence'], [valid])

    def test_executive_repair_can_succeed_without_using_fallback(self):
        stub = ModelStub()
        prompts = []
        def respond(*args):
            if args[5] is ExecutiveOutput:
                prompts.append(args[2])
                pid = 'hidden' if len(prompts) == 1 else 'p'
                return json.dumps({'bullets': [dict(text='Reported 73% success.', paper_ids=[pid])]})
            return stub(*args)
        with self.assertNoLogs(level='WARNING'):
            result, _ = self.generate([paper('p')], respond)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(result['briefing']['executive_summary'], ['Reported 73% success.'])

    def test_executive_fallback_excludes_papers_with_rejected_overviews(self):
        stub = ModelStub()
        executive_payloads = []
        def respond(*args):
            if args[5] is ExecutiveOutput:
                executive_payloads.append(args[3])
                return json.dumps({'bullets': [dict(text='A finding.', paper_ids=['a'])]})
            raw = stub(*args)
            if args[5] is OverviewOutput:
                data = json.loads(raw)
                next(p for p in data['papers'] if p['paper_id'] == 'a')['claims'][0]['evidence_quote'] = 'invented quote'
                return json.dumps(data)
            return raw
        with self.assertLogs(level='WARNING'):
            result, _ = self.generate([paper('a'), paper('b')], respond)
        for payload in executive_payloads:
            self.assertEqual([p['paper_id'] for p in payload['papers']], ['b'])
        self.assertEqual(len(executive_payloads), 2)
        self.assertEqual(result['briefing']['executive_summary_evidence'], [dict(
            text=paper('b')['abstract'], paper_ids=['b'])])

    def test_executive_numeric_presentation_does_not_trigger_literal_token_filtering(self):
        stub = ModelStub()
        attempts = []
        def respond(*args):
            if args[5] is ExecutiveOutput:
                attempts.append(args[2])
                return json.dumps({'bullets': [dict(text='The authors report 73% success.', paper_ids=['p'])]})
            return stub(*args)
        with self.assertNoLogs(level='WARNING'):
            result, _ = self.generate([paper('p', abstract='The authors report success probability 0.73.')], respond)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(result['briefing']['executive_summary'], ['The authors report 73% success.'])

    def test_malformed_or_incomplete_executive_responses_use_verified_overviews(self):
        for response in ['{', '{"bullets": []}', ValueError('Model response was incomplete, refused, or empty')]:
            stub = ModelStub()
            attempts = []
            def respond(*args):
                if args[5] is ExecutiveOutput:
                    attempts.append(args[2])
                    if isinstance(response, Exception):
                        raise response
                    return response
                return stub(*args)
            with self.subTest(response=response), self.assertLogs(level='WARNING'):
                result, _ = self.generate([paper('p')], respond)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(result['briefing']['executive_summary_evidence'], [dict(
                text=paper('p')['abstract'], paper_ids=['p'])])

    def test_executive_service_error_falls_back_without_extra_model_requests(self):
        stub = ModelStub()
        attempts = []
        def respond(*args):
            if args[5] is ExecutiveOutput:
                attempts.append(args[2])
                raise OpenAIError('Service unavailable')
            return stub(*args)
        with self.assertLogs(level='WARNING'):
            result, _ = self.generate([paper('p')], respond)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(result['briefing']['executive_summary'], [paper('p')['abstract']])

    def test_overview_cannot_omit_a_paper(self):
        stub = ModelStub()
        def respond(*args):
            return '{"papers": []}' if args[5] is OverviewOutput else stub(*args)
        with self.assertRaisesRegex(ValueError, 'after two attempts'):
            self.generate([paper('p')], respond)

    def test_bad_overview_evidence_does_not_abort_valid_papers_or_claims(self):
        for quote in ['made up quote', '73% success']:
            stub = ModelStub()
            def respond(*args):
                raw = stub(*args)
                if args[5] is OverviewOutput:
                    data = json.loads(raw)
                    bad = {'claim': 'Reported 99% success.', 'evidence_quote': quote}
                    data['papers'][0]['claims'] = [bad]
                    data['papers'][1]['claims'].append(bad)
                    return json.dumps(data)
                return raw
            with self.subTest(quote=quote), self.assertLogs(level='WARNING') as logs:
                result, _ = self.generate([paper('a'), paper('b'), paper('c')], respond)
            rows = {r['paper_id']: r for r in result['briefing']['topic_matches']}
            self.assertEqual(rows['a']['summary_status'], 'evidence_validation_failed')
            self.assertEqual(rows['a']['evidence'], [])
            self.assertIn('Summary unavailable', rows['a']['overview'])
            for pid in ['b', 'c']:
                self.assertEqual(rows[pid]['summary_status'], 'grounded_in_abstract')
                self.assertEqual(len(rows[pid]['evidence']), 1)
                self.assertNotIn('99%', rows[pid]['overview'])
            executive = [payload for schema, payload in stub.calls if schema is ExecutiveOutput][0]
            self.assertEqual({p['paper_id'] for p in executive['papers']}, {'b', 'c'})
            self.assertEqual(sum(schema is OverviewOutput for schema, _ in stub.calls), 2)
            self.assertIn('a, claim 1', '\n'.join(logs.output))

    def test_all_invalid_overviews_skip_executive_without_claiming_missing_abstracts(self):
        stub = ModelStub()
        def respond(*args):
            raw = stub(*args)
            if args[5] is OverviewOutput:
                data = json.loads(raw)
                data['papers'][0]['claims'][0]['evidence_quote'] = 'invented quote'
                return json.dumps(data)
            return raw
        with self.assertLogs(level='WARNING'):
            result, _ = self.generate([paper('p')], respond)
        self.assertFalse(any(schema is ExecutiveOutput for schema, _ in stub.calls))
        self.assertIn('No verified paper summaries', result['briefing']['executive_summary'][0])

    def test_missing_abstract_does_not_invent_a_summary(self):
        result, stub = self.generate([paper('inst', institution=True, abstract='')], ModelStub({'inst': (0, 0)}))
        row = result['briefing']['institution_matches'][0]
        self.assertEqual(row['summary_status'], 'abstract_unavailable')
        self.assertEqual(row['evidence'], [])
        self.assertEqual([schema for schema, _ in stub.calls], [ClassificationOutput])

    def test_empty_selection_needs_no_overview_or_executive_request(self):
        result, stub = self.generate([paper('p')], ModelStub({'p': (0, 0)}))
        self.assertEqual(result['briefing']['executive_summary'], [])
        self.assertEqual(len(stub.calls), 1)

    def test_schema_rejects_string_scores_and_unexpected_fields(self):
        for rows in [[dict(paper_id='p', topic_relevance='3', contribution_score=2, rationale='r')],
                     [dict(paper_id='p', topic_relevance=3, contribution_score=2, rationale='r', extra=True)]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                ClassificationOutput.model_validate_json(json.dumps({'papers': rows}))

    def test_sdk_serializes_strict_schema_and_reasoning_on_responses_endpoint(self):
        captured = []
        def handler(request):
            captured.append((request.url.path, json.loads(request.content)))
            return httpx2.Response(200, json={
                'id': 'resp_offline', 'object': 'response', 'created_at': 0,
                'status': 'completed', 'model': 'gpt-5.1',
                'output': [{'id': 'msg_offline', 'type': 'message', 'role': 'assistant',
                            'status': 'completed', 'content': [
                                {'type': 'output_text', 'text': '{"papers": []}', 'annotations': []}
                            ]}],
            })
        with OpenAI(api_key='offline-test', http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
            text = _responses_create(client, 'gpt-5.1', 'Classify.', {}, 'low', ClassificationOutput, 2000)
        self.assertEqual(json.loads(text), {'papers': []})
        path, body = captured[0]
        self.assertEqual(path, '/v1/responses')
        self.assertEqual(body['model'], 'gpt-5.1')
        self.assertTrue(body['text']['format']['strict'])
        self.assertFalse(body['text']['format']['schema']['additionalProperties'])
        classification = body['text']['format']['schema']['$defs']['Classification']
        self.assertEqual(set(classification['properties']),
                         {'paper_id', 'topic_relevance', 'contribution_score', 'rationale'})
        self.assertEqual(body['reasoning'], {'effort': 'low'})
        self.assertEqual(body['max_output_tokens'], 2000)


if __name__ == '__main__':
    unittest.main()
