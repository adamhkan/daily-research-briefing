from __future__ import annotations

import argparse
from datetime import date
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
    parser.add_argument("--model", default="gpt-4.1")
    args = parser.parse_args()

    cfg = load_filters(args.filters)
    institutions = cfg.get("institutions", [])
    topics = cfg.get("topics", [])
    max_papers = int(cfg.get("max_papers", 400))
    max_papers_for_llm = int(cfg.get("max_papers_for_llm", 120))

    papers = fetch_csro_recent(max_papers=max_papers)
    papers_for_llm = [p.to_dict() for p in papers[:max_papers_for_llm]]

    briefing = create_daily_briefing(
        papers=papers_for_llm,
        institutions=institutions,
        topics=topics,
        model=args.model,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(briefing + "\n", encoding="utf-8")
    print(f"Wrote briefing: {args.out}")


if __name__ == "__main__":
    main()
