"""Discovery tests use paginated fake GitHub responses and real local Git remotes."""
import json
from pathlib import Path

from test_craft_tool import CraftFixture


FAKE_GH = '''#!/usr/bin/env python3
import json,os,sys,subprocess,shutil
from pathlib import Path
args=sys.argv[1:]
state=json.loads(Path(os.environ['GH_FIXTURE']).read_text())
with open(os.environ['GH_FIXTURE_LOG'],'a') as log: log.write(json.dumps(args)+'\\n')
if args[0]=='api':
    endpoint=args[-1]
    if endpoint.startswith('orgs/'):
        if state.get('api_fail'): sys.exit(1)
        print(json.dumps(state['pages']))
    elif endpoint=='user': print(json.dumps({'login':'fixture'}))
    elif '/branches?' in endpoint:
        name=endpoint.split('/')[2]
        print(json.dumps([] if name in state.get('empty',[]) else [{'name':'main'}]))
    elif endpoint.endswith('/forks'):
        name=endpoint.split('/')[2]
        if name in state.get('fork_fail',[]): sys.exit(1)
        fork=state.get('fork_names',{}).get(name,name)
        path=Path(os.environ['GH_REMOTE_ROOT'])/'forks'/(fork+'.git')
        if not path.exists(): shutil.copytree(os.environ['GH_ORIGIN'],path)
        print(json.dumps({'full_name':'fixture/'+fork}))
    elif endpoint.startswith('repos/fixture/'):
        if state.get('pending',0):
            state['pending']-=1
            Path(os.environ['GH_FIXTURE']).write_text(json.dumps(state))
            sys.exit(1)
        fork=endpoint.split('/')[2]
        name=next((name for name,value in state.get('fork_names',{}).items() if value==fork),fork)
        print(json.dumps({'fork':True,'parent':{'full_name':'storytold/'+name}}))
    else: raise RuntimeError(args)
elif args[:2]==['repo','clone']:
    if args[2].split('/')[1] in state.get('clone_fail',[]): sys.exit(1)
    subprocess.run(['git','clone','https://github.com/'+args[2]+'.git',args[3]],check=True)
else: raise RuntimeError(args)
'''


def repo(name, owner='storytold'):
    return {'name': name, 'owner': {'login': owner}}


class DiscoveryTests(CraftFixture):
    def setUp(self):
        super().setUp()
        self.remote_root = self.root / 'remotes'
        for group in ['upstreams', 'forks']:
            (self.remote_root / group).mkdir(parents=True)
        (self.remote_root / 'forks/photocraft.git').symlink_to(self.origin, target_is_directory=True)
        self.state = {'pages': [[repo('photocraft')]]}
        self.state_path = self.root / 'github.json'
        self.env.update(GH_FIXTURE=str(self.state_path), GH_FIXTURE_LOG=str(self.root / 'github-log.jsonl'),
                        GH_REMOTE_ROOT=str(self.remote_root), GH_ORIGIN=str(self.origin), GIT_CONFIG_COUNT='2',
                        GIT_CONFIG_KEY_0=f'url.{(self.remote_root / "upstreams").as_uri()}/.insteadOf',
                        GIT_CONFIG_VALUE_0='https://github.com/storytold/',
                        GIT_CONFIG_KEY_1=f'url.{(self.remote_root / "forks").as_uri()}/.insteadOf',
                        GIT_CONFIG_VALUE_1='https://github.com/fixture/')
        for remote, owner in [('upstream', 'storytold'), ('origin', 'fixture')]:
            self.git('-C', str(self.app), 'remote', 'set-url', remote, f'https://github.com/{owner}/photocraft.git')
        gh = self.bin / 'gh'
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)

    def pull(self, expected=0, *args):
        self.state_path.write_text(json.dumps(self.state))
        for page in self.state['pages']:
            for item in page:
                name = item['name']
                if '/' not in name:
                    link = self.remote_root / 'upstreams' / (name + '.git')
                    if not link.exists(): link.symlink_to(self.upstream, target_is_directory=True)
        return self.run_tool('pull', *args, expected=expected)

    def gh_calls(self):
        return [json.loads(line) for line in (self.root / 'github-log.jsonl').read_text().splitlines()]

    def test_later_pages_and_new_repositories_are_discovered(self):
        self.state['pages'] = [[repo(f'unrelated-{i}') for i in range(100)],
                               [repo('photocraft'), repo('newcraft'), repo('craft-new-assets')]]
        new = self.advance()
        self.pull()
        for name in ['photocraft', 'newcraft', 'craft-new-assets']:
            self.assertEqual(self.head(self.workspace / name), new)
        self.assertEqual(self.commands(), [])
        self.assertIn('--paginate', self.gh_calls()[0])
        self.assertIn('--slurp', self.gh_calls()[0])
        self.assertFalse((self.workspace / 'unrelated-0').exists())

    def test_empty_mixed_case_repository_is_retried_later(self):
        self.state['pages'][0].append(repo('AniCraft'))
        self.state['empty'] = ['AniCraft']
        self.assertIn('empty repository', self.pull().stdout)
        self.assertFalse((self.workspace / 'AniCraft').exists())
        self.state['empty'] = []
        self.pull()
        self.assertTrue((self.workspace / 'AniCraft/.git').is_dir())

    def test_existing_checkouts_are_reused_and_feature_branch_preserved(self):
        self.git('-C', str(self.app), 'switch', '-c', 'fix/mine')
        old = self.head(self.app)
        new = self.advance()
        self.pull()
        self.pull()
        self.assertEqual(self.head(self.app), old)
        self.assertEqual(self.head(self.app, 'main'), new)
        self.assertFalse(any(call[-1].endswith('/forks') for call in self.gh_calls()))

    def test_renamed_fork_is_supported(self):
        self.state['pages'][0].append(repo('newcraft'))
        self.state['fork_names'] = {'newcraft': 'my-renamed-craft'}
        self.pull()
        self.assertEqual(self.git('-C', str(self.workspace / 'newcraft'), 'config', '--get', 'remote.origin.url'),
                         'https://github.com/fixture/my-renamed-craft.git')

    def test_destination_collision_does_not_overwrite_and_other_repos_continue(self):
        self.state['pages'][0].extend([repo('newcraft'), repo('othercraft')])
        destination = self.workspace / 'newcraft'
        destination.mkdir()
        (destination / 'keep').write_text('user data')
        self.pull(1)
        self.assertEqual((destination / 'keep').read_text(), 'user data')
        self.assertTrue((self.workspace / 'othercraft/.git').is_dir())

    def test_wrong_upstream_is_not_changed_or_updated(self):
        self.git('-C', str(self.app), 'config', 'remote.upstream.url', 'https://github.com/other/photocraft.git')
        old = self.head(self.app)
        self.advance()
        self.pull(1)
        self.assertEqual(self.head(self.app), old)
        self.assertIn('upstream does not match', self.pull(1).stdout)

    def test_api_failure_does_not_fall_back_to_stale_inventory(self):
        self.state['api_fail'] = True
        old = self.head(self.app)
        self.advance()
        self.pull(1)
        self.assertEqual(self.head(self.app), old)

    def test_validate_all_pages_before_any_fork(self):
        self.state['pages'] = [[repo('newcraft')], [repo('othercraft', owner='unexpected')]]
        self.pull(1)
        self.assertFalse((self.workspace / 'newcraft').exists())
        self.assertEqual(len(self.gh_calls()), 1)

    def test_clone_failure_is_cleaned_up_and_retry_succeeds(self):
        self.state['pages'][0].append(repo('newcraft'))
        self.state['clone_fail'] = ['newcraft']
        self.pull(1)
        self.assertFalse((self.workspace / 'newcraft').exists())
        self.assertEqual(list((self.workspace / '.build').glob('clone-*')), [])
        self.state['clone_fail'] = []
        self.pull()
        self.assertTrue((self.workspace / 'newcraft/.git').exists())

    def test_no_push_preserves_existing_fork_default(self):
        old = self.head(self.origin, 'main')
        new = self.advance()
        self.pull(0, '--no-push')
        self.assertEqual(self.head(self.app), new)
        self.assertEqual(self.head(self.origin, 'main'), old)

    def test_fork_creation_waits_for_github_readiness(self):
        self.state['pages'][0].append(repo('newcraft'))
        self.state['pending'] = 1
        self.pull()
        self.assertTrue((self.workspace / 'newcraft/.git').exists())

    def test_symlink_destinations_are_not_followed(self):
        self.state['pages'][0].append(repo('newcraft'))
        target = self.root / 'user-folder'
        target.mkdir()
        (self.workspace / 'newcraft').symlink_to(target, target_is_directory=True)
        self.pull(1)
        self.assertEqual(list(target.iterdir()), [])

    def test_foreign_origin_is_not_changed_or_updated(self):
        self.git('-C', str(self.app), 'config', 'remote.origin.url', 'https://github.com/someone/photocraft.git')
        old = self.head(self.app)
        self.advance()
        self.pull(1)
        self.assertEqual(self.head(self.app), old)

    def test_pull_rejects_build_arguments(self):
        for args in [('--no-update',), ('--all',), ('--release',), ('photocraft',)]:
            self.run_tool('pull', *args, expected=2)
        self.assertFalse((self.workspace / '.logs').exists())
