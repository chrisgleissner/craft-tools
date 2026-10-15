"""Exercise desktop wrappers without launching apps or changing the real panel."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class LaunchScriptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='craft launcher ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root / 'fake'
        self.fake.mkdir()
        for name in ['run-craft.sh', 'install-shortcuts.sh']:
            shutil.copy2(SOURCE / name, self.root / name)
        self.env = dict(os.environ, HOME=str(self.root), XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_CURRENT_DESKTOP='test', PATH=str(self.fake) + ':' + os.environ['PATH'])
        for name in ['notify-send', 'update-desktop-database']:
            self.executable(self.fake / name, '#!/bin/sh\nexit 0\n')

    def executable(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def invoke(self, script, *args):
        return subprocess.run([str(self.root / script), *args], env=self.env,
                              cwd='/tmp', capture_output=True, text=True, timeout=10)

    def test_default_and_launcher_mapping_and_arguments(self):
        for app, binary in [('photocraft', 'photocraft'), ('craft-launcher', 'artcraft-launcher')]:
            self.executable(self.root / 'bin' / binary,
                            '#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            result = self.invoke('run-craft.sh', app, 'file with spaces.pcraft', '--flag')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['file with spaces.pcraft', '--flag'])
        self.assertEqual(self.invoke('run-craft.sh').returncode, 0)

    def test_missing_binary_and_unknown_app(self):
        result = self.invoke('run-craft.sh', 'craft-launcher')
        self.assertEqual(result.returncode, 1)
        self.assertIn('has not been built', result.stderr)
        self.assertEqual(self.invoke('run-craft.sh', 'unknown').returncode, 2)

    def test_desktop_entries_and_backup(self):
        result = self.invoke('install-shortcuts.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = self.root / 'data/applications'
        photo = entries / 'ai.storyteller.photocraft.desktop'
        launcher = entries / 'ai.storyteller.artcraft-launcher.desktop'
        self.assertIn(f'Exec="{self.root}/run-craft.sh" photocraft %F', photo.read_text())
        self.assertIn(f'Exec="{self.root}/run-craft.sh" craft-launcher', launcher.read_text())
        before = launcher.read_text()
        self.assertEqual(self.invoke('install-shortcuts.sh').returncode, 0)
        self.assertEqual(launcher.read_text(), before)
        backups = list((self.root / '.logs').glob('desktop-backup-*/' + launcher.name))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)

    def test_shortcut_update_preserves_custom_fields_and_actions(self):
        entries = self.root / 'data/applications'
        entries.mkdir(parents=True)
        photo = entries / 'ai.storyteller.photocraft.desktop'
        photo.write_text('[Desktop Entry]\nType=Application\nName=PhotoCraft\n'
                         'GenericName=Custom Editor\nMimeType=image/png;\nTryExec=/old/photocraft\n'
                         'Actions=Custom;\n\n[Desktop Action Custom]\nName=Custom\nExec=custom %F\n')
        result = self.invoke('install-shortcuts.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = photo.read_text()
        self.assertIn('GenericName=Custom Editor', text)
        self.assertIn('MimeType=image/png;', text)
        self.assertIn('[Desktop Action Custom]', text)
        self.assertIn('Exec=custom %F', text)
        self.assertIn(f'TryExec={self.root}/run-craft.sh', text)

    def test_desktop_exec_escapes_special_path_characters(self):
        self.root = self.root / 'path $cash `tick` "quote" \\slash'
        self.root.mkdir()
        shutil.copy2(SOURCE / 'install-shortcuts.sh', self.root)
        result = self.invoke('install-shortcuts.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        photo = Path(self.env['XDG_DATA_HOME']) / 'applications/ai.storyteller.photocraft.desktop'
        line = next(line for line in photo.read_text().splitlines() if line.startswith('Exec='))
        self.assertIn('\\\\$cash', line)
        self.assertIn('\\\\`tick\\\\`', line)
        self.assertIn('\\\\"quote\\\\"', line)
        self.assertIn('\\\\\\\\slash', line)
        self.assertTrue(line.endswith(' photocraft %F'))

    def test_desktop_launch_with_special_path_characters(self):
        python = Path('/usr/bin/python3')
        if not python.exists() or subprocess.run(
                [str(python), '-c', 'from gi.repository import Gio'],
                capture_output=True, timeout=10).returncode:
            self.skipTest('System Python GIO bindings unavailable')
        self.root = self.root / 'path $cash `tick` "quote" \\slash'
        self.root.mkdir()
        for name in ['run-craft.sh', 'install-shortcuts.sh']:
            shutil.copy2(SOURCE / name, self.root)
        self.executable(self.root / 'bin/artcraft-launcher',
                        '#!/usr/bin/python3\nfrom pathlib import Path\n'
                        'Path(__file__).with_name("launched").write_text("ok")\n')
        self.assertEqual(self.invoke('install-shortcuts.sh').returncode, 0)
        desktop = Path(self.env['XDG_DATA_HOME']) / 'applications/ai.storyteller.artcraft-launcher.desktop'
        helper = ('import sys; from gi.repository import Gio; '
                  'app=Gio.DesktopAppInfo.new_from_filename(sys.argv[1]); assert app.launch([], None)')
        result = subprocess.run([str(python), '-c', helper, str(desktop)],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.root / 'bin/launched'
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(marker.read_text(), 'ok')

    def test_unsupported_desktop_paths_are_rejected(self):
        original = self.root
        for name in ['percent%path', 'equals=path']:
            self.root = original / name
            self.root.mkdir()
            shutil.copy2(SOURCE / 'install-shortcuts.sh', self.root)
            result = self.invoke('install-shortcuts.sh')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Desktop shortcut paths cannot contain', result.stderr)


if __name__ == '__main__':
    unittest.main()
