from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx
from openai import OpenAI

CLASSIFICATION_PROMPT = """
You are a robotics-paper triage classifier.
You are given papers for one date and normalized institution/topic filters.
Institution matching was already computed deterministically.

Return JSON only with shape:
{
  "papers": [
    {
      "paper_id": "...",
      "topic_relevance": 0,
      "topic_match": false,
      "rationale": "short justification"
    }
  ]
}

Rules:
- Score topic relevance 0-3.
- topic_match=true when relevance >=2.
- Do not invent paper ids.
- Keep rationale <= 25 words.
- No markdown, no prose, JSON only.
""".strip()

SUMMARY_PROMPT = """
You are a robotics research editor. Build a concise daily briefing from selected papers.

Return JSON only with shape:
{
  "executive_summary": ["bullet", "bullet"],
  "institution_matches": [
    {
      "paper_id": "...",
      "title": "...",
      "institution": "...",
      "overview": "2-3 concise sentences",
      "link": "https://arxiv.org/abs/..."
    }
  ],
  "topic_matches": [
    {
      "paper_id": "...",
      "title": "...",
      "institution": "...",
      "overview": "2-3 concise sentences",
      "link": "https://arxiv.org/abs/..."
    }
  ]
}

Rules:
- Include only provided selected papers.
- Institution section: only papers with institution_match=true.
- Topic section: highest topic relevance first; exclude papers already listed in institution section. There should be no duplicate papers throughout both sections.
- Keep executive_summary to 3-6 bullets.
- JSON only.
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


def _parse_json_response(text: str) -> dict[str, Any]:
    raw = text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _responses_create(
    client: OpenAI,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    effort: str,
) -> str:
    system_message = {"role": "system", "content": system_prompt}
    user_message = {"role": "user", "content": json.dumps(payload)}

    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[system_message, user_message],
            reasoning={"effort": effort},
        )
        return response.output_text

    response = client.chat.completions.create(
        model=model,
        messages=[system_message, user_message],
    )
    return response.choices[0].message.content or "{}"


def _clean_match_rows(rows: Any) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return cleaned
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "paper_id": str(row.get("paper_id", "")),
                "title": str(row.get("title", "")),
                "institution": str(row.get("institution", "")),
                "overview": str(row.get("overview", "")),
                "link": str(row.get("link", "")),
            }
        )
    return cleaned


def _paper_institution_label(paper: dict[str, Any]) -> str:
    def _clean_name(value: Any) -> str:
        name = str(value).strip()
        if not name:
            return ""
        # Common PDF extraction artifact: a stray leading lowercase marker
        # (e.g., "e Chinese University of Hong Kong").
        name = re.sub(r"^[a-z]\s+(?=[A-Z])", "", name)
        return name

    def _unique_join(values: list[Any], limit: int | None = None) -> str:
        cleaned = [_clean_name(value) for value in values]
        cleaned = [value for value in cleaned if value]
        if not cleaned:
            return ""
        unique = list(dict.fromkeys(cleaned))
        if limit is not None:
            unique = unique[:limit]
        return "; ".join(unique)

    matched = paper.get("matched_institutions", [])
    if isinstance(matched, list) and matched:
        value = _unique_join(sorted(matched))
        if value:
            return value

    extraction = paper.get("manual_institution_extraction", {})
    if isinstance(extraction, dict):
        paper_level = extraction.get("paper_level_institutions", [])
        if isinstance(paper_level, list) and paper_level:
            value = _unique_join(paper_level)
            if value:
                return value

        detected = extraction.get("paper_level_detected_institutions", [])
        if isinstance(detected, list) and detected:
            value = _unique_join(detected, limit=3)
            if value:
                return value

        raw_from_authors: list[str] = []
        authors = extraction.get("authors", [])
        if isinstance(authors, list):
            for author in authors:
                if not isinstance(author, dict):
                    continue
                raw = author.get("raw_institutions", [])
                if isinstance(raw, list):
                    raw_from_authors.extend(str(item).strip() for item in raw if str(item).strip())
        if raw_from_authors:
            value = _unique_join(raw_from_authors, limit=3)
            if value:
                return value

    return ""


def create_daily_briefing(
    papers: list[dict[str, Any]],
    institutions: list[str],
    topics: list[str],
    submission_date: date,
    model: str = "gpt-5.1",
    max_topic_matches: int = 10,
) -> dict[str, Any]:
    client = OpenAI(http_client=httpx.Client())

    filters = {
        "institutions": _normalize_filter_entries(institutions),
        "topics": _normalize_filter_entries(topics),
    }

    stage1_payload = {
        "submission_date": submission_date.isoformat(),
        "filters": filters,
        "paper_count": len(papers),
        "papers": [
            {
                "paper_id": paper["arxiv_id"],
                "title": paper["title"],
                "subjects": paper["subjects"],
                "abstract": paper.get("abstract_for_prompt", paper["abstract"]),
                "abs_url": paper["abs_url"],
                "institution_match": bool(
                    paper.get("manual_institution_extraction", {}).get("filter_match", False)
                ),
                "matched_institutions": paper.get("manual_institution_extraction", {}).get(
                    "filter_match_institutions", []
                ),
            }
            for paper in papers
        ],
    }

    stage1_text = _responses_create(
        client=client,
        model=model,
        system_prompt=CLASSIFICATION_PROMPT,
        payload=stage1_payload,
        effort="low",
    )
    stage1_json = _parse_json_response(stage1_text)
    scored_by_id = {
        row.get("paper_id", ""): row for row in stage1_json.get("papers", []) if isinstance(row, dict)
    }

    enriched: list[dict[str, Any]] = []
    for paper in papers:
        pid = paper["arxiv_id"]
        score_row = scored_by_id.get(pid, {})
        topic_relevance = int(score_row.get("topic_relevance", 0) or 0)
        topic_match = bool(score_row.get("topic_match", topic_relevance >= 2))
        institution_match = bool(
            paper.get("manual_institution_extraction", {}).get("filter_match", False)
        )
        enriched.append(
            {
                **paper,
                "topic_relevance": max(0, min(3, topic_relevance)),
                "topic_match": topic_match,
                "topic_rationale": str(score_row.get("rationale", "")).strip(),
                "institution_match": institution_match,
                "matched_institutions": paper.get("manual_institution_extraction", {}).get(
                    "filter_match_institutions", []
                ),
            }
        )

    selected = [p for p in enriched if p["institution_match"] or p["topic_match"]]
    selected.sort(key=lambda p: (p["topic_relevance"], p["institution_match"]), reverse=True)

    stage2_payload = {
        "submission_date": submission_date.isoformat(),
        "filters": filters,
        "max_topic_matches": max_topic_matches,
        "selected_paper_count": len(selected),
        "selected_papers": [
            {
                "paper_id": paper["arxiv_id"],
                "title": paper["title"],
                "subjects": paper["subjects"],
                "abstract": paper["abstract"],
                "abs_url": paper["abs_url"],
                "institution_match": paper["institution_match"],
                "matched_institutions": paper["matched_institutions"],
                "topic_relevance": paper["topic_relevance"],
                "topic_rationale": paper["topic_rationale"],
                "institution": _paper_institution_label(paper),
            }
            for paper in selected
        ],
    }

    stage2_text = _responses_create(
        client=client,
        model=model,
        system_prompt=SUMMARY_PROMPT,
        payload=stage2_payload,
        effort="medium",
    )
    summary_json = _parse_json_response(stage2_text)
    topic_rows = _clean_match_rows(summary_json.get("topic_matches", []))[:max_topic_matches]
    institution_rows = _clean_match_rows(summary_json.get("institution_matches", []))

    institutions_by_id = {paper["arxiv_id"]: _paper_institution_label(paper) for paper in selected}
    for row in topic_rows:
        if row.get("institution", "").strip():
            continue
        paper_id = row.get("paper_id", "").strip()
        row["institution"] = institutions_by_id.get(paper_id, "")
    summary_rows = summary_json.get("executive_summary", [])
    if not isinstance(summary_rows, list):
        summary_rows = []
    return {
        "submission_date": submission_date.isoformat(),
        "filters": {
            "institutions": institutions,
            "topics": topics,
        },
        "paper_count": len(papers),
        "selected_paper_count": len(selected),
        "papers": enriched,
        "briefing": {
            "executive_summary": [str(line) for line in summary_rows],
            "institution_matches": institution_rows,
            "topic_matches": topic_rows,
        },
    }
