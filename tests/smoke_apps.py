#!/usr/bin/env python3
"""Launch built desktop apps on an isolated X display and capture rendered windows.

Run: xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
     python3 tests/smoke_apps.py [APP ...]
Uses xwininfo, ImageMagick import/identify, and an isolated temporary HOME per app.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BINARIES = {'craft-launcher': 'artcraft-launcher', 'artcraft-native': 'artcraft-native',
            'craft-repo-status-app': 'craft-status-app'}


def run(app, output, profile):
    binary = ROOT / '.build/target' / profile / BINARIES.get(app, app)
    result = {'app': app, 'binary': str(binary), 'passed': False}
    if not binary.is_file():
        return dict(result, error='binary missing')
    with tempfile.TemporaryDirectory(prefix='craft-smoke-') as tmp:
        home = Path(tmp)
        runtime = home / 'run'
        runtime.mkdir(mode=0o700)
        env = {k: v for k, v in os.environ.items() if k in [
            'PATH', 'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'LANG', 'LD_LIBRARY_PATH']}
        env.update(HOME=tmp, XDG_CONFIG_HOME=str(home / 'config'), XDG_DATA_HOME=str(home / 'data'),
                   XDG_CACHE_HOME=str(home / 'cache'), XDG_RUNTIME_DIR=str(runtime),
                   WINIT_UNIX_BACKEND='x11', WEBKIT_DISABLE_DMABUF_RENDERER='1',
                   WEBKIT_DISABLE_COMPOSITING_MODE='1', PHOTOCRAFT_NO_PRINT='1',
                   RUST_LOG='info')
        log = output / (app + '.log')
        with log.open('w') as stream:
            try:
                process = subprocess.Popen([str(binary)], cwd=home, env=env,
                                           stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as error:
                return dict(result, error=str(error), log=str(log))
            try:
                deadline = time.monotonic() + 90
                window = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f'exited before readiness (status {process.returncode})')
                    tree = subprocess.run(['xwininfo', '-root', '-tree'], env=env, capture_output=True, text=True, check=True, timeout=10)
                    for line in tree.stdout.splitlines():
                        match = re.match(r'\s*(0x[0-9a-fA-F]+).*?\s(\d+)x(\d+)[+-]', line)
                        if match and int(match[2]) >= 200 and int(match[3]) >= 150:
                            info = subprocess.run(['xwininfo', '-id', match[1]], env=env, capture_output=True, text=True, check=True, timeout=10)
                            pid_property = subprocess.run(['xprop', '-id', match[1], '_NET_WM_PID'], env=env, capture_output=True, text=True, check=True, timeout=10)
                            if 'Map State: IsViewable' in info.stdout and re.search(r'=\s*' + str(process.pid) + r'\b', pid_property.stdout):
                                window = match[1]
                                break
                    if window:
                        break
                    time.sleep(0.5)
                if not window:
                    raise RuntimeError('no visible app window within 90 seconds')
                time.sleep(8)  # allow first frames and delayed startup errors to surface
                if process.poll() is not None:
                    raise RuntimeError(f'exited after opening (status {process.returncode})')
                screenshot = output / (app + '.png')
                subprocess.run(['import', '-display', env['DISPLAY'], '-window', window, str(screenshot)],
                               env=env, capture_output=True, check=True, timeout=20)
                colors = int(subprocess.check_output(['identify', '-format', '%k', str(screenshot)], text=True, timeout=20))
                if colors < 10:
                    raise RuntimeError(f'window appears unrendered ({colors} colors)')
                wm_class = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS'], env=env, text=True, timeout=10).strip()
                result.update(passed=True, window=window, screenshot=str(screenshot), colors=colors, wm_class=wm_class,
                              evidence='visible rendered window and process alive after 8 seconds')
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
                result['error'] = str(error)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        result['log'] = str(log)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apps', nargs='*')
    parser.add_argument('--profile', choices=['debug', 'release'], default='debug')
    args = parser.parse_args()
    apps = args.apps or subprocess.check_output([str(ROOT / 'craft'), '--list'], text=True).splitlines()
    known = subprocess.check_output([str(ROOT / 'craft'), '--list'], text=True).splitlines()
    if any(app not in known for app in apps):
        parser.error('Unknown app')
    if not os.environ.get('DISPLAY') or re.fullmatch(r'(?:unix)?:0(?:\.\d+)?', os.environ['DISPLAY']):
        parser.error('Use an isolated X display via xvfb-run; do not run this on the user desktop')
    output = ROOT / '.logs' / ('smoke-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    output.mkdir(parents=True)
    results = []
    for app in apps:
        result = run(app, output, args.profile)
        results.append(result)
        (output / 'results.json').write_text(json.dumps(results, indent=2))
        print(app, 'PASS' if result['passed'] else 'FAIL', result.get('error', ''), flush=True)
    print('Evidence:', output, flush=True)
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
