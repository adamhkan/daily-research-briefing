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

## Current cloud-chat network blocker

The current development environment allows the required Git operations, but its
proxy blocks `chatgpt.com` and `api.github.com` before authentication. An environment
draft adds those domains and `developers.openai.com`, preserving `api.openai.com`
and `arxiv.org` and the existing package-manager preset. Review and save that draft
in environment settings, then publish it before retrying this chat's connectivity
checks. Saving a draft alone does not apply it. These settings affect this cloud
environment, not GitHub-hosted runners.

No live cloud-task submission or GitHub-hosted smoke execution has yet been
verified. The existing paid-workflow pause is unchanged.
