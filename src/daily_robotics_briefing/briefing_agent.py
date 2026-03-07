from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a list of arXiv cs.RO papers that were already pre-filtered to a single submission date.
Create a concise, evidence-based daily briefing.

Output format requirements (markdown):
1) Executive Summary
   - 3-6 bullets summarizing major themes from the provided papers.
2) Papers Table
   - A markdown table with exactly these columns:
     Title | Institution | Overview | Link
   - Institution should be a best-effort name from provided metadata; use "Unknown" if unavailable.
   - Link must be the arXiv abstract URL.
   - Overview should be 3-4 concise sentences describing the most important technical aspects of the paper.

Rules:
- Use only papers from the provided dataset and submission date.
- Do not add any extra sections.
- If there are no papers, say so briefly and output an empty table with headers.
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
            "This dataset only contains cs.RO papers for one submission date; "
            "do not reference papers outside this set.\n\n"
            f"{json.dumps(payload)}"
        ),
    }

    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[system_message, user_message],
            # "Agent mode" style capability: allow model to use web search when needed.
            tools=[{"type": "web_search_preview"}],
        )
        return response.output_text

    # Compatibility path for older OpenAI Python SDK versions that do not
    # implement the Responses API yet.
    response = client.chat.completions.create(
        model=model,
        messages=[system_message, user_message],
    )
    return response.choices[0].message.content or ""
