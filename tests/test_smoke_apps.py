"""Exercise smoke-harness failure paths without a real display or app."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import smoke_apps


class SmokeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='craft smoke test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.binary = self.root / '.build/target/debug/photocraft'
        self.binary.parent.mkdir(parents=True)
        self.root_patch = patch.object(smoke_apps, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_missing_binary_is_a_failed_result(self):
        result = smoke_apps.run('photocraft', self.output, 'debug')
        self.assertFalse(result['passed'])
        self.assertEqual(result['error'], 'binary missing')

    def test_unexecutable_binary_is_a_failed_result(self):
        self.binary.write_text('not executable')
        result = smoke_apps.run('photocraft', self.output, 'debug')
        self.assertFalse(result['passed'])
        self.assertIn('Permission denied', result['error'])

    def test_probe_timeout_cleans_up_child(self):
        self.binary.write_text('fixture')
        with patch.object(smoke_apps.subprocess, 'Popen') as popen, \
                patch.object(smoke_apps.subprocess, 'run', side_effect=subprocess.TimeoutExpired('xwininfo', 10)), \
                patch.object(smoke_apps.os, 'killpg') as kill:
            popen.return_value.poll.return_value = None
            popen.return_value.pid = 12345
            result = smoke_apps.run('photocraft', self.output, 'debug')
            self.assertFalse(result['passed'])
            self.assertIn('timed out', result['error'])
            kill.assert_called_once_with(12345, smoke_apps.signal.SIGTERM)
            popen.return_value.wait.assert_called_once_with(timeout=10)


if __name__ == '__main__':
    unittest.main()
