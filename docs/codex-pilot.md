# Three-day Codex briefing pilot

**Status: discontinued.** The user chose to return to the GitHub Actions/OpenAI
API workflow because the Dot run took over half an hour. The daily workflow no
longer has a pilot gate, and `pause_paid_api` is false. The instructions below are
retained for reference, not a request to activate or continue the experiment.
Any recurring schedule created in Dot must be disabled there; this cloud coding
session cannot inspect or cancel Dot-owned schedules.

The pilot uses Codex to answer saved structured requests while retaining the existing paper collector, validation, selection, and report renderer. It does not send requests to the OpenAI API or require an API key. Codex work still consumes the account's Codex allowance; the harness cannot measure that allowance or claim the model work is free.

The default pilot dates are **October 23–25, 2026**, inclusive, with a wake-up at **8:30 a.m. America/New_York** each day. Each report covers the previous Eastern calendar day's submissions. `config/codex-pilot.json` is the shared configuration for the wake-up harness and paid-workflow pause.

## Schedule activation

The user's Dot-native help-command smoke test completed in the prepared cloud
environment with exit code 0 (task ID `01a16684-e2fe-7517-a3bf-025bec31e0ec`;
the service supplied no URL). Dot's native scheduling/delegation is the preferred
pilot route. The complete briefing still needs to be exercised in a fresh cloud
task; the help test alone does not establish daily reliability.

An external scheduler can alternatively submit tasks through the experimental
Codex CLI. The [manual GitHub Actions smoke test](codex-cloud-smoke.md) checks that
separate route; GitHub credentials are not a prerequisite for Dot-native execution.

The repository contains the runnable harness and exact recurring instructions below. **No recurring Codex task has been registered by this change.** The current chat exposes no tool to create a durable scheduled Codex task. A cron process in this disposable cloud machine would not be a durable substitute.

Use the user's Dot to save the schedule and delegate cloud execution, using this
repository on `main` and the same prepared environment as the successful smoke
test. This cloud coding chat cannot register the schedule itself. The intended
schedule values are:

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

If the scheduling interface cannot express a three-occurrence end, use three
one-time schedules or report the limitation and leave recurrence inactive. Do not
create an indefinite schedule. The harness independently refuses to prepare a new
daily pilot outside the configured window, but this does not delete a saved
schedule. Scheduling remains subject to the account's actual capabilities.

### Dot scheduling prompt

Give this to the Dot that ran the successful smoke test:

```text
Create a daily pilot schedule at 08:30 America/New_York on October 23, 24, and 25,
2026 only, for three occurrences total. At each wake-up, launch a Codex CLOUD task
for adamhkan/daily-research-briefing, branch main, using the same prepared cloud
environment as successful test 01a16684-e2fe-7517-a3bf-025bec31e0ec. Do not use my Mac.

In each cloud task, locate /workspace/daily-research-briefing, explicitly select
that working directory, read docs/codex-pilot.md, and execute the instructions in
its "Recurring task prompt" section for today's run. Do not create other schedules.
Use Codex-generated response files, never paid OpenAI API calls. Keep pilot output
separate from the website and persist the run's artifacts as those instructions
require. Return actual completion/failure results and verified persistence state.

Confirm the saved schedule ID, next-run time, timezone, and finite end date or
occurrence count. Report any unsupported scheduling or delegation requirement
instead of claiming activation. No schedule should run after October 25.
```

### Recurring task prompt

Copy this text into the recurring Codex task:

```text
Run the daily Codex research-briefing pilot for adamhkan/daily-research-briefing.

Use the existing isolated checkout under /workspace/daily-research-briefing and
branch main. Do not create a worktree or another checkout. Read any AGENTS.md,
docs/codex-pilot.md, and config/codex-pilot.json. Preserve existing user changes.
If the checkout is clean, fetch origin/main and fast-forward only; do not reset,
force-push, or discard changes. Set every shell tool's working directory to the
verified repository root. The default /workspace is not necessarily that root,
and cd does not persist across separate shell-tool calls. Use the installed
.venv/bin/python and PYTHONPATH=src; stop with a setup error if it is unavailable.

Run:
cd /workspace/daily-research-briefing && PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot wake --config config/codex-pilot.json

Inspect its JSON result. If status is inactive, report the status and stop without
model work. If ready or waiting, use the returned run_dir and enter the advance
loop below. If complete or no_papers, skip the model loop but still perform the
review and checkpoint steps below, including newly generated artifacts. If failed,
report the blocker and perform the review/checkpoint steps; do not automatically
retry a failed run. Source input is frozen for this date; do not recollect or
overwrite it on a retry.

Run:
cd /workspace/daily-research-briefing && PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot advance --run-dir RUN_DIR

While status is waiting, read the returned request_path. Have a fresh subagent
with no parent conversation and low reasoning process only that request's system
message, user payload, output schema, and output settings. Do not add past reports,
known bugs, hints, or invented data. Use an available low-reasoning Codex model;
record actual model identity if available rather than calling it gpt-5.1. The
request's model field is a workflow label, not an instruction to call an API.
Save only the structured response JSON to a temporary file, then run:
cd /workspace/daily-research-briefing && PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot submit --run-dir RUN_DIR --request-id REQUEST_ID --response-file RESPONSE_FILE

Call advance again after successful submission. Stored responses are reused on
replay; never request another model answer for an existing accepted response.
Follow repair requests emitted by the harness as separate requests. Do not rewrite source inputs or suppress a failed assertion by editing code, the request, or
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

## API workflow restored

The normal daily GitHub Actions workflow is restored immediately. Its original
`15 11 * * *` UTC cron, API generation, report persistence, recovery behavior,
and website deployment remain in place. The pilot gate was removed entirely, so
daily generation no longer depends on this experiment's configuration or dates.
`pause_paid_api` is false, and the pilot source, responses, and reports are retained.

The repository change does not cancel tasks independently saved in Dot. Disable
any such recurring schedules in Dot to avoid duplicate experimental runs. Existing
GitHub runs use their original workflow definitions on rerun; a new dispatch or
scheduled run on `main` uses the restored definition.

Current-schema note: model outputs no longer request or validate evidence quotes.
New paper rows contain `claims` with `summary_status: model_generated`; pilot metrics
use `summaries_unavailable` instead of `summaries_without_evidence`. Historical
pilot artifacts retain their original schemas and have not been rewritten.
