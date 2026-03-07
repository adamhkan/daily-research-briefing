from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import yaml

from .briefing_agent import create_daily_briefing
from .collector import fetch_csro_recent


def load_filters(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily robotics briefing.")
    parser.add_argument("--filters", type=Path, default=Path("config/filters.yaml"))
    parser.add_argument("--out", type=Path, default=Path(f"reports/{date.today().isoformat()}.md"))
    parser.add_argument("--model", default="gpt-5.1")
    parser.add_argument(
        "--submission-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Submission date to summarize (YYYY-MM-DD). Defaults to yesterday.",
    )
    args = parser.parse_args()

    submission_date = args.submission_date or (date.today() - timedelta(days=1))

    cfg = load_filters(args.filters)
    institutions = cfg.get("institutions", [])
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

    all_papers = [paper.to_dict() for paper in papers]
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
