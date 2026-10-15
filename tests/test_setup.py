"""Exercise prerequisite setup without root access, downloads, or host changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = '''#!/usr/bin/python3
import json,os,sys,subprocess
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
state_path=Path(os.environ['SETUP_STATE'])
state=json.loads(state_path.read_text())
with open(os.environ['SETUP_LOG'],'a') as log: log.write(json.dumps([name,args])+'\\n')
if name=='dpkg-query':
    print('missing' if args[-1] in state.get('missing',[]) else 'installed',end='')
elif name=='node': sys.exit(int(state.get('node_missing',False)))
elif name=='npm': sys.exit(int(state.get('npm_broken',False)))
elif name=='rustup':
    if args[0]=='run': sys.exit(int(state.get('rust_missing',False)))
    if args[:2]==['component','list']: print('clippy-x86_64-unknown-linux-gnu\\nrustfmt-x86_64-unknown-linux-gnu')
    if args[:2]==['target','list']: print('wasm32-unknown-unknown')
    if args[:2]==['toolchain','install']:
        state['rust_missing']=False; state_path.write_text(json.dumps(state))
elif name=='gh':
    if args[:2]==['auth','status']: sys.exit(int(state.get('auth_missing',False)))
    if args[:2]==['auth','login']:
        state['auth_missing']=False; state_path.write_text(json.dumps(state))
elif name=='sudo': sys.exit(subprocess.run(args).returncode)
elif name=='apt-get':
    if state.get('apt_fail'): sys.exit(9)
    if args[0]=='install':
        state['missing']=[]; state_path.write_text(json.dumps(state))
elif name=='curl':
    output=Path(args[args.index('-o')+1])
    if 'https://sh.rustup.rs' in args:
        output.write_text('#!/bin/sh\\nmkdir -p "${CARGO_HOME:-$HOME/.cargo}/bin"\\ncp "$SETUP_RUSTUP" "${CARGO_HOME:-$HOME/.cargo}/bin/rustup"\\n')
    else: output.write_text('0'*64+'  node-v24.11.0-linux-x64.tar.xz\\n')
elif name=='sha256sum': sys.exit(int(state.get('checksum_fail',False)))
elif name=='tar':
    target=Path(args[args.index('-C')+1])/'bin'; target.mkdir()
    for tool in ['node','npm']:
        path=target/tool; path.write_text('#!/bin/sh\\nexit 0\\n'); path.chmod(0o755)
elif name=='uname': print('x86_64')
'''


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='craft setup ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(ROOT / 'craft', self.root)
        shutil.copytree(ROOT / 'scripts', self.root / 'scripts')
        self.fake = self.root / 'fake'
        self.fake.mkdir()
        self.state = {}
        self.env = dict(os.environ, HOME=str(self.root / 'home'),
                        CARGO_HOME=str(self.root / 'home/.cargo'), RUSTUP_HOME=str(self.root / 'home/.rustup'),
                        PATH=f'{self.fake}:/usr/bin:/bin', SETUP_STATE=str(self.root / 'state.json'),
                        SETUP_LOG=str(self.root / 'log.jsonl'), RUSTUP_TOOLCHAIN='1.95.0')
        for name in ['dpkg-query', 'node', 'npm', 'rustup', 'gh', 'sudo', 'apt-get', 'curl', 'sha256sum', 'tar', 'uname']:
            p = self.fake / name
            p.write_text(FAKE)
            p.chmod(0o755)

    def run_setup(self, *args, expected=0):
        Path(self.env['SETUP_STATE']).write_text(json.dumps(self.state))
        result = subprocess.run([str(self.root / 'craft'), 'setup', *args], env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def calls(self):
        return [json.loads(line) for line in Path(self.env['SETUP_LOG']).read_text().splitlines()]

    def test_check_ready_has_no_install_or_auth_side_effects(self):
        self.assertIn('Prerequisites ready', self.run_setup('--check').stdout)
        self.assertFalse((self.root / '.build').exists())
        self.assertFalse(any(name in ['sudo', 'apt-get', 'curl'] for name, _ in self.calls()))
        self.assertFalse(any(args[:2] == ['auth', 'login'] for _, args in self.calls()))

    def test_check_reports_missing_requirements_without_changing_them(self):
        self.state = dict(missing=['libgtk-3-dev'], node_missing=True, rust_missing=True, auth_missing=True)
        result = self.run_setup('--check', expected=1)
        for text in ['libgtk-3-dev', 'Node.js', 'Rust', 'GitHub authentication']:
            self.assertIn(text, result.stdout)
        self.assertFalse((self.root / '.build').exists())

    def test_install_only_missing_packages_and_authenticate(self):
        self.state = dict(missing=['libgtk-3-dev', 'gh'], auth_missing=True)
        self.run_setup()
        apt = [args for name, args in self.calls() if name == 'apt-get']
        self.assertEqual(apt, [['update'], ['install', '-y', '--no-install-recommends', 'gh', 'libgtk-3-dev']])
        self.assertTrue(any(args[:2] == ['auth', 'login'] for name, args in self.calls() if name == 'gh'))
        self.assertTrue(any(args[:2] == ['auth', 'setup-git'] for name, args in self.calls() if name == 'gh'))

    def test_existing_dependencies_do_not_trigger_apt_or_node_download(self):
        self.run_setup()
        self.assertFalse(any(name in ['sudo', 'apt-get', 'curl'] for name, _ in self.calls()))

    def test_checks_real_packages_instead_of_transitional_aliases(self):
        self.run_setup('--check', '--no-auth')
        queried = [args[-1] for name, args in self.calls() if name == 'dpkg-query']
        self.assertIn('libfreetype-dev', queried)
        self.assertIn('libfontconfig-dev', queried)
        self.assertNotIn('libfreetype6-dev', queried)
        self.assertNotIn('libfontconfig1-dev', queried)

    def test_no_auth_never_requests_or_modifies_credentials(self):
        self.state = dict(auth_missing=True)
        self.run_setup('--no-auth')
        self.assertFalse(any(name == 'gh' for name, _ in self.calls()))
        self.run_setup('--check', '--no-auth')

    def test_node_install_checks_checksum_before_unpacking(self):
        self.state = dict(node_missing=True)
        self.run_setup()
        commands = [name for name, _ in self.calls()]
        self.assertLess(commands.index('sha256sum'), commands.index('tar'))
        self.assertTrue((self.root / '.build/tools/node/bin/node').exists())
        self.assertFalse(list((self.root / '.build/tools').glob('node-install-*')))

    def test_broken_npm_triggers_a_working_local_runtime_install(self):
        self.state = dict(npm_broken=True)
        self.run_setup('--no-auth')
        self.assertTrue((self.root / '.build/tools/node/bin/npm').exists())

    def test_checksum_failure_preserves_previous_runtime(self):
        self.state = dict(node_missing=True, checksum_fail=True)
        previous = self.root / '.build/tools/node/keep'
        previous.parent.mkdir(parents=True)
        previous.write_text('previous runtime')
        self.run_setup(expected=1)
        self.assertEqual(previous.read_text(), 'previous runtime')
        self.assertFalse(any(name == 'tar' for name, _ in self.calls()))
        self.assertFalse(list((self.root / '.build/tools').glob('node-install-*')))

    def test_bootstraps_missing_rustup(self):
        rustup = self.fake / 'rustup'
        saved = self.fake / 'saved-rustup'
        rustup.rename(saved)
        self.env['SETUP_RUSTUP'] = str(saved)
        self.run_setup()
        self.assertTrue((Path(self.env['HOME']) / '.cargo/bin/rustup').exists())
        self.assertTrue(any(name == 'curl' and 'https://sh.rustup.rs' in args for name, args in self.calls()))

    def test_custom_cargo_home_is_respected(self):
        saved = self.fake / 'saved-rustup'
        (self.fake / 'rustup').rename(saved)
        self.env.update(SETUP_RUSTUP=str(saved), CARGO_HOME=str(self.root / 'custom cargo'))
        self.run_setup('--no-auth')
        self.assertTrue((Path(self.env['CARGO_HOME']) / 'bin/rustup').exists())

    def test_package_install_failure_stops_setup(self):
        self.state = dict(missing=['gh'], apt_fail=True)
        self.run_setup(expected=9)
        self.assertFalse(any(name == 'rustup' for name, _ in self.calls()))

    def test_invalid_option_has_no_effects(self):
        self.run_setup('--bogus', expected=2)
        self.assertFalse(Path(self.env['SETUP_LOG']).exists())
