"""The model owns content; code checks response structure and references only."""
import json
import unittest
from datetime import date
from unittest.mock import patch

from openai import OpenAIError

from daily_robotics_briefing.affiliations import AFFILIATION_PROMPT, identify_institutions
from daily_robotics_briefing.briefing_agent import OVERVIEW_PROMPT, _request_validated, create_daily_briefing
from daily_robotics_briefing.response_schemas import AffiliationOutput, ClassificationOutput, ExecutiveOutput, OverviewOutput
from test_briefing_agent import ModelStub, paper


def source_record():
    record = dict(paper('p'), authors=['Jane Doe'], affiliation_blocks=[dict(
        id='b', text='MIT', kind='header_context', authors=[],
        source_url='https://example.org/p', locator='#authors')])
    record.pop('manual_institution_extraction')
    return record


def affiliation_response(payload, *, complete=True):
    return json.dumps({'papers': [dict(paper_id=p['paper_id'], complete=complete,
        affiliations=[dict(institution='Massachusetts Institute of Technology', authors=['Jane Doe'],
                           block_id='b', role='author_affiliation')]) for p in payload['papers']]})


class ModelOutputContractTests(unittest.TestCase):
    def test_quote_fields_and_requirements_are_absent(self):
        for schema, prompt in [(AffiliationOutput, AFFILIATION_PROMPT), (OverviewOutput, OVERVIEW_PROMPT)]:
            self.assertNotIn('evidence_quote', json.dumps(schema.model_json_schema()))
            self.assertNotIn('evidence_quote', prompt)

    def test_paraphrased_claim_is_preserved_without_quote_or_number_comparison(self):
        stub = ModelStub()
        calls = []
        text = 'The authors report 73% success.'
        def respond(*args):
            calls.append(args[5])
            if args[5] is OverviewOutput:
                return json.dumps({'papers': [dict(paper_id='p', claims=[dict(claim=text)])]})
            return stub(*args)
        with patch('daily_robotics_briefing.briefing_agent.OpenAI'), \
                patch('daily_robotics_briefing.briefing_agent._responses_create', side_effect=respond):
            result = create_daily_briefing([paper('p', abstract='Success probability was 0.73.')], [], [], date(2026, 10, 24))
        row = result['briefing']['topic_matches'][0]
        self.assertEqual(row['overview'], text)
        self.assertEqual(row['claims'], [text])
        self.assertEqual(row['summary_status'], 'model_generated')
        self.assertNotIn('evidence', row)
        self.assertEqual(calls, [ClassificationOutput, OverviewOutput, ExecutiveOutput])

    def test_model_names_and_author_associations_are_not_compared_to_source_text(self):
        record = source_record()
        with patch('daily_robotics_briefing.briefing_agent._responses_create',
                   side_effect=lambda *a: affiliation_response(a[3])) as request:
            identify_institutions([record], ['Massachusetts Institute of Technology'],
                                  ['Massachusetts Institute of Technology'], None, 'offline', _request_validated)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(record['affiliation_evidence'][0]['authors'], ['Jane Doe'])
        self.assertNotIn('evidence_quote', record['affiliation_evidence'][0])
        self.assertEqual(record['institution_match_status'], 'matched')

    def test_wrong_affiliation_references_fail_without_salvage(self):
        for change in [dict(block_id='missing'), dict(authors=['Unknown Author'])]:
            record = source_record()
            data = json.loads(affiliation_response(dict(papers=[dict(paper_id='p')])))
            data['papers'][0]['affiliations'][0].update(change)
            with self.subTest(change=change), \
                    patch('daily_robotics_briefing.briefing_agent._responses_create', return_value=json.dumps(data)) as request:
                with self.assertRaisesRegex(ValueError, 'after two attempts'):
                    identify_institutions([record], [], [], None, 'offline', _request_validated)
                self.assertEqual(request.call_count, 2)
                self.assertNotIn('manual_institution_extraction', record)

    def test_independent_authors_can_have_complete_empty_institution_list(self):
        record = source_record()
        record['affiliation_blocks'][0]['text'] = 'Independent researcher'
        with patch('daily_robotics_briefing.briefing_agent._responses_create', return_value=json.dumps(
                dict(papers=[dict(paper_id='p', complete=True, affiliations=[])]))):
            identify_institutions([record], [], [], None, 'offline', _request_validated)
        self.assertTrue(record['affiliation_complete'])
        self.assertEqual(record['institution_match_status'], 'no_match')

    def test_affiliation_paper_coverage_still_requires_exact_ids(self):
        valid = dict(paper_id='p', complete=True, affiliations=[])
        for rows in [[], [valid, valid], [dict(valid, paper_id='other')]]:
            with self.subTest(rows=rows), patch(
                    'daily_robotics_briefing.briefing_agent._responses_create',
                    return_value=json.dumps(dict(papers=rows))) as request:
                with self.assertRaisesRegex(ValueError, 'after two attempts'):
                    identify_institutions([source_record()], [], [], None, 'offline', _request_validated)
                self.assertEqual(request.call_count, 2)

    def test_executive_citation_errors_fail_without_substitute_bullets(self):
        for ids in [['hidden'], ['p', 'p']]:
            stub = ModelStub()
            attempts = []
            def respond(*args):
                if args[5] is ExecutiveOutput:
                    attempts.append(args[2])
                    return json.dumps(dict(bullets=[dict(text='A summary.', paper_ids=ids)]))
                return stub(*args)
            with self.subTest(ids=ids), patch('daily_robotics_briefing.briefing_agent.OpenAI'), \
                    patch('daily_robotics_briefing.briefing_agent._responses_create', side_effect=respond):
                with self.assertRaisesRegex(ValueError, 'after two attempts'):
                    create_daily_briefing([paper('p')], [], [], date(2026, 10, 24))
                self.assertEqual(len(attempts), 2)

    def test_schema_and_service_failures_propagate_in_every_stage(self):
        for stage in [AffiliationOutput, ClassificationOutput, OverviewOutput, ExecutiveOutput]:
            for failure in ['{', OpenAIError('Offline service failure')]:
                stub = ModelStub()
                attempts = []
                def respond(*args):
                    if args[5] is stage:
                        attempts.append(args[2])
                        if isinstance(failure, Exception):
                            raise failure
                        return failure
                    if args[5] is AffiliationOutput:
                        return affiliation_response(args[3])
                    return stub(*args)
                with self.subTest(stage=stage.__name__, failure=failure), \
                        patch('daily_robotics_briefing.briefing_agent.OpenAI'), \
                        patch('daily_robotics_briefing.briefing_agent._responses_create', side_effect=respond):
                    with self.assertRaises(OpenAIError if isinstance(failure, Exception) else ValueError):
                        create_daily_briefing([source_record()], [], [], date(2026, 10, 24),
                                              institution_entries=['Massachusetts Institute of Technology'])
                    self.assertEqual(len(attempts), 1 if isinstance(failure, Exception) else 2)
