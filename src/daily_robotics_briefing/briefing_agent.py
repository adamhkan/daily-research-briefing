from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a list of arXiv cs.RO papers that were pre-filtered to a single submission date. 
Use the provided first-page PDF text for each paper to understand what the paper is about and to check whether the paper matches the filtering requirements.
Then, create a concise, evidence-based daily briefing.

Output format requirements (markdown):
1) Executive Summary
   - 3-6 bullets summarizing major themes from the included papers.
2) Papers Table
   - A markdown table with exactly these columns:
     Title | Institution | Overview | Link
   - Institution should be a best-effort name from provided metadata; use "Unknown" if unavailable.
   - Link must be the arXiv abstract URL.
   - Overview should be 3-4 concise sentences describing the most important technical aspects of the paper.
   - Papers with authors from the filtered institutions should be listed first. Then, list papers with topic areas that match the requested topics, in descending order of relevance.
   - Don't include any papers more than once in the table.

Filtering requirements:
- Include a paper only if it matches at least one institution OR at least one topic.
- Institution match: infer likely author institutions from provided metadata and the included first-page PDF text, then compare against user-provided institution entries using best-effort semantic matching.
- Topic match: compare user-provided topic entries against title, abstract, and subject information using best-effort semantic matching.
- If institutions and topics are both empty, include all provided papers.

Rules:
- Use only papers from the provided dataset and submission date.
- Do not add papers that are not in the provided papers list.
- Do not add any extra sections.
- If no papers match filters, say so briefly and output an empty table with headers.
""".strip()


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
        "institutions": institutions,
        "topics": topics,
        "paper_count": len(papers),
        "papers": papers,
    }

    system_message = {"role": "system", "content": SYSTEM_PROMPT}
    user_message = {
        "role": "user",
        "content": (
            "Build today's robotics briefing from the following JSON dataset. "
            "First apply the requested institution/topic filtering to the provided papers, "
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
