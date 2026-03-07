# Daily Robotics Research Briefing Agent

This repository contains an AI agent that runs on GitHub Actions and produces a daily summary of recent robotics research from arXiv (`cs.RO`).

## What this agent does

1. Fetches papers from https://arxiv.org/list/cs.RO/recent?skip=0&show=2000.
2. Selects only papers submitted on the day before the run date ("yesterday" by default).
3. Collects title, authors, abstract, subjects, and links.
4. Applies your custom filters:
   - institution allow-list (e.g., MIT, CMU, ETH Zurich)
   - topic keywords (e.g., manipulation, legged locomotion, SLAM)
5. Calls the OpenAI API (default model: `gpt-5.1`) in agent-like mode (with web search enabled when supported) and asks it to keep only papers that match your institution/topic filters before summarization.
6. Synthesizes:
   - only the filter-matched papers
   - key findings and trends
   - a compact "what to read first" section
7. Saves the output as a markdown report under `reports/`.

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

## Notes on institution filtering

arXiv metadata often does not include author affiliation. The code uses a best-effort OpenAlex title lookup first, then falls back to extracting likely affiliation strings from the first pages of the paper PDF when OpenAlex has no match. You can disable or extend these resolvers depending on your quality/speed tradeoff.

## Example output sections

- Executive summary
- Papers table (`Title | Institution | Link | Overview`)
