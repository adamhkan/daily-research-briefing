# Test externally triggered Codex Cloud execution

This is a **manual smoke test**, not an activated daily scheduler. It uses the
experimental `codex cloud exec` CLI command to submit one small cloud task, waits
for completion, then checks its diff. Your Mac can be asleep once the GitHub
workflow has started; the runner submits the task and Codex executes it remotely.

The test does not collect papers, call the OpenAI API, commit, push, or publish.
It uses Codex allowance and a small amount of GitHub Actions runtime. The remote
task checks the existing harness's help command and creates only
`pilots/cloud-dispatch-smoke.json` in its isolated checkout. The workflow checks
that exact result and does **not** apply its diff to this repository.

Cloud shells can start at `/workspace`, outside the checkout. The submitted
prompt locates the repository, selects it in the same shell invocation, and
checks the module and virtual environment before launch. A missing or broken
`.venv/bin/python` is a setup failure; the smoke test does not install packages or
silently choose a different interpreter. `cd` in a previous shell call does not
change the working directory of a later call.

For a Dot-native, help-only retry in the standard prepared checkout, use:

```bash
cd /workspace/daily-research-briefing && \
  test -x .venv/bin/python && \
  PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot --help
```

If `cd` or the executable check fails, have Dot report the actual checkout root
and environment state. Do not count that as a successful module test or fabricate
a task URL when the service returns only a task ID.

## Credentials and environment

The GitHub runner needs its own ChatGPT-authenticated Codex CLI credentials.
Platform-provided authentication from this cloud chat must not be exported or
copied to GitHub. No `OPENAI_API_KEY` is used by this test.

On your Mac, sign into Codex CLI using your ChatGPT account. If credentials are
stored in the keychain rather than a file, the CLI's `cli_auth_credentials_store`
configuration can select `file` for a separate sign-in. Do not paste credentials
into chat. Using an existing file-based CLI sign-in, upload it directly to the
repository's Actions secret store:

```bash
codex login status
gh secret set CODEX_CLOUD_AUTH_JSON --repo adamhkan/daily-research-briefing < "$HOME/.codex/auth.json"
```

This secret grants access through your ChatGPT Codex sign-in; it is not a narrowly
scoped repository token. Use it only with trusted workflows and remove it after
the test if you do not proceed. The runner writes it with owner-only permissions,
removes its local copy on completion, and never uploads auth files or CLI debug
logs. Keychain credentials must not be guessed, scraped, or dumped as a fallback.

Find the target cloud environment's ID or unique label in your Codex environment
settings or through `codex cloud`. Select the environment prepared for this
repository; it must have `.venv` and the existing dependencies available. An
environment configuration version ID is not necessarily the environment ID.

## Run and interpret the test

1. In GitHub Actions, open **Test Codex Cloud Dispatch**, then **Run workflow**.
2. Choose branch `main` and supply the cloud environment ID or unique label.
3. Wait for the workflow to finish. The artifact contains `result.json` and, on
   verified success, `cloud-task.diff`. `task_url` opens the corresponding Codex
   cloud task in the browser.

You can also dispatch it from an authenticated GitHub CLI:

```bash
gh workflow run test-codex-cloud.yml --repo adamhkan/daily-research-briefing --ref main -f environment='YOUR_ENVIRONMENT_ID_OR_LABEL'
```

`status: verified` means submission, cloud execution, access to the prepared
repository, the harness help command, and retrieval of the expected result all
succeeded. A submitted URL alone is not success. The driver submits once and
never automatically repeats a failed/ambiguous submission. On a polling timeout,
inspect the existing task before starting another; it may still be running.

The test does not demonstrate full daily-briefing quality or reliable recurring
authentication. Before enabling a daily trigger, test another run after credential
refresh and decide how refreshed credentials will persist: a fresh runner receives
the original secret again, not the previous runner's updated login state. CLI
support is experimental, and a successful manual test is not proof of a durable
recurring service. No `schedule` trigger is present in this workflow.

## Live checks and remaining blockers

Initial cloud-chat requests to `chatgpt.com` and `api.github.com` were blocked by
the proxy before authentication. A saved environment draft adds the required
domains while preserving existing rules and presets; draft saving alone does not
apply or publish it. Subsequent CLI access reached the cloud service but returned
HTTP 401 (`Could not parse your authentication token`). A local `codex login status`
message is therefore not proof that this cloud session can use the cloud-task API.
These environment settings and credentials are separate from GitHub-hosted runners.

The user reported a Dot-native task, ID `01a16672-eb54-73e0-9555-ede894a0e0f7`,
that reached a cloud shell but exited 127: `.venv/bin/python` was resolved from
`/workspace`, rather than the repository directory. The module never started.
No task URL was supplied by the service, so none has been inferred. The corrected
command has passed locally when launched from `/workspace`, and regression tests
cover selecting the checkout and stopping on missing environment setup. A fresh
remote retry and GitHub-hosted smoke execution remain unverified. The existing
paid-workflow pause is unchanged.
