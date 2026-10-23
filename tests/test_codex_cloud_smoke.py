"""Exercise the dispatch lifecycle without submitting real cloud tasks."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'cloud_smoke', Path(__file__).resolve().parents[1] / '.github/scripts/codex-cloud-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

TASK_URL = 'https://chatgpt.com/codex/tasks/task_smoke'


def reply(text, code=0):
    return subprocess.CompletedProcess([], code, stdout=text, stderr='')


def result_diff(value=None):
    payload = json.dumps(smoke.EXPECTED if value is None else value)
    return (f'diff --git a/{smoke.RESULT_PATH} b/{smoke.RESULT_PATH}\n'
            f'new file mode 100644\n--- /dev/null\n+++ b/{smoke.RESULT_PATH}\n'
            f'@@ -0,0 +1 @@\n+{payload}\n')


class CodexCloudSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'output'

    def test_submits_once_waits_and_verifies_completed_task_diff(self):
        responses = [reply(TASK_URL), reply('[PENDING] Smoke\n', 1),
                     reply('[READY] Smoke\n'), reply(result_diff())]
        with patch.object(smoke, 'run_cli', side_effect=responses) as cli, \
                patch.object(smoke.time, 'sleep'):
            result = smoke.run_smoke('env-example', self.output)
        self.assertEqual(result['status'], 'verified')
        commands = [call.args[0] for call in cli.call_args_list]
        self.assertEqual(sum(c[:2] == ['cloud', 'exec'] for c in commands), 1)
        self.assertEqual(commands[-1], ['cloud', 'diff', TASK_URL])
        self.assertFalse(any('apply' in c for c in commands))
        self.assertEqual((self.output / 'cloud-task.diff').read_text(), result_diff())

    def test_submitted_task_is_not_reported_as_verified_on_timeout(self):
        with patch.object(smoke, 'run_cli', return_value=reply(TASK_URL)) as cli, \
                patch.object(smoke.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                smoke.run_smoke('env-example', self.output, timeout_seconds=1)
        cli.assert_called_once()
        self.assertEqual(json.loads((self.output / 'result.json').read_text())['status'], 'submitted')

    def test_transport_failure_does_not_retry_submission(self):
        with patch.object(smoke, 'run_cli', return_value=reply('', 1)) as cli:
            with self.assertRaisesRegex(RuntimeError, 'submission failed'):
                smoke.run_smoke('env-example', self.output)
        cli.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_remote_failure_is_not_treated_as_pending_or_success(self):
        for status in ['[ERROR] Failed\n', 'authentication failed\n']:
            with self.subTest(status=status), \
                    patch.object(smoke, 'run_cli', side_effect=[reply(TASK_URL), reply(status, 1)]):
                with self.assertRaises(RuntimeError):
                    smoke.run_smoke('env-example', self.output)
        self.assertFalse((self.output / 'cloud-task.diff').exists())

    def test_rejects_wrong_marker_and_unexpected_repository_changes(self):
        for diff in [result_diff({'marker': 'wrong'}),
                     result_diff() + 'diff --git a/README.md b/README.md\n+changed\n']:
            with self.subTest(diff=diff), \
                    patch.object(smoke, 'run_cli', side_effect=[
                        reply(TASK_URL), reply('[READY] Smoke\n'), reply(diff)]):
                with self.assertRaises(RuntimeError):
                    smoke.run_smoke('env-example', self.output)
        self.assertFalse((self.output / 'cloud-task.diff').exists())


if __name__ == '__main__':
    unittest.main()
