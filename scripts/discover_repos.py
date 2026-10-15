#!/usr/bin/env python3
"""Discover storytold Craft repositories and safely provision missing forks."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

OWNER = 'storytold'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')


def gh_json(*args):
    output = subprocess.check_output(['gh', 'api', '--hostname', 'github.com', *args], text=True)
    return json.loads(output)


def remote_repo(path, remote):
    value = subprocess.check_output(
        ['git', '-C', str(path), 'config', '--get', f'remote.{remote}.url'], text=True).strip()
    if value.startswith('git@github.com:'):
        name = value.removeprefix('git@github.com:')
    else:
        parsed = urlparse(value)
        if parsed.hostname != 'github.com' or parsed.scheme not in ('https', 'ssh'):
            raise ValueError(f'{remote} must point to github.com')
        name = parsed.path.lstrip('/')
    name = name.removesuffix('.git')
    parts = name.split('/')
    if len(parts) != 2 or not all(NAME.fullmatch(part) for part in parts):
        raise ValueError(f'Invalid {remote} repository path')
    return name.lower()


def validate_checkout(path, source, login, details=None):
    if path.is_symlink() or not (path / '.git').exists():
        raise ValueError('Destination exists but is not an independent Git checkout')
    if remote_repo(path, 'upstream') != source.lower():
        raise ValueError('Existing upstream does not match; leaving checkout unchanged')
    origin = remote_repo(path, 'origin')
    if origin.split('/')[0] != login.lower():
        raise ValueError('Existing origin is not owned by the authenticated user')
    details = details if details is not None else gh_json(f'repos/{origin}')
    if not details.get('fork') or details.get('parent', {}).get('full_name', '').lower() != source.lower():
        raise ValueError('Origin is not a fork of the expected upstream; leaving checkout unchanged')


def provision(root, name, login):
    source = f'{OWNER}/{name}'
    destination = root / name
    if destination.exists() or destination.is_symlink():
        validate_checkout(destination, source, login)
        print(f'FOUND {source}', flush=True)
        return True
    # Size zero is not sufficient evidence that a repository has no commits.
    branches = gh_json(f'repos/{source}/branches?per_page=1')
    if not isinstance(branches, list):
        raise ValueError('Invalid branches response')
    if not branches:
        print(f'SKIP {source}: empty repository (cannot fork yet)', flush=True)
        return False
    fork = gh_json('--method', 'POST', f'repos/{source}/forks')
    full_name = fork.get('full_name', '')
    parts = full_name.split('/')
    if (len(parts) != 2 or not all(NAME.fullmatch(part) for part in parts)
            or parts[0].lower() != login.lower()):
        raise ValueError('Fork response did not identify a user-owned repository')
    # GitHub can return an existing fork under a different name. Check its parent.
    for attempt in range(4):
        try:
            details = gh_json(f'repos/{full_name}')
            break
        except subprocess.CalledProcessError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if not details.get('fork') or details.get('parent', {}).get('full_name', '').lower() != source.lower():
        raise ValueError('Returned repository is not a fork of the expected upstream')
    # Failed clones remain temporary and never masquerade as complete checkouts.
    with tempfile.TemporaryDirectory(prefix=f'clone-{name}-', dir=root / '.build') as tmp:
        checkout = Path(tmp) / 'checkout'
        for attempt in range(3):
            try:
                subprocess.run(['gh', 'repo', 'clone', f'https://github.com/{full_name}.git', str(checkout)], check=True)
                break
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
                if checkout.exists():
                    shutil.rmtree(checkout)
                time.sleep(2 ** attempt)
        remotes = subprocess.check_output(['git', '-C', str(checkout), 'remote'], text=True).splitlines()
        action = 'set-url' if 'upstream' in remotes else 'add'
        subprocess.run(['git', '-C', str(checkout), 'remote', action, 'upstream',
                        f'https://github.com/{source}.git'], check=True)
        if remote_repo(checkout, 'origin') != full_name.lower():
            raise ValueError('Cloned origin does not match the expected fork')
        validate_checkout(checkout, source, login, details)
        if destination.exists() or destination.is_symlink():
            raise ValueError('Destination appeared during clone; leaving it unchanged')
        checkout.rename(destination)
    print(f'CLONED {full_name} -> {name}', flush=True)
    return True


def discover(root, inventory):
    # Materialize and validate every page before creating forks or checkouts.
    pages = gh_json('--paginate', '--slurp', f'orgs/{OWNER}/repos?type=all&per_page=100')
    if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
        raise ValueError('Invalid paginated repository response')
    names = set()
    for page in pages:
        for repo in page:
            name = repo['name']
            if not NAME.fullmatch(name) or repo['owner']['login'].lower() != OWNER:
                raise ValueError('Unexpected repository owner or name')
            if 'craft' in name.lower():
                names.add(name)
    login = gh_json('user')['login']
    if not NAME.fullmatch(login):
        raise ValueError('Invalid authenticated user')
    failed = False
    with inventory.open('w') as listing:
        for name in sorted(names, key=str.lower):
            try:
                if provision(root, name, login):
                    listing.write(name + '\n')
                    listing.flush()
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                print(f'FAILED discover {name}: {error}', flush=True)
                failed = True
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('inventory', type=Path)
    args = parser.parse_args()
    try:
        return discover(args.root.resolve(), args.inventory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'FAILED discovery: {error}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
