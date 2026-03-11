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


def _load_actions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"papers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"papers": {}}
    if not isinstance(payload, dict):
        return {"papers": {}}
    papers = payload.get("papers", {})
    if not isinstance(papers, dict):
        papers = {}
    return {"papers": papers}


def _write_weekly_digest(reports_root: Path, actions_file: Path, submission_date: date) -> Path:
    week_start = submission_date - timedelta(days=submission_date.weekday())
    week_end = week_start + timedelta(days=6)
    weekly_json_paths = [
        reports_root / (week_start + timedelta(days=offset)).isoformat() / f"{(week_start + timedelta(days=offset)).isoformat()}.json"
        for offset in range(7)
    ]
    papers: list[dict[str, Any]] = []
    for path in weekly_json_paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for paper in payload.get("papers", []):
            if not isinstance(paper, dict):
                continue
            card = paper.get("decision_card", {})
            if not isinstance(card, dict):
                continue
            papers.append(
                {
                    "paper_id": str(paper.get("arxiv_id", "")),
                    "title": str(paper.get("title", "")),
                    "score": int(card.get("read_priority_score", 0) or 0),
                    "link": str(paper.get("abs_url", "")),
                }
            )
    actions = _load_actions(actions_file)
    read_by_id = {
        str(pid): bool(state.get("read", False))
        for pid, state in actions.get("papers", {}).items()
        if isinstance(state, dict)
    }
    papers = [paper for paper in papers if paper.get("paper_id")]
    papers.sort(key=lambda p: p["score"], reverse=True)
    notable = papers[:20]
    unread = [paper for paper in notable if not read_by_id.get(str(paper["paper_id"]), False)]

    weekly_dir = reports_root / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_slug = f"{week_start.isoformat()}_to_{week_end.isoformat()}"
    weekly_path = weekly_dir / f"{weekly_slug}.html"
    body = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Weekly Robotics Digest {week_start.isoformat()} to {week_end.isoformat()}</title>",
        "<style>body{font-family:Inter,Segoe UI,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;} li{margin:.35rem 0;} a{color:#2b5c99;}</style>",
        "</head><body>",
        f"<h1>Weekly Robotics Digest ({week_start.isoformat()} → {week_end.isoformat()})</h1>",
        "<h2>Top notable papers</h2><ol>",
    ]
    for paper in notable:
        body.append(
            f"<li><a href='{paper['link']}'>{paper['title']}</a> <em>(score {paper['score']})</em></li>"
        )
    body.append("</ol><h2>Unread notable papers</h2><ul>")
    for paper in unread:
        body.append(
            f"<li><a href='{paper['link']}'>{paper['title']}</a> <em>(score {paper['score']})</em></li>"
        )
    body.append("</ul></body></html>")
    weekly_path.write_text("".join(body), encoding="utf-8")
    return weekly_path


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
    parser.add_argument("--actions-file", type=Path, default=Path("reports/state/user_actions.json"))
    parser.add_argument("--mark-read", nargs="*", default=[])
    parser.add_argument("--mark-unread", nargs="*", default=[])
    parser.add_argument(
        "--submission-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Submission date to summarize (YYYY-MM-DD). Defaults to yesterday.",
    )
    args = parser.parse_args()

    if args.mark_read or args.mark_unread:
        args.actions_file.parent.mkdir(parents=True, exist_ok=True)
        if args.actions_file.exists():
            actions = json.loads(args.actions_file.read_text(encoding="utf-8"))
        else:
            actions = {"papers": {}}
        papers_state = actions.setdefault("papers", {})
        for paper_id in args.mark_read:
            papers_state[str(paper_id)] = {"read": True}
        for paper_id in args.mark_unread:
            papers_state[str(paper_id)] = {"read": False}
        args.actions_file.write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Updated actions file: {args.actions_file}")
        return

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
            source_text=record.get("html_author_notes_text", ""),
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
    result["papers_fetched"] = len(all_papers)
    result["papers_analyzed"] = len(papers_for_llm)

    decision_cards = {
        str(p.get("arxiv_id", "")): p.get("decision_card", {})
        for p in result.get("papers", [])
        if isinstance(p, dict)
    }
    for section_name in ("institution_matches", "topic_matches"):
        rows = result.get("briefing", {}).get(section_name, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            paper_id = str(row.get("paper_id", "")).strip()
            if paper_id and paper_id in decision_cards:
                row["decision_card"] = decision_cards[paper_id]

    week_start = submission_date - timedelta(days=submission_date.weekday())
    week_end = week_start + timedelta(days=6)
    result["week_start"] = week_start.isoformat()
    result["week_end"] = week_end.isoformat()

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
    )
    html_output = render_html(
        briefing=result["briefing"],
        matched_institutions=[str(x) for x in result.get("filters", {}).get("institutions", [])],
        matched_topics=[str(x) for x in result.get("filters", {}).get("topics", [])],
        submission_date=submission_date,
        papers_fetched=int(result.get("papers_fetched", 0)),
        papers_analyzed=int(result.get("papers_analyzed", 0)),
    )

    args.out.write_text(markdown_output, encoding="utf-8")
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_html.write_text(html_output, encoding="utf-8")
    weekly_path = _write_weekly_digest(args.dashboard_out.parent, args.actions_file, submission_date)
    build_dashboard(args.dashboard_out.parent, args.dashboard_out)
    print(f"Wrote markdown briefing: {args.out}")
    print(f"Wrote structured briefing: {args.out_json}")
    print(f"Wrote HTML briefing: {args.out_html}")
    print(f"Wrote dashboard index: {args.dashboard_out}")
    print(f"Wrote weekly digest: {weekly_path}")

if __name__ == "__main__":
    main()
