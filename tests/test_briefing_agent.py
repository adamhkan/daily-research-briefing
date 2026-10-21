import json
import unittest
from datetime import date
from unittest.mock import patch

from daily_robotics_briefing.briefing_agent import (
    _validated_match_rows,
    create_daily_briefing,
)


def paper(paper_id, *, institution_match=False, topic_match=True, relevance=3):
    return {
        "arxiv_id": paper_id,
        "title": f"Title for {paper_id}",
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
        "abstract": "A robotics paper.",
        "subjects": "Robotics",
        "institution_match": institution_match,
        "topic_match": topic_match,
        "topic_relevance": relevance,
        "matched_institutions": ["EPFL"] if institution_match else [],
        "manual_institution_extraction": {
            "filter_match": institution_match,
            "filter_match_institutions": ["EPFL"] if institution_match else [],
            "paper_level_institutions": ["EPFL" if institution_match else "Tsinghua University"],
        },
    }


def row(paper_id):
    return {
        "paper_id": paper_id,
        "title": "Invented title",
        "link": "https://example.com/invented",
        "institution": "Invented institution",
        "overview": f"Overview for {paper_id}",
    }


class ValidatedMatchRowsTests(unittest.TestCase):
    def test_topic_only_paper_cannot_be_an_institution_match(self):
        institutions, topics = _validated_match_rows(
            {"institution_matches": [row("topic-only")]},
            [paper("topic-only")],
            10,
        )
        self.assertEqual(institutions, [])
        self.assertEqual([r["paper_id"] for r in topics], ["topic-only"])
        self.assertEqual(topics[0]["institution"], "Tsinghua University")
        self.assertEqual(topics[0]["title"], "Title for topic-only")
        self.assertEqual(topics[0]["link"], "https://arxiv.org/abs/topic-only")
        self.assertEqual(topics[0]["overview"], "Overview for topic-only")

    def test_institution_match_takes_precedence_and_papers_are_unique(self):
        institutions, topics = _validated_match_rows(
            {
                "institution_matches": [row("topic-only"), row("topic-only")],
                "topic_matches": [row("institution"), row("topic-only")],
            },
            [paper("topic-only"), paper("institution", institution_match=True, topic_match=False)],
            10,
        )
        self.assertEqual([r["paper_id"] for r in institutions], ["institution"])
        self.assertEqual(institutions[0]["institution"], "EPFL")
        self.assertEqual([r["paper_id"] for r in topics], ["topic-only"])

    def test_unknown_and_unmatched_papers_are_rejected(self):
        institutions, topics = _validated_match_rows(
            {"institution_matches": [row("unknown"), row("unmatched")]},
            [paper("unmatched", topic_match=False)],
            10,
        )
        self.assertEqual((institutions, topics), ([], []))

    def test_topics_are_ranked_and_capped_after_reclassification(self):
        summary = {
            "institution_matches": [row("low"), row("high")],
            "topic_matches": [row("middle")],
        }
        papers = [
            paper("low", relevance=1),
            paper("high", relevance=3),
            paper("middle", relevance=2),
        ]
        institutions, topics = _validated_match_rows(summary, papers, 2)
        self.assertEqual(institutions, [])
        self.assertEqual([r["paper_id"] for r in topics], ["high", "middle"])
        self.assertEqual(_validated_match_rows(summary, papers, 0), ([], []))

    def test_missing_or_malformed_sections_do_not_create_rows(self):
        for summary in [{}, {"institution_matches": None, "topic_matches": [None, 7]}]:
            with self.subTest(summary=summary):
                self.assertEqual(_validated_match_rows(summary, [paper("topic")], 10), ([], []))

    @patch("daily_robotics_briefing.briefing_agent.OpenAI")
    @patch("daily_robotics_briefing.briefing_agent._responses_create")
    def test_daily_briefing_enforces_flags_when_model_ignores_instructions(self, responses, client):
        responses.side_effect = [
            json.dumps({"papers": [
                {"paper_id": "topic", "topic_relevance": 3, "topic_match": True},
                {"paper_id": "institution", "topic_relevance": 0, "topic_match": False},
            ]}),
            json.dumps({
                "executive_summary": ["A summary."],
                "institution_matches": [row("topic"), row("unknown")],
                "topic_matches": [row("institution"), row("topic")],
            }),
        ]
        result = create_daily_briefing(
            [paper("topic"), paper("institution", institution_match=True)],
            institutions=["EPFL"],
            topics=["manipulation"],
            submission_date=date(2026, 10, 20),
        )
        self.assertEqual(responses.call_count, 2)
        briefing = result["briefing"]
        self.assertEqual([r["paper_id"] for r in briefing["institution_matches"]], ["institution"])
        self.assertEqual([r["paper_id"] for r in briefing["topic_matches"]], ["topic"])
        self.assertEqual(briefing["executive_summary"], ["A summary."])


if __name__ == "__main__":
    unittest.main()
