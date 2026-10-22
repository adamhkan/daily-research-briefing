# Daily Robotics Research Briefing Agent

This repository contains an AI agent that runs on GitHub Actions and produces a daily summary of recent robotics research from arXiv (`cs.RO`).

## What this agent does

1. Fetches papers from https://arxiv.org/list/cs.RO/recent?skip=0&show=2000.
2. Selects only papers submitted on the day before the run date in US Eastern time (EST/EDT, "yesterday" by default).
3. Collects title, authors, full abstract, subjects, links, and HTML author affiliations, with a first-page PDF fallback when HTML affiliation data is missing.
4. Applies deterministic institution matching, retaining extraction source, failures, and an explicit unknown status when affiliations cannot be extracted.
5. Calls the OpenAI Responses API (default model: `gpt-5.1`) with strict JSON schemas: classify all fetched papers in batches, write evidence-backed overviews for the selected papers, then summarize only those displayed papers.
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
  retry-robotics-briefing.yml   # Delayed recovery of a failed run
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

### Automatic recovery

A separate recovery workflow checks every 15 minutes. If the latest daily briefing on `main` failed or timed out at least 30 minutes ago, it requests **one automatic retry** of failed jobs and their dependent jobs (at most two attempts total). This also covers hosted-runner allocation failures, which happen before any briefing steps execute. Successful jobs are not repeated; a failed build may repeat any API calls it completed before failing.

Recovery only considers scheduled or manually dispatched runs that failed within the last 24 hours. It skips cancelled runs, runs already retried manually or automatically, and older failures superseded by a newer run. Briefing runs are serialized per branch. A rerun checks out the latest branch contents and retains the original run's report/submission dates in US Eastern time, including across midnight.

Normally the retry is requested about 30–45 minutes after failure; GitHub can delay scheduled workflows or runner allocation further. The checker does not keep a runner waiting for 30 minutes. No additional secret is needed: it uses the repository's built-in `GITHUB_TOKEN` with `actions: write`. You can also manually run **Retry Failed Robotics Briefing** to perform the same eligibility check. Persistent failures need manual attention after the one retry.

## Notes on institution filtering

The collector reads complete HTML front matter: explicit affiliation fields, author tables, and author/thanks footnotes, including notes before the author list. Abstract, body, and reference mentions are excluded. Each institution is backed by a short source quote, URL, and HTML locator or PDF page. HTML and PDF versions are pinned together when a version is available.

If HTML does not provide usable affiliation information, the collector downloads a PDF up to `max_pdf_megabytes` (default 32 MiB), reads its first page with layout preservation, and reconstructs wrapped author footnotes. When PDF text is absent, local Poppler/Tesseract OCR processes only the first page, with bounded image size and execution time. The daily workflow installs these tools; local users can install `poppler-utils` and `tesseract-ocr` to enable OCR. Missing tools, size limits, and source failures are recorded explicitly.

Clear institutional fields and explicit author-affiliation statements are handled deterministically. Curated full-name/acronym aliases resolve institution identity; automatic fuzzy matching, token-subset matching, guessed acronyms, and assigning a sole paper-level institution to every author have been removed. Joint affiliations count. Source names and quotes are retained separately from resolved identities. Model extraction requests one clean organization name per entry, copied from the source, with department/address context kept in the separate evidence quote. Explicit parent organizations are preferred over department prefixes; standalone labs and unfamiliar organizations retain their own names. Campus, branch, and business-unit qualifiers must be preserved. Source abbreviations are not expanded by the model; alias resolution remains deterministic. Bounded validation catches known omitted campus qualifiers, but does not establish that every organizational boundary is correct. Full-name aliases inside a department/lab field can resolve when the remaining suffix is an explicit country; unknown qualifiers and multiple institution hits remain unresolved. A unique whole-field full-name comparison can recover missing PDF spaces, and apostrophe variants are normalized. No general fuzzy matching is used. Project-page tails are removed from dedicated HTML affiliation fields, and punctuation-only or template-placeholder names are rejected. Funding, acknowledgments, datasets, references, former affiliations, and work-done-at notes do not create current-author filter matches. Author associations remain empty when the source only establishes a paper-level institution.

The built-in catalog excludes ambiguous abbreviations such as `UW`, `UCB`, `NTU`, `OSU`, `USC`, `UCD`, and `UNIGE`, and common-word aliases such as `FAIR`, `AS`, `HIT`, `Rice`, and `Mines`. Bare `Intrinsic` is not automatically recognized as a company. Full institution names and specific aliases remain available; an unfamiliar extracted name is retained as unresolved. Miami University and the University of Miami are distinct, as are Boston Dynamics and Boston Dynamics AI Institute, and Amazon Robotics, Amazon Alexa AI, and Amazon Lab126. Generic “Max Planck Institute” does not identify a particular institute. Explicit filter aliases can override these conservative catalog choices, so avoid reintroducing ambiguous names in custom configuration.

Ambiguous front matter uses a strict-schema model extraction step in batches (`affiliation_batch_size`, default 12). It receives bounded snippets (`affiliation_snippet_chars`, default 4,000 characters per paper) under a run-wide source-text cap (`affiliation_max_input_chars`, default 120,000). Setting the run-wide cap to zero disables model affiliation fallback. Model output must quote supplied text verbatim and retain the original institution name. Dedicated affiliation fields are preferred over general context when they explicitly support the same institution; each retained author association must have evidence in its recorded block. Unsupported author links are omitted without discarding a verified paper-level institution. Extraction completeness describes institutional evidence, not completeness of per-author mappings; omissions are recorded as `affiliation_author_mappings_omitted`.

Invalid institutional claims trigger one repair attempt. If a claim is still invalid, only that claim is rejected, its paper's extraction remains incomplete, and independently verified claims from the same paper and batch survive. Rejected claims are logged and recorded as `affiliation_model_claim_rejected`. Whole-response API/schema/ID failures without any validated response retain deterministic confirmations and mark the remaining extraction unresolved. Missing evidence is never turned into a nonmatch. The source-character cap excludes JSON/schema/prompt overhead and a possible repair request, so it is not a token billing cap.

Fallback warnings include the model, exception type/message, chained validation cause with the affected paper ID, and API status/request ID when available. Warnings redact credentials, omit HTTP headers and full model responses, and bound the error detail to 2,000 characters.

### Persistent logs and isolated diagnostics

The daily job streams test output and briefing stdout/stderr (including exceptions) to credential-redacted files in `logs/briefings/<run-id>-<attempt>/`. These are committed to the run's branch even when generation fails, so they can be read through Git. A `briefing-logs-<run-id>-<attempt>` artifact also retains them for 30 days. Report files remain under `reports/`; logs are not published to Pages. Failures before the application starts may produce no application log, and saving logs still requires a working runner and GitHub service.

To investigate affiliation failures without rebuilding the briefing, open **Actions → Diagnose Affiliation Extraction → Run workflow**. Leave `report_path` blank to use the latest saved report, or specify a report JSON path. The default `sample_size` of 12 replays the first failed batch; use 1 to inspect its first paper. This uses saved front matter without arXiv/PDF downloads, ignores the affiliation cache, and makes at most two affiliation model requests, with SDK network retries disabled. It skips classification, summaries, report writing, and deployment. It uses the current default model (`gpt-5.1`), the report's institution filters, and the current curated aliases and extraction limits. A historical report's model does not override the current default; local callers can select one explicitly with `--model`.

Diagnostic logs and JSON evidence are committed under `logs/diagnostics/<run-id>-<attempt>/`, even when validation fails, and attached as a 30-day artifact. Evidence includes the selected source records, exact request payloads, model output text for each completed response, validation warnings, results, and API usage. Credentials are redacted; HTTP headers are not saved. The diagnostic action fails when the replay fails or makes no model request. You can run it locally with:

```bash
PYTHONPATH=src python -u -m daily_robotics_briefing.diagnose_affiliations \
  --report reports/2026-10-21/2026-10-21.json \
  --output-dir /tmp/affiliation-diagnostic
```

Each paper records `affiliation_evidence`, `affiliation_complete`, `affiliation_identity_complete`, source/version metadata, and `institution_match_status`:

- `matched`: at least one supported current-author institution matches a configured identity, even if additional affiliations remain unresolved.
- `no_match`: extraction is complete and all identified institutions resolve to known identities outside the filters.
- `unresolved`: source information exists but extraction or institutional identity is incomplete. Original unfamiliar names remain visible rather than being forced onto a similar university.
- `source_unavailable`: no usable affiliation/front-matter source was obtained.

Reports aggregate the last two states as unknown, with separate counts in `affiliation_status_counts`. These diagnostics remain in JSON and logs; reader-facing HTML and Markdown show the number of papers in the selected briefing instead. Common inline summary notation is converted to readable Unicode, and redundant `[reported result]` labels are omitted from display without altering stored claims or evidence. Each paper also records `affiliation_resolution_status`, summarized by `affiliation_resolution_counts`: `filter_match`, `verified_nonmatch`, `unresolved_identity`, `incomplete_extraction`, or `no_usable_evidence` (in that precedence order). Missing evidence takes precedence over incomplete extraction; unresolved identity means extraction is complete but catalog resolution is not. Existing matching statuses remain unchanged for compatibility. Raw evidence is cached under `.cache/affiliations`, keyed by paper/version, source content, extractor version, and model. Filter decisions are recomputed, including when the configured list changes. Only complete, revalidated evidence is reused. The workflow restores this cache between runs; cache contents contain public paper evidence, not credentials.

## Selection, grounding, and cost controls

Every fetched paper is classified using its full abstract. Topic classification returns relevance and contribution scores with a short rationale; it does not require a verbatim evidence quote. Scientific overview claims and affiliation identification retain their separate evidence requirements. `classification_batch_size` (default 25) limits papers per classification request, not total coverage. The legacy `max_papers_for_llm` setting is accepted as a batch-size fallback capped at 25; it no longer drops papers. `max_papers` still caps collection (default 400), with a warning when the listing exceeds that limit.

Code preserves all institution matches, then selects up to `max_topic_matches` additional papers (default 10). Topics are ranked by relevance (0–3), then an evidence-based contribution score (0–3), then paper ID for deterministic ties. The contribution score favors explicit comparative evaluation, real-robot validation, or demonstrated generalization; it is a model judgment, not an independent quality assessment. Overviews are generated only for that final reading list, in batches controlled by `summary_batch_size` (default 10). Institutions, titles, URLs, and section membership come from collected records.

Each overview claim retains a verbatim abstract quote in the JSON report. Quotes are checked against the source, and numerical values must occur in the supporting quote. Invalid overview evidence triggers one repair attempt with paper IDs and claim positions. If evidence remains invalid, unsupported claims are omitted while verified claims survive. Papers with no verified claims remain in the reading list with an explicit unavailable-summary notice and `summary_status: evidence_validation_failed`; they are excluded from executive-summary inputs. This evidence failure does not abort the briefing. The executive summary is generated from displayed overviews only, retains supporting paper IDs, checks numbers against cited summaries, and renders links to those papers. Prompts require author-reported phrasing and preserve simulation/hardware distinctions and caveats. These checks improve grounding; they do not independently verify experimental claims or prove every paraphrase is correct.

Missing, duplicate, or unexpected classification/overview IDs and malformed structured outputs trigger one repair attempt, then fail the run before reports are written. Requests have explicit output-token limits and low reasoning effort. The default is `gpt-5.1`; use `--model` to override it. Confirm access and current pricing for your API account before a live run. Total usage can vary with paper volume, full abstracts, evidence output, and repairs. No extra API calls are made for summaries when no papers qualify. `api_usage` in the JSON report and workflow log records SDK request counts and API-reported input, output, cached-input, and reasoning tokens, including completed repair responses. Reasoning tokens are a subset of output tokens; SDK-internal network retries are not separately counted. These counts do not calculate a dollar cost.

Run the offline regression suite with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
node --test tests/test_briefing_recovery.cjs
```

Tests include abbreviated real-paper front-matter fixtures (ContactBench, CoopUQ, DexOAK, the robotics-exposure paper, the giant Rubik’s Cube paper, InJePA, and others), real SDK request serialization through a simulated HTTP transport, PDF/OCR parsing, cache invalidation, ranking, grounding checks, and CLI report generation without paid API calls. The daily workflow runs these tests before generating the briefing.

## Example output sections

- Executive summary
- Papers table (`Title | Institution | Link | Overview`)
