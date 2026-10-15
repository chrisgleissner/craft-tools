"""Verify that release archives contain executable, standalone tooling."""
from pathlib import Path
import shutil
import subprocess
import tarfile

from test_craft_tool import CraftFixture


class PackageTests(CraftFixture):
    def setUp(self):
        super().setUp()
        source = Path(__file__).resolve().parents[1]
        shutil.copy2(source / 'run-craft', self.workspace)
        shutil.copy2(source / '.gitignore', self.workspace)
        shutil.copy2(source / 'README.md', self.workspace)
        self.git('init', '--initial-branch=main', str(self.workspace))
        self.git('-C', str(self.workspace), 'config', 'user.email', 'fixture@example.invalid')
        self.git('-C', str(self.workspace), 'config', 'user.name', 'Fixture')
        self.commit(self.workspace, 'tooling fixture')
        # Ignored runtime data and child repos must never enter the archive.
        (self.workspace / '.logs').mkdir()
        (self.workspace / '.logs/private-log').write_text('local only')

    def package(self, version):
        return subprocess.run(['bash', str(self.workspace / 'scripts/package-release.sh'),
                               version, str(self.root / 'dist')], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_archive_has_executable_commands_and_no_local_data(self):
        result = self.package('v0.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / 'dist'
        subprocess.run(['sha256sum', '--check', 'SHA256SUMS'], cwd=output, check=True, capture_output=True)
        with tarfile.open(output / 'craft-tools-v0.1.0.tar.gz') as archive:
            names = archive.getnames()
            self.assertFalse(any('/.logs' in name or '/photocraft' in name or '/.git/' in name for name in names))
            for name in ['craft', 'run-craft']:
                self.assertTrue(archive.getmember('craft-tools-v0.1.0/' + name).mode & 0o111)
            # This archive was generated entirely from our disposable Git fixture.
            archive.extractall(self.root / 'unpack', filter='data')
        unpack = self.root / 'unpack/craft-tools-v0.1.0'
        for flag in ['--help', '--list']:
            check = subprocess.run([str(unpack / 'craft'), flag], env=self.env, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_invalid_version_has_no_output(self):
        for version in ['../escape', 'v1', 'v1.2.3;bad']:
            result = self.package(version)
            self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'dist').exists())
