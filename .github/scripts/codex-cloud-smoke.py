"""Submit one cloud smoke task and verify its completed diff, without applying it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.parse import urlparse

RESULT_PATH = 'pilots/cloud-dispatch-smoke.json'
EXPECTED = dict(marker='CODEX_CLOUD_SMOKE_OK',
                repository='adamhkan/daily-research-briefing', harness_import=True)


def smoke_command(repo_root: str = '/workspace/daily-research-briefing') -> str:
    """Select the checkout within the same shell invocation as the command."""
    return f'''set -eu
cd {shlex.quote(repo_root)}
if [ ! -f src/daily_robotics_briefing/codex_pilot.py ]; then
  echo 'Pilot module missing: verify the checkout and main branch' >&2
  exit 78
fi
if [ ! -x .venv/bin/python ]; then
  echo 'Prepared Python missing or unusable in repository .venv; environment setup is required' >&2
  exit 78
fi
PYTHONPATH=src .venv/bin/python -m daily_robotics_briefing.codex_pilot --help
'''


PROMPT = f'''Test Codex Cloud execution in adamhkan/daily-research-briefing on main.
This is a dispatch smoke test, not a daily briefing. Do not collect papers, call
the OpenAI API, read credentials, commit, push, deploy, or start other cloud tasks.
Use the existing checkout; do not create another checkout or worktree.
Locate the checkout and confirm it is adamhkan/daily-research-briefing without
displaying credential-bearing URLs. Do not assume the initial /workspace directory
is its root. The prepared checkout is normally /workspace/daily-research-briefing;
if it is elsewhere, use its verified root in the cd command below.
Run this whole block in one shell invocation and require exit code 0:
{smoke_command()}
Do not install dependencies or silently switch interpreters if the check fails.
Only after those checks succeed, create {RESULT_PATH} containing this exact JSON:
{json.dumps(EXPECTED)}
Do not modify any other tracked files. Leave the new file uncommitted so the
cloud task diff can be verified. If a check fails, report the failure instead of
creating a success marker. Finish with CODEX_CLOUD_SMOKE_OK only on success.
'''


def run_cli(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(['codex', *arguments], capture_output=True, text=True, timeout=90)


def write_result(output: Path, **values) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps(values, indent=2) + '\n')


def verify_diff(diff: str) -> None:
    headers = re.findall(r'^diff --git (.+)$', diff, flags=re.MULTILINE)
    if headers != [f'a/{RESULT_PATH} b/{RESULT_PATH}']:
        raise RuntimeError('Cloud diff must contain only the smoke-result file')
    if not re.search(r'^--- /dev/null$', diff, flags=re.MULTILINE):
        raise RuntimeError('Smoke result must be a new file')
    added = '\n'.join(line[1:] for line in diff.splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    try:
        value = json.loads(added)
    except ValueError as error:
        raise RuntimeError('Cloud task did not return a JSON smoke result') from error
    if value != EXPECTED:
        raise RuntimeError('Cloud task result does not match the expected smoke checks')


def run_smoke(environment: str, output: Path, timeout_seconds: int = 900) -> dict:
    if not environment.strip() or timeout_seconds < 1:
        raise ValueError('An environment ID/label and positive timeout are required')
    # Do not retry this mutation: a transport failure could follow task creation.
    created = run_cli(['cloud', 'exec', '--env', environment, '--branch', 'main',
                       '--attempts', '1', PROMPT])
    if created.returncode:
        raise RuntimeError('Cloud submission failed; check CLI sign-in, environment access, and network connectivity')
    candidates = [line.strip() for line in created.stdout.splitlines() if line.startswith('https://')]
    if len(candidates) != 1:
        raise RuntimeError('Submission did not return exactly one cloud task URL; do not automatically resubmit')
    task_url = candidates[0]
    parsed = urlparse(task_url)
    if parsed.hostname != 'chatgpt.com' or not parsed.path.startswith('/codex/') or parsed.username:
        raise RuntimeError('Submission returned an unexpected task URL')
    write_result(output, status='submitted', task_url=task_url)
    print(f'Cloud task submitted: {task_url}', flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = run_cli(['cloud', 'status', task_url])
        match = re.search(r'^\[(PENDING|READY|APPLIED|ERROR)\]', status.stdout, flags=re.MULTILINE)
        if not match:
            raise RuntimeError('Cannot read cloud task status; submission may still be running')
        state = match.group(1)
        if state == 'ERROR':
            raise RuntimeError('Cloud task reported an execution error')
        if state in ('READY', 'APPLIED'):
            diff = run_cli(['cloud', 'diff', task_url])
            if diff.returncode:
                raise RuntimeError('Cloud task finished but its diff could not be retrieved')
            verify_diff(diff.stdout)
            (output / 'cloud-task.diff').write_text(diff.stdout)
            result = dict(status='verified', task_url=task_url, **EXPECTED)
            write_result(output, **result)
            return result
        print('Cloud task pending', flush=True)
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    raise RuntimeError('Timed out waiting for cloud completion; inspect the existing task instead of resubmitting')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=900)
    args = parser.parse_args()
    try:
        result = run_smoke(args.environment, args.output, args.timeout_seconds)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        # CLI stderr/debug logs are deliberately excluded from uploaded artifacts:
        # they may include account metadata. Keep any submitted task URL for recovery.
        path = args.output / 'result.json'
        result = json.loads(path.read_text()) if path.exists() else {}
        result.update(status='failed', error=str(error))
        write_result(args.output, **result)
        print(json.dumps(result))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
