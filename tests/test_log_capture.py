import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_robotics_briefing.log_capture import capture, redact_text


class LogCaptureTests(unittest.TestCase):
    def test_console_and_persistent_file_receive_the_same_redacted_output(self):
        key = 'credential-test-value'
        output = io.StringIO()
        lines = ['Starting extraction\n', f'AuthenticationError: {key}\n', 'Traceback: failed\n']
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENAI_API_KEY': key}):
            path = Path(tmp) / 'nested' / 'run.log'
            capture(lines, path, output)
            saved = path.read_text()
        self.assertEqual(saved, output.getvalue())
        self.assertNotIn(key, saved)
        self.assertIn('AuthenticationError: [REDACTED]', saved)
        self.assertIn('Traceback: failed', saved)

    def test_redaction_preserves_multiline_traceback_structure(self):
        source = 'ValueError: bad response\n  File "example.py", line 12\nBearer sample-token\n'
        safe = redact_text(source)
        self.assertEqual(safe.count('\n'), source.count('\n'))
        self.assertNotIn('sample-token', safe)
        self.assertIn('example.py', safe)

    def test_shell_pipeline_keeps_failure_status_and_saves_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'failure.log'
            env = {**os.environ, 'PYTHONPATH': 'src', 'TEST_LOG_PATH': str(path),
                   'TEST_PYTHON': sys.executable, 'OPENAI_API_KEY': 'offline-sensitive-value'}
            result = subprocess.run(['bash', '-o', 'pipefail', '-c', '''
"$TEST_PYTHON" -c 'import os,sys; print("fatal: " + os.environ["OPENAI_API_KEY"], file=sys.stderr); sys.exit(7)' \
  2>&1 | "$TEST_PYTHON" -m daily_robotics_briefing.log_capture --out "$TEST_LOG_PATH"
'''], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(path.read_text(), 'fatal: [REDACTED]\n')
            self.assertNotIn('offline-sensitive-value', result.stdout)

    def test_log_commit_rebases_over_a_concurrent_code_push(self):
        script = Path('.github/scripts/persist-run-logs.sh').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, local, other = [root / name for name in ['remote.git', 'local', 'other']]
            def git(*args, cwd=root):
                return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True,
                                      text=True, capture_output=True).stdout
            git('init', '--bare', '--initial-branch=main', remote)
            git('clone', remote, local)
            for target in [local]:
                git('config', 'user.name', 'Test', cwd=target)
                git('config', 'user.email', 'test@example.invalid', cwd=target)
            (local / 'README.md').write_text('initial\n')
            git('add', 'README.md', cwd=local)
            git('commit', '-m', 'initial', cwd=local)
            git('push', 'origin', 'main', cwd=local)
            git('clone', remote, other)
            git('config', 'user.name', 'Test', cwd=other)
            git('config', 'user.email', 'test@example.invalid', cwd=other)
            (other / 'README.md').write_text('concurrent code update\n')
            git('commit', '-am', 'update', cwd=other)
            git('push', 'origin', 'main', cwd=other)
            directory = local / 'logs' / 'diagnostics' / '123-1'
            directory.mkdir(parents=True)
            (directory / 'diagnostic.log').write_text('ValidationError: source mismatch\n')
            subprocess.run(['bash', str(script)], cwd=local, check=True, capture_output=True,
                           env={**os.environ, 'RUN_LOG_DIR': 'logs/diagnostics/123-1',
                                'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REF_NAME': 'main'})
            self.assertEqual(git('--git-dir', remote, 'show', 'main:logs/diagnostics/123-1/diagnostic.log'),
                             'ValidationError: source mismatch\n')
            self.assertEqual((local / 'README.md').read_text(), 'concurrent code update\n')


if __name__ == '__main__':
    unittest.main()
