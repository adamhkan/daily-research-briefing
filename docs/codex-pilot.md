# Three-day Codex briefing pilot

The pilot uses Codex to answer saved structured requests while retaining the existing paper collector, validation, selection, and report renderer. It does not send requests to the OpenAI API or require an API key. Codex work still consumes the account's Codex allowance; the harness cannot measure that allowance or claim the model work is free.

The default pilot dates are **October 23–25, 2026**, inclusive, with a wake-up at **8:30 a.m. America/New_York** each day. Each report covers the previous Eastern calendar day's submissions. `config/codex-pilot.json` is the shared configuration for the wake-up harness and paid-workflow pause.

## Schedule activation

An external scheduler can submit cloud tasks through the experimental Codex CLI.
The [manual GitHub Actions smoke test](codex-cloud-smoke.md) checks that route;
it has no daily trigger and must pass before adopting it as the recurring wake-up.

The repository contains the runnable harness and exact recurring instructions below. **No recurring Codex task has been registered by this change.** The current chat exposes no tool to create a durable scheduled Codex task. A cron process in this disposable cloud machine would not be a durable substitute.

The prompt below describes the intended recurring task; it does not establish
that the browser has a native scheduling interface. An external scheduler must
first pass the cloud-dispatch test and have a verified authentication strategy.
If a supported scheduling interface is available, use this repository on `main`
and the prepared cloud environment, with these schedule values:

```text
Timezone: America/New_York
First wake-up: 2026-10-23 08:30
Last wake-up: 2026-10-25 08:30
Recurrence: daily, three occurrences
```

The equivalent calendar recurrence is:

```text
DTSTART;TZID=America/New_York:20261023T083000
RRULE:FREQ=DAILY;COUNT=3;BYHOUR=8;BYMINUTE=30;BYSECOND=0
```

If the scheduling interface cannot express a three-occurrence end, configure a daily task and disable it after October 25. The harness independently refuses to prepare a new daily pilot outside the configured date window, so an extra wake-up should stop without model work. Scheduling remains subject to the account's actual scheduling and cloud-execution capabilities.

### Recurring task prompt

Copy this text into the recurring Codex task:

```text
Run the daily Codex research-briefing pilot for adamhkan/daily-research-briefing.

Use the existing isolated checkout under /workspace/daily-research-briefing and
branch main. Do not create a worktree or another checkout. Read any AGENTS.md,
docs/codex-pilot.md, and config/codex-pilot.json. Preserve existing user changes.
If the checkout is clean, fetch origin/main and fast-forward only; do not reset,
force-push, or discard changes. Use the installed .venv/bin/python and PYTHONPATH=src.

Run:
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot wake --config config/codex-pilot.json

Inspect its JSON result. If status is inactive, report the status and stop without
model work. If ready or waiting, use the returned run_dir and enter the advance
loop below. If complete or no_papers, skip the model loop but still perform the
review and checkpoint steps below, including newly generated artifacts. If failed,
report the blocker and perform the review/checkpoint steps; do not automatically
retry a failed run. Source input is frozen for this date; do not recollect or
overwrite it on a retry.

Run:
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot advance --run-dir RUN_DIR

While status is waiting, read the returned request_path. Have a fresh subagent
with no parent conversation and low reasoning process only that request's system
message, user payload, output schema, and output settings. Do not add past reports,
known bugs, hints, or invented data. Use an available low-reasoning Codex model;
record actual model identity if available rather than calling it gpt-5.1. The
request's model field is a workflow label, not an instruction to call an API.
Save only the structured response JSON to a temporary file, then run:
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot submit --run-dir RUN_DIR --request-id REQUEST_ID --response-file RESPONSE_FILE

Call advance again after successful submission. Stored responses are reused on
replay; never request another model answer for an existing accepted response.
Follow repair requests emitted by the harness as separate requests. Do not repair
source evidence or suppress a failed assertion by editing code, the request, or
an already accepted response. If submit or advance fails, inspect the error; make
at most one structural-output correction, then stop and report the blocker rather
than loop. Respect max_requests and stop if the Codex task allowance is exhausted.
On any orderly stop, failure, or max_requests/allowance exhaustion, preserve the
partial run directory through the checkpoint step below. Do not assume an
uncommitted local directory survives a future isolated cloud task.

Do not call the OpenAI API, run the normal API briefing command, use API keys,
install an API-billing fallback, change filters/model budgets, or modify application
code during this scheduled task. Do not run the full regression suite every day
unless repository changes or an observed failure make it necessary.

After any run outcome, inspect available metrics.json, status.json, and any
comparison.json. A missing same-date baseline is unavailable, not zero errors; do
not generate a paid baseline. Save review.md in the run directory with the actual
subagent model identity when exposed, the run outcome, source-reviewed observations
about institution formatting, missing affiliations, selected paper IDs, summary
problems, and unresolved limitations. State how many papers were actually
source-reviewed and identify observed errors by paper ID. Separate no configured
filter match from missing extraction and unavailable source evidence. Distinguish
confirmed defects from ambiguous evidence; never report an unreviewed error count
as zero or imply complete factual accuracy from validation. No-papers days are
distinct outcomes, not model-quality successes. After the final pilot day,
summarize observed quality, successful wake-ups/checkpoints, and Codex usage if
available; say whether the evidence supports continuing, adjusting, or ending the
pilot and list any unresolved limitation.

The runtime records model-request count, requests_by_stage, repair_request_count,
and api_requests=0. Codex token usage is unknown unless the platform supplies it;
do not estimate it from API counters or call the work free.

Default outputs stay under pilots/codex/YYYY-MM-DD for review. Do not write reports/
or deploy the public website while config.publish is false. On every orderly
stop with a run directory, including complete, no_papers, failed, or a request/
allowance cap, commit and push this run's pilot output/status artifacts to main as
a checkpoint. Include source, available request/response records, status, metrics,
and review.md needed for reproducibility. If no artifacts changed, no commit is
needed. Never stage credentials, unrelated user changes, or temporary files. If
commit/push is blocked, report that the checkpoint is local and is not guaranteed
to survive the next task; do not claim it was persisted. Do not send Slack, email,
or other messages.

Finish with a concise task result: completion state, papers processed, model-request
count, validation/repair issues, comparison results when available, and observed
quality limitations. Report Codex token usage as unavailable unless the platform
supplies it. Distinguish these pilot results from the public website and from API
billing totals.
```

## Runtime commands and artifacts

All commands run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot wake --config config/codex-pilot.json
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot advance --run-dir pilots/codex/2026-10-23
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot status --run-dir pilots/codex/2026-10-23
```

`wake` returns `ready` or an existing run state such as `waiting`, `failed`, `complete`, or `no_papers`; it returns `inactive` outside the configured date window. Run-directory fields are present when applicable. Resume `ready`/`waiting` through `advance`; review and checkpoint terminal outcomes without automatically retrying `failed`. `advance` pauses as `waiting` with `request_id` and `request_path`, or ends as `complete`, `no_papers`, or `failed`. `submit` validates response structure and stores a response idempotently; production semantic/source validation happens when `advance` replays the pipeline. A validation repair is a new hashed request. The harness never waits on a live API connection.

Each run retains `source.json`, `manifest.json`, `status.json`, `requests/`, `responses/`, rendered `report/briefing.json`, `report/briefing.md`, `report/briefing.html`, `report/index.html`, `metrics.json`, and `comparison.json` when a matching baseline exists. The scheduled task also writes `review.md` with observed quality findings and model identity when available. The recorded input makes interrupted runs reproducible and distinguishes collection differences from model-output differences, but a future isolated task needs the checkpoint committed and pushed; local files alone are not durable task-to-task storage. The public website is unchanged by default: pilot files are outside `reports/` and do not trigger the website's report-path deployment workflow.

An offline smoke test can use an existing saved report instead of collecting arXiv:

```bash
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot prepare \
  --run-dir /tmp/codex-pilot-smoke \
  --report-date 2026-10-22 \
  --filters config/filters.yaml \
  --source-report reports/2026-10-22/2026-10-22.json \
  --max-requests 64
```

Use a separate run directory for experiments. Never overwrite a frozen pilot input or accepted response to hide a failure.

## Paid workflow pause and automatic resumption

The user chose to pause the paid daily API run during the pilot. The GitHub Actions daily workflow now checks `config/codex-pilot.json` in a separate gate job before dependency installation or API-key injection. For runs using the new gated workflow definition, scheduled runs and manual dispatches skip paid generation and its dependent deployment when **either** their original run creation time maps to a pilot report date **or** the current Eastern calendar date is October 23, 24, or 25. Original report/submission dates are preserved, and invalid or unreadable configuration fails the gate instead of enabling paid work.

GitHub reruns use their original workflow definition. A run created before this gate was added can therefore bypass it, and the separate affiliation-diagnostic workflow is not covered by this pause. Do not rerun pre-change daily runs or launch paid diagnostic actions during the pilot. Live GitHub API run-list access was forbidden in this environment, so existing run state and absence of in-flight paid runs have not been verified.

The original daily cron remains in place. Normal paid generation automatically resumes for report dates beginning **October 26, 2026**, unless configuration is deliberately changed. The workflow pause does not itself start Codex: the recurring task must be activated separately. While pilot output is review-only and paid generation is paused, the public site keeps its last published report.

To end the pause early, set `pause_paid_api` to `false` in the reviewed configuration. To change dates, keep a finite inclusive `start_date`/`end_date` and update the recurring schedule to match. Publishing pilot outputs is a separate explicit decision; changing a calendar schedule alone must not publish them.
