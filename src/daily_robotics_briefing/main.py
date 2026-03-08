from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .briefing_agent import create_daily_briefing
from .collector import fetch_csro_recent
from .institution_filter import build_institution_specs, extract_institutions_for_paper
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
    parser.add_argument("--out", type=Path, default=Path(f"reports/{eastern_today().isoformat()}.md"))
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
    institution_specs = build_institution_specs(institution_entries)
    institutions = _canonical_names(institution_entries)
    topics = cfg.get("topics", [])
    max_papers = int(cfg.get("max_papers", 400))
    max_papers_for_llm = int(cfg.get("max_papers_for_llm", 120))

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
        record["manual_institution_extraction"] = institution_result.to_dict()
        all_papers.append(record)
    papers_for_llm = all_papers[:max_papers_for_llm]

    briefing = create_daily_briefing(
        papers=papers_for_llm,
        institutions=institutions,
        topics=topics,
        submission_date=submission_date,
        model=args.model,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = (
        f"# Daily Robotics Briefing\n\n"
        f"Submission date covered: **{submission_date.isoformat()}**\n"
        f"Papers fetched: **{len(all_papers)}**\n"
        f"Papers analyzed: **{len(papers_for_llm)}**\n\n"
        f"{briefing.strip()}\n"
    )
    args.out.write_text(output, encoding="utf-8")
    print(f"Wrote briefing: {args.out}")

if __name__ == "__main__":
    main()
