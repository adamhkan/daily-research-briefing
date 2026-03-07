from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

SYSTEM_PROMPT = """
You are a robotics research scout.
You are given a large list of recent arXiv cs.RO papers.
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
""".strip()


def create_daily_briefing(
    papers: list[dict[str, Any]],
    institutions: list[str],
    topics: list[str],
    model: str = "gpt-4.1",
) -> str:
    client = OpenAI()

    payload = {
        "institutions": institutions,
        "topics": topics,
        "paper_count": len(papers),
        "papers": papers,
    }

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Build today's robotics briefing from the following JSON dataset. "
                    "Treat this as a full scan of recent cs.RO papers.\n\n"
                    f"{json.dumps(payload)}"
                ),
            },
        ],
        # "Agent mode" style capability: allow model to use web search when needed.
        tools=[{"type": "web_search_preview"}],
    )

    return response.output_text
