from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a normalized JSON dataset of arXiv cs.RO papers for exactly one submission date.
Carefully inspect metadata and first-page PDF text to infer institution and topic relevance.
Then, create a concise, evidence-based daily briefing.

Core method:
1) Evaluate each paper for institution relevance and topic relevance independently.
2) Keep only papers that satisfy (institution_match OR topic_match).
3) For ranking in the topic table, sort by strongest topical relevance first.

Scoring guidance:
- Institution confidence (0-3):
  0 = no institution evidence, 1 = weak/indirect evidence,
  2 = likely match, 3 = explicit affiliation evidence.
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
   - Include only papers where institution confidence >= 2.
3) Topic Matches
   - A markdown table with exactly these columns:
     Title | Institution | Overview | Link
   - Include 5-10 papers with highest topic relevance, excluding papers already used in Institution Matches.

Table rules:
- Institution should be best-effort from provided metadata/text; use "Unknown" if unavailable.
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
                "pdf_first_page_text": paper["pdf_first_page_text"],
            }
            for paper in papers
        ],
    }

    system_message = {"role": "system", "content": SYSTEM_PROMPT}
    user_message = {
        "role": "user",
        "content": (
            "Build today's robotics briefing from the following JSON dataset. "
            "First apply institution/topic filtering to the provided papers, "
            "then summarize only the papers that match. "
            "Use robust semantic matching and confidence scoring guidance from the system prompt. "
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
