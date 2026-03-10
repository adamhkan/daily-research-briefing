from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import json


def _institution_table_rows(rows: list[dict[str, str]]) -> str:
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


def _topic_table_rows(rows: list[dict[str, str]]) -> str:
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
    matched_institutions: list[str],
    matched_topics: list[str],
    submission_date: date,
    papers_fetched: int,
    papers_analyzed: int,
) -> str:
    summary = briefing.get("executive_summary", [])
    institution_rows = briefing.get("institution_matches", [])
    topic_rows = briefing.get("topic_matches", [])

    summary_block = "\n".join(f"- {line}" for line in summary) or "- No papers matched the filters today."
    institution_filters = "; ".join(matched_institutions) if matched_institutions else "(none)"
    topic_filters = "; ".join(matched_topics) if matched_topics else "(none)"

    return (
        "# Daily Robotics Briefing\n\n"
        f"Submission date covered: **{submission_date.isoformat()}**\n"
        f"Papers fetched: **{papers_fetched}**\n"
        f"Papers analyzed: **{papers_analyzed}**\n\n"
        "## Filters Used\n\n"
        f"- Institution filters: {institution_filters}\n"
        f"- Topic filters: {topic_filters}\n\n"
        "## Executive Summary\n\n"
        f"{summary_block}\n\n"
        "## Institution Matches\n\n"
        "| Title | Institution | Overview | Link |\n"
        "| --- | --- | --- | --- |\n"
        f"{_institution_table_rows(institution_rows)}\n\n"
        "## Topic Matches\n\n"
        "| Title | Institution | Overview | Link |\n"
        "| --- | --- | --- | --- |\n"
        f"{_topic_table_rows(topic_rows)}\n"
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


def _render_topic_html_rows(rows: list[dict[str, str]]) -> str:
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
    matched_institutions: list[str],
    matched_topics: list[str],
    submission_date: date,
    papers_fetched: int,
    papers_analyzed: int,
) -> str:
    summary = briefing.get("executive_summary", [])
    summary_html = "".join(f"<li>{escape(str(line))}</li>" for line in summary) or "<li>No papers matched.</li>"
    institution_filters = matched_institutions or ["(none)"]
    topic_filters = matched_topics or ["(none)"]
    institution_filter_html = "".join(f"<li>{escape(item)}</li>" for item in institution_filters)
    topic_filter_html = "".join(f"<li>{escape(item)}</li>" for item in topic_filters)
    institution_html = _render_html_rows(briefing.get("institution_matches", []))
    topic_html = _render_topic_html_rows(briefing.get("topic_matches", []))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Robotics Briefing - {submission_date.isoformat()}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f6f3;
      --panel: #fffefd;
      --panel-muted: #f5f2ec;
      --ink: #253044;
      --ink-soft: #5b6578;
      --line: #ddd5ca;
      --accent-soft: #dfe6f0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.6;
      color: var(--ink);
      background: linear-gradient(180deg, #fbfaf8 0%, var(--bg) 45%, #f2f0eb 100%);
    }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 2.25rem 1.25rem 3rem; }}
    .hero {{ margin-bottom: 1.5rem; padding: 1.5rem; background: var(--panel); border: 1px solid var(--line); border-radius: 14px; }}
    h1, h2, h3 {{ font-family: 'Merriweather', Georgia, 'Times New Roman', serif; line-height: 1.3; color: #1f2a3d; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 2.3vw, 2.1rem); }}
    h2 {{ margin: 0; font-size: 1.35rem; }}
    h3 {{ margin: 1rem 0 0.5rem; font-size: 1.05rem; color: #344158; }}
    p {{ margin: 0.45rem 0; color: var(--ink-soft); }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.85rem; margin: 1rem 0 0.3rem; }}
    .card {{ background: var(--panel-muted); border: 1px solid var(--line); border-radius: 10px; padding: 0.7rem 0.9rem; }}
    .card strong {{ color: #2b3850; }}
    .section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 1.15rem 1.2rem; margin-top: 1rem; }}
    ul {{ margin: 0.55rem 0 0; padding-left: 1.2rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 0.65rem; font-size: 0.95rem; }}
    th, td {{ border: 1px solid var(--line); text-align: left; padding: 0.58rem 0.62rem; vertical-align: top; }}
    th {{ background: var(--accent-soft); color: #22304a; font-weight: 600; }}
    tbody tr:nth-child(even) {{ background: #fcfbf8; }}
    a {{ color: #3d5f89; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Daily Robotics Briefing</h1>
      <p><strong>Submission date covered:</strong> {submission_date.isoformat()}</p>
      <div class="stats">
        <div class="card">Papers fetched: <strong>{papers_fetched}</strong></div>
        <div class="card">Papers analyzed: <strong>{papers_analyzed}</strong></div>
      </div>
    </section>

    <section class="section">
      <h2>Executive Summary</h2>
      <ul>{summary_html}</ul>
    </section>

    <section class="section">
      <h2>Filters Used</h2>
      <h3>Institution filters</h3>
      <ul>{institution_filter_html}</ul>
      <h3>Topic filters</h3>
      <ul>{topic_filter_html}</ul>
    </section>

    <section class="section">
      <h2>Institution Matches</h2>
      <table>
        <thead><tr><th>Title</th><th>Institution</th><th>Overview</th><th>Link</th></tr></thead>
        <tbody>{institution_html}</tbody>
      </table>
    </section>

    <section class="section">
      <h2>Topic Matches</h2>
      <table>
        <thead><tr><th>Title</th><th>Institution</th><th>Overview</th><th>Link</th></tr></thead>
        <tbody>{topic_html}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def build_dashboard(reports_dir: Path, dashboard_out: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[str, str]] = []
    search_index: list[dict[str, str | int | bool]] = []
    for json_path in sorted(reports_dir.glob("**/*.json"), reverse=True):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        submission_date = payload.get("submission_date", json_path.stem)
        html_relative_path = json_path.with_suffix(".html").relative_to(dashboard_out.parent)
        html_name = html_relative_path.as_posix()
        entries.append((submission_date, html_name))

        overview_by_paper_id: dict[str, str] = {}
        briefing = payload.get("briefing", {})
        if isinstance(briefing, dict):
            for section_name in ("institution_matches", "topic_matches"):
                section_rows = briefing.get(section_name, [])
                if not isinstance(section_rows, list):
                    continue
                for row in section_rows:
                    if not isinstance(row, dict):
                        continue
                    paper_id = str(row.get("paper_id", "")).strip()
                    overview = str(row.get("overview", "")).strip()
                    if paper_id and overview and paper_id not in overview_by_paper_id:
                        overview_by_paper_id[paper_id] = overview

        papers = payload.get("papers", [])
        if not isinstance(papers, list):
            continue
        for paper in papers:
            if not isinstance(paper, dict):
                continue
            institution_match = bool(paper.get("institution_match", False))
            topic_match = bool(paper.get("topic_match", False))
            if not (institution_match or topic_match):
                continue

            paper_id = str(paper.get("arxiv_id", "")).strip()
            title = str(paper.get("title", "")).strip()
            abstract = str(paper.get("abstract", "")).strip()
            overview = overview_by_paper_id.get(paper_id, "")
            link = str(paper.get("abs_url", "")).strip()
            topic_relevance = int(paper.get("topic_relevance", 0) or 0)

            if not (paper_id and title and (abstract or overview)):
                continue

            institution_tags = paper.get("matched_institutions", [])
            if isinstance(institution_tags, list):
                normalized_institution_tags = [str(tag).strip() for tag in institution_tags if str(tag).strip()]
            else:
                normalized_institution_tags = []

            search_index.append(
                {
                    "paper_id": paper_id,
                    "submission_date": str(submission_date),
                    "title": title,
                    "abstract": abstract,
                    "overview": overview,
                    "institution_tags": normalized_institution_tags,
                    "institution_match": institution_match,
                    "topic_match": topic_match,
                    "topic_relevance": topic_relevance,
                    "abs_url": link,
                    "briefing_path": html_name,
                }
            )

    rows = "\n".join(
        f"<tr><td>{escape(date_label)}</td><td><a href=\"{escape(path)}\">Open briefing</a></td></tr>"
        for date_label, path in entries
    )
    if not rows:
        rows = '<tr><td colspan="2"><em>No briefings available.</em></td></tr>'

    search_index_json = json.dumps(search_index, ensure_ascii=False).replace("</", "<\\/")

    dashboard_html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Robotics Briefing Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f4f0;
      --panel: #fffdf9;
      --panel-2: #f4efe7;
      --ink: #263248;
      --ink-soft: #5d677a;
      --line: #ddd4c6;
      --accent-soft: #dbe4f0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.6;
      color: var(--ink);
      background: linear-gradient(180deg, #fbfaf7 0%, var(--bg) 45%, #f1ede5 100%);
    }
    main { max-width: 1140px; margin: 0 auto; padding: 2.4rem 1.2rem 3rem; }
    h1, h2 { font-family: 'Merriweather', Georgia, serif; line-height: 1.3; color: #202c41; }
    h1 { margin-bottom: 0.25rem; font-size: clamp(1.6rem, 2.4vw, 2.2rem); }
    p { margin-top: 0.25rem; color: var(--ink-soft); }
    .search-card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.15rem; margin: 1.2rem 0; }
    #paper-search { width: 100%; max-width: 840px; border: 1px solid #c8c0b3; border-radius: 9px; padding: 0.72rem; font-size: 1rem; background: #fffefc; color: var(--ink); }
    .search-help { margin: 0.45rem 0 0; color: var(--ink-soft); font-size: 0.95rem; }
    #search-results { margin: 1rem 0 1.5rem; display: grid; gap: 0.75rem; }
    .result-item { border: 1px solid var(--line); border-radius: 11px; padding: 0.78rem 0.9rem; background: var(--panel-2); }
    .result-item p { margin-bottom: 0.2rem; }
    .result-meta { color: var(--ink-soft); font-size: 0.9rem; margin-top: 0.3rem; }
    .muted { color: #707a8d; }
    a { color: #3d5f89; }
    table { width: 100%; border-collapse: collapse; border: 1px solid var(--line); background: var(--panel); border-radius: 12px; overflow: hidden; }
    th, td { border: 1px solid var(--line); text-align: left; padding: 0.56rem; }
    th { background: var(--accent-soft); color: #22304a; font-weight: 600; }
    tbody tr:nth-child(even) { background: #fcfbf8; }
  </style>
</head>
<body>
  <main>
  <h1>Daily Robotics Briefing Dashboard</h1>
  <p>Select a date to view the digest.</p>

  <section class="search-card">
    <h2>Search papers</h2>
    <p class="search-help">Searches ArXiv robotics papers. Matches prioritize <strong>title and abstract</strong>, while still matching <strong>institution tags</strong> and overview text.</p>
    <input id="paper-search" type="search" placeholder="Try: motion planning, Carnegie Mellon..." autocomplete="off" />
    <p id="search-status" class="search-help muted">Type at least 2 characters to search.</p>
    <div id="search-results"></div>
  </section>

  <table>
    <thead><tr><th>Submission date</th><th>Digest</th></tr></thead>
    <tbody>__ROWS__</tbody>
  </table>

  <script id="search-index" type="application/json">__SEARCH_INDEX_JSON__</script>
  <script>
    const indexEl = document.getElementById('search-index');
    const allPapers = JSON.parse(indexEl.textContent || '[]');
    const inputEl = document.getElementById('paper-search');
    const resultsEl = document.getElementById('search-results');
    const statusEl = document.getElementById('search-status');

    const normalize = (value) => value.toLowerCase().replace(/\s+/g, ' ').trim();
    const escapeHtml = (value) => value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

    const matchPaper = (paper, terms) => {
      const title = normalize(paper.title || '');
      const abstract = normalize(paper.abstract || '');
      const overview = normalize(paper.overview || '');
      const institutionTags = (paper.institution_tags || []).map((tag) => normalize(tag)).join(' ');
      return terms.every((term) => title.includes(term) || abstract.includes(term) || overview.includes(term) || institutionTags.includes(term));
    };

    const scorePaper = (paper, terms) => {
      const title = normalize(paper.title || '');
      const abstract = normalize(paper.abstract || '');
      const overview = normalize(paper.overview || '');
      const institutionTags = (paper.institution_tags || []).map((tag) => normalize(tag)).join(' ');
      let score = 0;
      for (const term of terms) {
        if (title.includes(term)) score += 5;
        if (abstract.includes(term)) score += 4;
        if (institutionTags.includes(term)) score += 3;
        if (overview.includes(term)) score += 2;
      }
      score += Number(paper.topic_relevance || 0);
      return score;
    };

    const renderResults = (papers, terms) => {
      if (!papers.length) {
        resultsEl.innerHTML = '<p class="muted">No matching papers found.</p>';
        return;
      }

      const topResults = papers.slice(0, 50);
      resultsEl.innerHTML = topResults.map((paper) => {
        const snippetSource = paper.abstract || paper.overview || '';
        const snippet = snippetSource.length > 420 ? `${snippetSource.slice(0, 420)}...` : snippetSource;
        const tags = [
          paper.institution_match ? 'institution match' : '',
          paper.topic_match ? 'topic match' : '',
        ].filter(Boolean).join(' · ');
        return `
          <article class="result-item">
            <div><a href="${escapeHtml(paper.abs_url || '#')}" target="_blank" rel="noopener noreferrer">${escapeHtml(paper.title || '(untitled)')}</a></div>
            <div class="result-meta">${escapeHtml(paper.submission_date || '')} · ${escapeHtml(tags)}</div>
            <p>${escapeHtml(snippet)}</p>
            <div class="result-meta"><a href="${escapeHtml(paper.briefing_path || '#')}">Open daily briefing</a></div>
          </article>
        `;
      }).join('');
    };

    const runSearch = () => {
      const query = normalize(inputEl.value || '');
      if (query.length < 2) {
        statusEl.textContent = 'Type at least 2 characters to search.';
        resultsEl.innerHTML = '';
        return;
      }

      const terms = query.split(' ').filter(Boolean);
      const matches = allPapers
        .filter((paper) => matchPaper(paper, terms))
        .map((paper) => ({ ...paper, _score: scorePaper(paper, terms) }))
        .sort((a, b) => (b._score - a._score) || String(b.submission_date).localeCompare(String(a.submission_date)));

      statusEl.textContent = `Found ${matches.length} matching paper${matches.length === 1 ? '' : 's'}.`;
      renderResults(matches, terms);
    };

    inputEl.addEventListener('input', runSearch);
  </script>
  </main>
</body>
</html>
"""
    dashboard_html = dashboard_html.replace("__ROWS__", rows).replace("__SEARCH_INDEX_JSON__", search_index_json)
    dashboard_out.write_text(dashboard_html, encoding="utf-8")
