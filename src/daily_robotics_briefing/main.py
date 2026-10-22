from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .briefing_agent import DEFAULT_MODEL, create_daily_briefing
from .collector import fetch_csro_recent
from .common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from .institution_filter import build_institution_specs
from .renderer import build_dashboard, render_html, render_markdown
from .time_utils import eastern_today


def load_filters(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _canonical_names(institution_entries: list[Any]) -> list[str]:
    specs = build_institution_specs(institution_entries)
    return [spec.canonical for spec in specs]


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily robotics briefing.")
    parser.add_argument("--filters", type=Path, default=Path("config/filters.yaml"))
    default_report_dir = Path("reports") / eastern_today().isoformat()
    parser.add_argument("--out", type=Path, default=default_report_dir / f"{eastern_today().isoformat()}.md")
    parser.add_argument(
        "--out-json",
        type=Path,
        default=default_report_dir / f"{eastern_today().isoformat()}.json",
    )
    parser.add_argument(
        "--out-html",
        type=Path,
        default=default_report_dir / f"{eastern_today().isoformat()}.html",
    )
    parser.add_argument(
        "--dashboard-out",
        type=Path,
        default=Path("reports/index.html"),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--affiliation-cache-dir", type=Path, default=Path(".cache/affiliations"))
    parser.add_argument(
        "--submission-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Submission date to summarize (YYYY-MM-DD). Defaults to yesterday.",
    )
    args = parser.parse_args()

    submission_date = args.submission_date or (eastern_today() - timedelta(days=1))

    cfg = load_filters(args.filters)
    institution_entries = cfg.get("institutions", [])
    canonical_from_config = _canonical_names(institution_entries)
    combined_entries: list[object] = [*institution_entries, *COMMON_ROBOTICS_INSTITUTIONS]
    institutions = canonical_from_config
    topics = _normalize_string_list(cfg.get("topics", []))
    max_papers = int(cfg.get("max_papers", 400))
    # The old total LLM cap is now a batch-size fallback, never a coverage limit.
    classification_batch_size = (
        int(cfg["classification_batch_size"]) if "classification_batch_size" in cfg
        else min(int(cfg.get("max_papers_for_llm", 25)), 25)
    )
    summary_batch_size = int(cfg.get("summary_batch_size", 10))
    max_topic_matches = int(cfg.get("max_topic_matches", 10))
    if min(max_papers, classification_batch_size, summary_batch_size) < 1 or max_topic_matches < 0:
        raise ValueError("Collection and batch limits must be positive; max_topic_matches must be nonnegative")

    affiliation_batch_size = int(cfg.get('affiliation_batch_size', 12))
    affiliation_max_input_chars = int(cfg.get('affiliation_max_input_chars', 120000))
    affiliation_snippet_chars = int(cfg.get('affiliation_snippet_chars', 4000))
    pdf_limit = int(cfg.get('max_pdf_megabytes', 32)) * 1024 * 1024
    if min(affiliation_batch_size, affiliation_snippet_chars, pdf_limit) < 1 or affiliation_max_input_chars < 0:
        raise ValueError('Affiliation batch/snippet/PDF limits must be positive; input budget must be nonnegative')
    papers = fetch_csro_recent(max_papers=max_papers, submission_date=submission_date, max_pdf_bytes=pdf_limit)

    if not papers:
        print(
            "No papers found for submission date "
            f"{submission_date.isoformat()}; skipping briefing generation."
        )
        return

    all_papers = [paper.to_dict() for paper in papers]

    result = create_daily_briefing(
        papers=all_papers,
        institutions=institutions,
        topics=topics,
        submission_date=submission_date,
        model=args.model,
        max_topic_matches=max_topic_matches,
        classification_batch_size=classification_batch_size,
        summary_batch_size=summary_batch_size,
        institution_entries=combined_entries,
        affiliation_cache_dir=args.affiliation_cache_dir,
        affiliation_batch_size=affiliation_batch_size,
        affiliation_max_input_chars=affiliation_max_input_chars,
        affiliation_snippet_chars=affiliation_snippet_chars,
    )
    result["filters"] = {
        "institutions": institutions,
        "topics": topics,
    }
    result["papers_fetched"] = len(all_papers)
    result["papers_analyzed"] = len(all_papers)
    result['affiliation_coverage'] = {
        'matched': sum(p['institution_match_status'] == 'matched' for p in result['papers']),
        'no_match': sum(p['institution_match_status'] == 'no_match' for p in result['papers']),
        'unknown': sum(p['institution_match_status'] in {'unresolved', 'source_unavailable'} for p in result['papers']),
    }
    result['affiliation_status_counts'] = {
        status: sum(p['institution_match_status'] == status for p in result['papers'])
        for status in ('matched', 'no_match', 'unresolved', 'source_unavailable')
    }
    print('Affiliation coverage:', result['affiliation_status_counts'])
    print('API usage:', {k: v for k, v in result['api_usage'].items() if k != 'responses'})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_html.parent.mkdir(parents=True, exist_ok=True)
    args.dashboard_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_output = render_markdown(
        briefing=result["briefing"],
        matched_institutions=[str(x) for x in result.get("filters", {}).get("institutions", [])],
        matched_topics=[str(x) for x in result.get("filters", {}).get("topics", [])],
        submission_date=submission_date,
        papers_fetched=int(result.get("papers_fetched", 0)),
        papers_analyzed=int(result.get("papers_analyzed", 0)),
        affiliation_coverage=result["affiliation_coverage"],
    )
    html_output = render_html(
        briefing=result["briefing"],
        matched_institutions=[str(x) for x in result.get("filters", {}).get("institutions", [])],
        matched_topics=[str(x) for x in result.get("filters", {}).get("topics", [])],
        submission_date=submission_date,
        papers_fetched=int(result.get("papers_fetched", 0)),
        papers_analyzed=int(result.get("papers_analyzed", 0)),
        affiliation_coverage=result["affiliation_coverage"],
    )

    args.out.write_text(markdown_output, encoding="utf-8")
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_html.write_text(html_output, encoding="utf-8")
    build_dashboard(args.dashboard_out.parent, args.dashboard_out)
    print(f"Wrote markdown briefing: {args.out}")
    print(f"Wrote structured briefing: {args.out_json}")
    print(f"Wrote HTML briefing: {args.out_html}")
    print(f"Wrote dashboard index: {args.dashboard_out}")

if __name__ == "__main__":
    main()
