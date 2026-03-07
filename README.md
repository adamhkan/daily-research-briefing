# Daily Robotics Research Briefing Agent

This repository contains an AI agent that runs on GitHub Actions and produces a daily summary of recent robotics research from arXiv (`cs.RO`).

## What this agent does

1. Fetches up to 2,000 recent papers from https://arxiv.org/list/cs.RO/recent?skip=0&show=2000.
2. Collects title, authors, abstract, subjects, and links.
3. Applies your custom filters:
   - institution allow-list (e.g., MIT, CMU, ETH Zurich)
   - topic keywords (e.g., manipulation, legged locomotion, SLAM)
4. Calls the OpenAI Responses API in agent-like mode (with web search enabled) to synthesize:
   - papers matching your institutions/topics
   - key findings and trends
   - a compact "what to read first" section
5. Saves the output as a markdown report under `reports/`.

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
  collector.py                  # arXiv ingestion + lightweight enrichment
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
python -m daily_robotics_briefing.main \
  --filters config/filters.yaml \
  --out reports/manual-run.md
```

## Notes on institution filtering

arXiv metadata often does not include author affiliation. The code uses a best-effort OpenAlex title lookup first, then falls back to extracting likely affiliation strings from the first pages of the paper PDF when OpenAlex has no match. You can disable or extend these resolvers depending on your quality/speed tradeoff.

## Example output sections

- Executive summary
- Institution-specific highlights
- Topic-specific highlights
- Notable papers (5–15)
- Emerging trends
- Suggested reading order
