from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import json


def _table_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "| _No matches_ |  |  |  |"
    lines = []
    for row in rows:
        lines.append(
            "| {title} | {institution} | {overview} | {link} |".format(
                title=row.get("title", "").replace("|", "\\|"),
                institution=row.get("institution", "").replace("|", "\\|"),
                overview=row.get("overview", "").replace("|", "\\|"),
                link=row.get("link", "").replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_markdown(
    briefing: dict,
    submission_date: date,
    papers_fetched: int,
    papers_analyzed: int,
) -> str:
    summary = briefing.get("executive_summary", [])
    institution_rows = briefing.get("institution_matches", [])
    topic_rows = briefing.get("topic_matches", [])

    summary_block = "\n".join(f"- {line}" for line in summary) or "- No papers matched the filters today."

    return (
        "# Daily Robotics Briefing\n\n"
        f"Submission date covered: **{submission_date.isoformat()}**\n"
        f"Papers fetched: **{papers_fetched}**\n"
        f"Papers analyzed: **{papers_analyzed}**\n\n"
        "## Executive Summary\n\n"
        f"{summary_block}\n\n"
        "## Institution Matches\n\n"
        "| Title | Institution | Overview | Link |\n"
        "| --- | --- | --- | --- |\n"
        f"{_table_rows(institution_rows)}\n\n"
        "## Topic Matches\n\n"
        "| Title | Institution | Overview | Link |\n"
        "| --- | --- | --- | --- |\n"
        f"{_table_rows(topic_rows)}\n"
    )


def _render_html_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<tr><td colspan="4"><em>No matches</em></td></tr>'

    rendered = []
    for row in rows:
        rendered.append(
            "<tr>"
            f"<td>{escape(str(row.get('title', '')))}</td>"
            f"<td>{escape(str(row.get('institution', '')))}</td>"
            f"<td>{escape(str(row.get('overview', '')))}</td>"
            f"<td><a href=\"{escape(str(row.get('link', '')))}\">Link</a></td>"
            "</tr>"
        )
    return "\n".join(rendered)


def render_html(
    briefing: dict,
    submission_date: date,
    papers_fetched: int,
    papers_analyzed: int,
) -> str:
    summary = briefing.get("executive_summary", [])
    summary_html = "".join(f"<li>{escape(str(line))}</li>" for line in summary) or "<li>No papers matched.</li>"
    institution_html = _render_html_rows(briefing.get("institution_matches", []))
    topic_html = _render_html_rows(briefing.get("topic_matches", []))

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Daily Robotics Briefing - {submission_date.isoformat()}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #1f2937; }}
    .stats {{ display: flex; gap: 1rem; margin-bottom: 1rem; }}
    .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem 1rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }}
    th, td {{ border: 1px solid #e2e8f0; text-align: left; padding: 0.5rem; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>Daily Robotics Briefing</h1>
  <p><strong>Submission date covered:</strong> {submission_date.isoformat()}</p>
  <div class=\"stats\">
    <div class=\"card\">Papers fetched: <strong>{papers_fetched}</strong></div>
    <div class=\"card\">Papers analyzed: <strong>{papers_analyzed}</strong></div>
  </div>

  <h2>Executive Summary</h2>
  <ul>{summary_html}</ul>

  <h2>Institution Matches</h2>
  <table>
    <thead><tr><th>Title</th><th>Institution</th><th>Overview</th><th>Link</th></tr></thead>
    <tbody>{institution_html}</tbody>
  </table>

  <h2>Topic Matches</h2>
  <table>
    <thead><tr><th>Title</th><th>Institution</th><th>Overview</th><th>Link</th></tr></thead>
    <tbody>{topic_html}</tbody>
  </table>
</body>
</html>
"""


def build_dashboard(reports_dir: Path, dashboard_out: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[str, str]] = []
    for json_path in sorted(reports_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        submission_date = payload.get("submission_date", json_path.stem)
        html_name = f"{json_path.stem}.html"
        entries.append((submission_date, html_name))

    rows = "\n".join(
        f"<tr><td>{escape(date_label)}</td><td><a href=\"{escape(path)}\">Open briefing</a></td></tr>"
        for date_label, path in entries
    )
    if not rows:
        rows = '<tr><td colspan="2"><em>No briefings available.</em></td></tr>'

    dashboard_html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Daily Robotics Briefing Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #1f2937; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #e2e8f0; text-align: left; padding: 0.5rem; }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>Daily Robotics Briefing Dashboard</h1>
  <p>Select a date to view the digest.</p>
  <table>
    <thead><tr><th>Submission date</th><th>Digest</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    dashboard_out.write_text(dashboard_html, encoding="utf-8")
