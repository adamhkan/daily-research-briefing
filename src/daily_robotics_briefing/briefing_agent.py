from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a list of arXiv cs.RO papers that were already pre-filtered to a single submission date.
Create a concise but insightful daily briefing.

Requirements:
1) Focus on papers that match either:
   - requested institutions, OR
   - requested topics.
2) If institution match confidence is low, clearly state uncertainty.
3) Output sections in markdown:
   - Executive Summary
   - Institution Highlights
   - Topic Highlights
   - Notable Papers (table with title, why it matters, link)
   - Emerging Trends
   - Recommended Reading Queue (top 10)
4) Be specific and evidence-based; cite arXiv links inline.
5) If no clear matches exist, say so and list closest relevant papers.
6) Do not include papers outside the provided submission date.
""".strip()


def create_daily_briefing(
    papers: list[dict[str, Any]],
    institutions: list[str],
    topics: list[str],
    submission_date: date,
    model: str = "gpt-4.1",
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
