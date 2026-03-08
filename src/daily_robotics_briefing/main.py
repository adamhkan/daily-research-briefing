from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .briefing_agent import create_daily_briefing
from .collector import fetch_csro_recent
from .common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from .institution_filter import build_institution_specs, extract_institutions_for_paper
from .renderer import build_dashboard, render_html, render_markdown
from .time_utils import eastern_today


def load_filters(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _canonical_names(institution_entries: list[Any]) -> list[str]:
    specs = build_institution_specs(institution_entries)
    return [spec.canonical for spec in specs]


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
    parser.add_argument("--model", default="gpt-5.1")
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
    institution_specs = build_institution_specs(combined_entries)
    institutions = canonical_from_config
    configured_institution_set = set(canonical_from_config)
    topics = cfg.get("topics", [])
    max_papers = int(cfg.get("max_papers", 400))
    max_papers_for_llm = int(cfg.get("max_papers_for_llm", 120))
    max_topic_matches = int(cfg.get("max_topic_matches", 10))

    papers = fetch_csro_recent(max_papers=max_papers, submission_date=submission_date)

    if not papers:
        print(
            "No papers found for submission date "
            f"{submission_date.isoformat()}; skipping briefing generation."
        )
        return

    all_papers = []
    for paper in papers:
        record = paper.to_dict()
        institution_result = extract_institutions_for_paper(
            author_names=record["authors"],
            pdf_first_page_text=record["pdf_first_page_text"],
            institution_specs=institution_specs,
        )
        extraction_dict = institution_result.to_dict()
        paper_level = extraction_dict.get("paper_level_institutions", [])
        if isinstance(paper_level, list):
            filtered_matches = sorted(
                {str(name) for name in paper_level if str(name) in configured_institution_set}
            )
        else:
            filtered_matches = []
        extraction_dict["filter_match"] = bool(filtered_matches)
        extraction_dict["filter_match_institutions"] = filtered_matches
        record["manual_institution_extraction"] = extraction_dict
        record["abstract_for_prompt"] = " ".join(record["abstract"].split())[:500]
        all_papers.append(record)
    papers_for_llm = all_papers[:max_papers_for_llm]

    result = create_daily_briefing(
        papers=papers_for_llm,
        institutions=institutions,
        topics=topics,
        submission_date=submission_date,
        model=args.model,
        max_topic_matches=max_topic_matches,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_html.parent.mkdir(parents=True, exist_ok=True)
    args.dashboard_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_output = render_markdown(
        briefing=result["briefing"],
        matched_institutions=[str(x) for x in result.get("filters", {}).get("institutions", [])],
        matched_topics=[str(x) for x in result.get("filters", {}).get("topics", [])],
        submission_date=submission_date,
        papers_fetched=len(all_papers),
        papers_analyzed=len(papers_for_llm),
    )
    html_output = render_html(
        briefing=result["briefing"],
        matched_institutions=[str(x) for x in result.get("filters", {}).get("institutions", [])],
        matched_topics=[str(x) for x in result.get("filters", {}).get("topics", [])],
        submission_date=submission_date,
        papers_fetched=len(all_papers),
        papers_analyzed=len(papers_for_llm),
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
