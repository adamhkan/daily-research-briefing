from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a normalized JSON dataset of arXiv cs.RO papers for exactly one submission date.
Institution filtering was already performed deterministically by the pipeline.
Then, create a concise, evidence-based daily briefing.

Core method:
1) Treat `manual_institution_extraction.filter_match` as the source of truth for institution matches.
2) Evaluate each paper for topic relevance.
3) Keep only papers that satisfy (manual institution match OR topic match).
4) For ranking in the topic table, sort by strongest topical relevance first.

Scoring guidance:
- Topic relevance (0-3):
  0 = unrelated, 1 = tangential mention,
  2 = clear match, 3 = core focus of the paper.

Output format requirements (markdown):
1) Executive Summary
   - List the institution filters and topic filters exactly as provided.
   - 3-6 bullets summarizing major themes from included papers.
2) Institution Matches
   - A markdown table with exactly these columns:
     Title | Institution | Overview | Link
   - Include only papers where `manual_institution_extraction.filter_match` is true.
   - Institution column should use `manual_institution_extraction.filter_match_institutions` joined by `; `.
3) Topic Matches
   - A markdown table with exactly these columns:
     Title | Institution | Overview | Link
   - Include 5-10 papers with highest topic relevance, excluding papers already used in Institution Matches.

Table rules:
- Link must be the arXiv abstract URL.
- Overview should be 2-3 concise sentences focused on technical contributions.
- Never include a paper that was not in the input dataset.
- Never include the same paper twice.

If no papers match filters, briefly state that in Executive Summary and still output both empty tables with headers.
Do not add any extra sections.
""".strip()


def _normalize_filter_entries(entries: list[str]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in entries:
        value = entry.strip()
        if not value:
            continue
        normalized.append(
            {
                "value": value,
                "lowercase": value.lower(),
            }
        )
    return normalized


def create_daily_briefing(
    papers: list[dict[str, Any]],
    institutions: list[str],
    topics: list[str],
    submission_date: date,
    model: str = "gpt-5.1",
) -> str:
    client = OpenAI(http_client=httpx.Client())

    payload = {
        "submission_date": submission_date.isoformat(),
        "filters": {
            "institutions": _normalize_filter_entries(institutions),
            "topics": _normalize_filter_entries(topics),
        },
        "paper_count": len(papers),
        "papers": [
            {
                "paper_id": paper["arxiv_id"],
                "title": paper["title"],
                "authors": paper["authors"],
                "subjects": paper["subjects"],
                "abstract": paper["abstract"],
                "abs_url": paper["abs_url"],
                "manual_institution_extraction": paper.get("manual_institution_extraction", {}),
            }
            for paper in papers
        ],
    }

    system_message = {"role": "system", "content": SYSTEM_PROMPT}
    user_message = {
        "role": "user",
        "content": (
            "Build today's robotics briefing from the following JSON dataset. "
            "Use manual institution extraction fields as authoritative institution filtering, "
            "and apply topic filtering to the provided papers, "
            "then summarize only the papers that match. "
            "Do not reference papers outside this set.\n\n"
            f"{json.dumps(payload)}"
        ),
    }

    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[system_message, user_message],
            reasoning={"effort": "high"},
        )
        return response.output_text

    # Compatibility path for older OpenAI Python SDK versions that do not
    # implement the Responses API yet.
    response = client.chat.completions.create(
        model=model,
        messages=[system_message, user_message],
    )
    return response.choices[0].message.content or ""
