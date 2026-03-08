# Daily Robotics Research Briefing Agent

This repository contains an AI agent that runs on GitHub Actions and produces a daily summary of recent robotics research from arXiv (`cs.RO`).

## What this agent does

1. Fetches papers from https://arxiv.org/list/cs.RO/recent?skip=0&show=2000.
2. Selects only papers submitted on the day before the run date in US Eastern time (EST/EDT, "yesterday" by default).
3. Collects title, authors, abstract, subjects, links, and first-page PDF text (locally scraped).
4. Applies deterministic institution extraction on first-page PDF text to map author affiliations from your institution allow-list (including aliases).
5. Calls the OpenAI API (default model: `gpt-5.1`) in two stages: first to classify topic relevance with structured JSON output, then to synthesize the final briefing from selected papers.
6. Synthesizes:
   - only the filter-matched papers
   - key findings and trends
   - a compact "what to read first" section
7. Saves outputs under `reports/` as:
   - structured JSON (`YYYY-MM-DD.json`)
   - markdown report (`YYYY-MM-DD.md`)
   - HTML digest (`YYYY-MM-DD.html`)
   - dashboard index (`index.html`)
   - each daily report records the exact institution/topic filters used that day
8. Publishes `reports/` to GitHub Pages so the dashboard is browsable from your repo site URL.

## Repository structure

```text
.github/workflows/
  daily-robotics-briefing.yml   # Scheduled daily run
config/
  filters.example.yaml          # Institution/topic filters
reports/
  .gitkeep
src/daily_robotics_briefing/
  __init__.py
  collector.py                  # arXiv ingestion + date filtering + enrichment
  briefing_agent.py             # OpenAI agent prompt + summary generation
  main.py                       # CLI entrypoint orchestrating the job
requirements.txt
```

## Setup

### 1) Configure secrets

In GitHub repository settings, add:

- `OPENAI_API_KEY` (required)

### 2) Configure filters

Copy and edit:

```bash
cp config/filters.example.yaml config/filters.yaml
```

### 3) Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m daily_robotics_briefing.main \
  --filters config/filters.yaml \
  --out reports/manual-run.md
```

Use a specific day (backfill) with:

```bash
PYTHONPATH=src python -m daily_robotics_briefing.main \
  --filters config/filters.yaml \
  --submission-date 2026-03-06 \
  --out reports/2026-03-07-backfill.md
```

### 4) Enable GitHub Pages (one-time)

In repository settings, set **Pages → Build and deployment → Source** to **GitHub Actions**.

The daily workflow uploads `reports/` as the Pages artifact, so `reports/index.html` becomes the site homepage for each deployment.

## Notes on institution filtering

arXiv metadata often does not include author affiliation. This project now performs institution extraction deterministically from first-page PDF text. It parses affiliation lines, matches configured aliases to canonical institution names, records paper-level and author-level institutions, and forwards only structured institution results plus metadata/abstracts to the LLM for reporting.

## Example output sections

- Executive summary
- Papers table (`Title | Institution | Link | Overview`)
