"""Offline orchestration tests: real temporary Git remotes, fake build commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'craft.sh'


class CraftToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='craft test ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(SCRIPT, self.root / 'craft.sh')
        self.bin = self.root / 'fake-bin'
        self.bin.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                        CRAFT_TEST_LOG=str(self.root / 'commands.jsonl'), PATH=str(self.bin) + ':' + os.environ['PATH'])
        for name in ['cargo', 'npm']:
            p = self.bin / name
            p.write_text('#!/usr/bin/env python3\nimport os,sys,json\n'
                         'with open(os.environ["CRAFT_TEST_LOG"],"a") as f: f.write(json.dumps([os.path.basename(sys.argv[0]),os.getcwd(),sys.argv[1:]])+"\\n")\n'
                         'sys.exit(9 if os.environ.get("CRAFT_TEST_FAIL") == os.path.basename(sys.argv[0])+":"+os.path.basename(os.getcwd()) else 0)\n')
            p.chmod(0o755)
        self.upstream = self.root / 'upstream.git'
        self.origin = self.root / 'origin.git'
        self.seed = self.root / 'seed'
        self.git('init', '--bare', '--initial-branch=main', str(self.upstream))
        self.git('init', '--bare', '--initial-branch=main', str(self.origin))
        self.git('init', '--initial-branch=main', str(self.seed))
        self.git('-C', str(self.seed), 'config', 'user.email', 'fixture@example.invalid')
        self.git('-C', str(self.seed), 'config', 'user.name', 'Fixture')
        (self.seed / 'source').write_text('one')
        self.commit(self.seed, 'initial')
        for remote in [self.upstream, self.origin]: self.git('-C', str(self.seed), 'push', str(remote), 'main')
        # Keep fixture Git repos outside the sibling discovery directory.
        self.workspace = self.root / 'workspace with spaces'
        self.workspace.mkdir()
        shutil.copy2(SCRIPT, self.workspace / 'craft.sh')
        self.app = self.workspace / 'photocraft'
        self.git('clone', str(self.origin), str(self.app))
        self.git('-C', str(self.app), 'remote', 'add', 'upstream', str(self.upstream))
        self.git('-C', str(self.app), 'config', 'user.email', 'fixture@example.invalid')
        self.git('-C', str(self.app), 'config', 'user.name', 'Fixture')

    def git(self, *args, check=True):
        return subprocess.run(['git', *args], env=self.env, check=check, capture_output=True, text=True).stdout.strip()

    def commit(self, path, message):
        self.git('-C', str(path), 'add', '.')
        self.git('-C', str(path), 'commit', '-m', message)

    def advance(self):
        (self.seed / 'source').write_text('two')
        self.commit(self.seed, 'upstream change')
        self.git('-C', str(self.seed), 'push', str(self.upstream), 'main')
        return self.git('-C', str(self.seed), 'rev-parse', 'HEAD')

    def run_tool(self, *args, expected=0, **env):
        result = subprocess.run([str(self.workspace / 'craft.sh'), *args], env=dict(self.env, **env),
                                capture_output=True, text=True, cwd='/tmp', timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        logs = [line[6:] for line in result.stdout.splitlines() if line.startswith('Logs: ')]
        if logs:
            self.assertEqual((Path(logs[-1]) / 'exit-status').read_text(), f'{expected}\n')
        return result

    def commands(self):
        p = self.root / 'commands.jsonl'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def head(self, path, ref='HEAD'):
        return self.git('-C', str(path), 'rev-parse', ref)

    def test_default_sync_push_and_build(self):
        new = self.advance()
        self.run_tool()
        self.assertEqual(self.head(self.app), new)
        self.assertEqual(self.head(self.origin, 'main'), new)
        self.assertEqual(self.commands()[0][2], ['build', '--locked', '-p', 'photocraft'])

    def test_update_only(self):
        self.advance()
        self.run_tool('--update-only')
        self.assertEqual(self.commands(), [])

    def test_no_push(self):
        old = self.head(self.origin, 'main')
        new = self.advance()
        self.run_tool('--update-only', '--no-push')
        self.assertEqual(self.head(self.app), new)
        self.assertEqual(self.head(self.origin, 'main'), old)

    def test_no_update_does_not_fetch(self):
        old = self.head(self.app)
        self.advance()
        self.run_tool('--no-update')
        self.assertEqual(self.head(self.app), old)
        self.assertEqual(self.git('-C', str(self.app), 'for-each-ref', 'refs/remotes/upstream'), '')

    def test_feature_branch_preserved(self):
        old = self.head(self.app)
        self.git('-C', str(self.app), 'switch', '-c', 'fix/mine')
        (self.app / 'local').write_text('work')
        self.commit(self.app, 'local fix')
        feature = self.head(self.app)
        new = self.advance()
        self.run_tool('--update-only')
        self.assertEqual(self.head(self.app), feature)
        self.assertEqual(self.head(self.app, 'main'), new)
        self.assertEqual(self.git('-C', str(self.app), 'rev-parse', '--abbrev-ref', 'main@{upstream}'), 'origin/main')
        self.assertEqual(self.git('-C', str(self.app), 'branch', '--show-current'), 'fix/mine')
        self.assertNotEqual(old, new)

    def test_dirty_checkout_preserved(self):
        old = self.head(self.app)
        self.advance()
        (self.app / 'source').write_text('unsaved')
        self.run_tool('--update-only', expected=1)
        self.assertEqual(self.head(self.app), old)
        self.assertEqual((self.app / 'source').read_text(), 'unsaved')

    def test_failed_update_does_not_stop_other_forks(self):
        other = self.workspace / 'vectorcraft'
        self.git('clone', str(self.origin), str(other))
        self.git('-C', str(other), 'remote', 'add', 'upstream', str(self.upstream))
        original = self.head(self.app)
        new = self.advance()
        (self.app / 'source').write_text('unsaved')
        self.run_tool('--update-only', expected=1)
        self.assertEqual(self.head(self.app), original)
        self.assertEqual(self.head(other), new)
        self.assertEqual(self.head(self.origin, 'main'), new)

    def test_divergent_local_default_refused(self):
        (self.app / 'local').write_text('work')
        self.commit(self.app, 'local')
        old = self.head(self.app)
        self.advance()
        self.run_tool('--update-only', expected=1)
        self.assertEqual(self.head(self.app), old)

    def test_divergent_fork_refused(self):
        (self.app / 'local').write_text('work')
        self.commit(self.app, 'local')
        self.git('-C', str(self.app), 'push', 'origin', 'main')
        fork = self.head(self.origin, 'main')
        self.git('-C', str(self.app), 'reset', '--hard', 'HEAD^')  # disposable fixture only
        self.advance()
        self.run_tool('--update-only', expected=1)
        self.assertEqual(self.head(self.origin, 'main'), fork)

    def test_explicit_subset_release_and_cli(self):
        (self.workspace / 'vectorcraft').mkdir()
        (self.app / 'apps/photocraft-cli').mkdir(parents=True)
        (self.app / 'apps/photocraft-cli/Cargo.toml').touch()
        self.run_tool('--no-update', '--release', '--jobs', '2', 'vectorcraft', 'photocraft')
        self.assertEqual([args[i + 1] for _, _, args in self.commands() for i, arg in enumerate(args) if arg == '-p'], ['vectorcraft', 'photocraft', 'photocraft-cli'])
        self.assertEqual(len(self.commands()), 2)
        self.assertTrue(all('--release' in c[2] for c in self.commands()))

    def test_failure_continues_to_next_app(self):
        (self.workspace / 'vectorcraft').mkdir()
        self.run_tool('--no-update', 'photocraft', 'vectorcraft', expected=1, CRAFT_TEST_FAIL='cargo:photocraft')
        self.assertEqual([c[2][-1] for c in self.commands()], ['photocraft', 'vectorcraft'])

    def test_log_writer_failure_is_reported(self):
        tee = self.bin / 'tee'
        tee.write_text('#!/bin/sh\ncat\nexit 7\n')
        tee.chmod(0o755)
        self.run_tool('--no-update', expected=1)
        self.run_tool('--update-only', expected=1)

    def test_frontend_failure_prevents_rust_build(self):
        (self.workspace / 'artcraftx/frontend').mkdir(parents=True)
        self.run_tool('--no-update', 'artcraftx', expected=1, CRAFT_TEST_FAIL='npm:frontend')
        self.assertEqual([c[0] for c in self.commands()], ['npm'])

    def test_all_includes_launcher_and_variants(self):
        listed = self.run_tool('--list').stdout.splitlines()
        for app in listed:
            repo = 'artcraft' if app == 'artcraft-native' else app
            (self.workspace / repo).mkdir(exist_ok=True)
        for repo in ['artcraft', 'artcraftx']:
            (self.workspace / repo / 'frontend').mkdir()
        self.run_tool('--no-update', '--all')
        built = [c[2][-1] for c in self.commands() if c[0] == 'cargo']
        self.assertEqual(len(built), len(listed))
        self.assertIn('artcraft-launcher', built)
        self.assertIn('artcraft_native', built)
        self.assertIn('artcraftx', built)
        self.assertIn('craft-status-app', built)

    def test_invalid_arguments_have_no_effects(self):
        for args in [('bogus',), ('--all', 'photocraft'), ('--jobs',), ('--jobs', '0'), ('--wat',)]:
            self.run_tool(*args, expected=2)
        self.assertEqual(self.commands(), [])
        self.assertFalse((self.workspace / '.logs').exists())

    def test_concurrent_run_refused(self):
        import fcntl
        (self.workspace / '.build').mkdir()
        with (self.workspace / '.build/craft.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_tool('--no-update', expected=1)
        self.assertEqual(self.commands(), [])


if __name__ == '__main__':
    unittest.main()
