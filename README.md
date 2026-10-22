# Daily Robotics Research Briefing Agent

This repository contains an AI agent that runs on GitHub Actions and produces a daily summary of recent robotics research from arXiv (`cs.RO`).

## What this agent does

1. Fetches papers from https://arxiv.org/list/cs.RO/recent?skip=0&show=2000.
2. Selects only papers submitted on the day before the run date in US Eastern time (EST/EDT, "yesterday" by default).
3. Collects title, authors, full abstract, subjects, links, and HTML author affiliations, with a first-page PDF fallback when HTML affiliation data is missing.
4. Applies deterministic institution matching, retaining extraction source, failures, and an explicit unknown status when affiliations cannot be extracted.
5. Calls the OpenAI Responses API (default model: `gpt-6.1-sol`) with strict JSON schemas: classify all fetched papers in batches, write evidence-backed overviews for the selected papers, then summarize only those displayed papers.
6. Synthesizes:
   - only the filter-matched papers
   - key findings and trends
   - ranked topic matches and an executive summary with links to supporting papers
7. Saves outputs under `reports/` as:
   - structured JSON (`YYYY-MM-DD/YYYY-MM-DD.json`)
   - markdown report (`YYYY-MM-DD/YYYY-MM-DD.md`)
   - HTML digest (`YYYY-MM-DD/YYYY-MM-DD.html`)
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

The collector reads complete HTML front matter: explicit affiliation fields, author tables, and author/thanks footnotes, including notes before the author list. Abstract, body, and reference mentions are excluded. Each institution is backed by a short source quote, URL, and HTML locator or PDF page. HTML and PDF versions are pinned together when a version is available.

If HTML does not provide usable affiliation information, the collector downloads a PDF up to `max_pdf_megabytes` (default 32 MiB), reads its first page with layout preservation, and reconstructs wrapped author footnotes. When PDF text is absent, local Poppler/Tesseract OCR processes only the first page, with bounded image size and execution time. The daily workflow installs these tools; local users can install `poppler-utils` and `tesseract-ocr` to enable OCR. Missing tools, size limits, and source failures are recorded explicitly.

Clear institutional fields and explicit author-affiliation statements are handled deterministically. Curated full-name/acronym aliases resolve institution identity; automatic fuzzy matching, token-subset matching, guessed acronyms, and assigning a sole paper-level institution to every author have been removed. Joint affiliations count. Funding, acknowledgments, datasets, references, former affiliations, and work-done-at notes do not create current-author filter matches. Author associations remain empty when the source only establishes a paper-level institution.

Ambiguous front matter uses a strict-schema model extraction step in batches (`affiliation_batch_size`, default 12). It receives bounded snippets (`affiliation_snippet_chars`, default 4,000 characters per paper) under a run-wide source-text cap (`affiliation_max_input_chars`, default 60,000). Setting the run-wide cap to zero disables model affiliation fallback. Model output must quote supplied text verbatim, retain the original institution name, and support any author associations. A failed fallback preserves deterministic confirmations and marks the remaining extraction unresolved; it does not turn missing evidence into a nonmatch. The source-character cap excludes JSON/schema/prompt overhead and a possible repair request, so it is not a token billing cap.

Each paper records `affiliation_evidence`, `affiliation_complete`, `affiliation_identity_complete`, source/version metadata, and `institution_match_status`:

- `matched`: at least one supported current-author institution matches a configured identity, even if additional affiliations remain unresolved.
- `no_match`: extraction is complete and all identified institutions resolve to known identities outside the filters.
- `unresolved`: source information exists but extraction or institutional identity is incomplete. Original unfamiliar names remain visible rather than being forced onto a similar university.
- `source_unavailable`: no usable affiliation/front-matter source was obtained.

Reports aggregate the last two states as unknown, with separate counts in `affiliation_status_counts`. Raw evidence is cached under `.cache/affiliations`, keyed by paper/version, source content, extractor version, and model. Filter decisions are recomputed, including when the configured list changes. Only complete, revalidated evidence is reused. The workflow restores this cache between runs; cache contents contain public paper evidence, not credentials.

## Selection, grounding, and cost controls

Every fetched paper is classified using its full abstract. `classification_batch_size` (default 25) limits papers per classification request, not total coverage. The legacy `max_papers_for_llm` setting is accepted as a batch-size fallback capped at 25; it no longer drops papers. `max_papers` still caps collection (default 400), with a warning when the listing exceeds that limit.

Code preserves all institution matches, then selects up to `max_topic_matches` additional papers (default 10). Topics are ranked by relevance (0–3), then an evidence-based contribution score (0–3), then paper ID for deterministic ties. The contribution score favors explicit comparative evaluation, real-robot validation, or demonstrated generalization; it is a model judgment, not an independent quality assessment. Overviews are generated only for that final reading list, in batches controlled by `summary_batch_size` (default 10). Institutions, titles, URLs, and section membership come from collected records.

Each overview claim retains a verbatim abstract quote in the JSON report. Quotes are checked against the source, and numerical values must occur in the supporting quote. The executive summary is generated from displayed overviews only, retains supporting paper IDs, checks numbers against cited summaries, and renders links to those papers. Prompts require author-reported phrasing and preserve simulation/hardware distinctions and caveats. These checks improve grounding; they do not independently verify experimental claims or prove every paraphrase is correct.

Missing, duplicate, or unexpected classification/overview IDs and malformed structured outputs trigger one repair attempt, then fail the run before reports are written. Requests have explicit output-token limits and low reasoning effort. The default is `gpt-6.1-sol`; use `--model` to override it. Confirm access and current pricing for your API account before a live run. Total usage can vary with paper volume, full abstracts, evidence output, and repairs. No extra API calls are made for summaries when no papers qualify. `api_usage` in the JSON report and workflow log records SDK request counts and API-reported input, output, cached-input, and reasoning tokens, including completed repair responses. Reasoning tokens are a subset of output tokens; SDK-internal network retries are not separately counted. These counts do not calculate a dollar cost.

Run the offline regression suite with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Tests include abbreviated real-paper front-matter fixtures (ContactBench, CoopUQ, DexOAK, the robotics-exposure paper, the giant Rubik’s Cube paper, InJePA, and others), real SDK request serialization through a simulated HTTP transport, PDF/OCR parsing, cache invalidation, ranking, grounding checks, and CLI report generation without paid API calls. The daily workflow runs these tests before generating the briefing.

## Example output sections

- Executive summary
- Papers table (`Title | Institution | Link | Overview`)
