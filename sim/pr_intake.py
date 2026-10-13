"""Conservative, zero-provider-cost intake for a public GitHub Python PR.

The PR's own tests are a candidate check, not independent proof by themselves.
Only a test that fails on the merge base and passes on the PR head is offered
as an executable regression check. All untrusted code runs in networkless Docker.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sim.public_pr_trial import canonical
from sim.hosted_cost import worst_case

# Reviewed offline test image: pinned Python plus pytest and pretend. Rebuild
# from studies/nvidia-distinct-batch/Dockerfile.pr-intake before this path runs.
IMAGE = 'sha256:476a386635d2cee2566d58bab5590288b613695e69f96541a22248844dc30b1a'
PRIVATE_ROOT = Path.home() / '.local/state/sim-provider/pr-intake-temp'
URL_PARTS = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)')
TEST_NAME = re.compile(r'(?:test_[A-Za-z0-9_]+|[A-Za-z0-9_]+_test)\.py$')


def is_python_test(path):
    # Real repositories nest tests below package and suite directories, e.g.
    # CPython Lib/test/test_json/test_tool.py. A fixed depth misses them.
    return bool(TEST_NAME.fullmatch(Path(path).name))


def command(argv, *, timeout=90, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          check=False)


def github(path):
    request = Request('https://api.github.com/' + path,
                      headers={'Accept': 'application/vnd.github+json',
                               'User-Agent': 'nvidia-public-pr-intake'})
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code != 403 or error.headers.get('X-RateLimit-Remaining') != '0':
            raise RuntimeError('Public GitHub API returned HTTP ' + str(error.code)) from error
    # The local operator may use gh for public API rate-limit headroom. A 404,
    # including a private repository, never falls back to authenticated access.
    result = command(['gh', 'api', path], timeout=30)
    if result.returncode:
        raise RuntimeError('Public GitHub API rate limit; authenticated fallback unavailable.')
    return json.loads(result.stdout)


def metadata(url):
    url = canonical(url)
    owner, repo, number = URL_PARTS.fullmatch(url).groups()
    prefix = f'repos/{owner}/{repo}'
    pr = github(f'{prefix}/pulls/{number}')
    if ((pr.get('base', {}).get('repo') or {}).get('private') or
            (pr.get('head', {}).get('repo') or {}).get('private')):
        return {'status': 'unsupported', 'url': url,
                'reason': 'Private repositories need a separate authorized GitHub connection.'}
    if not pr.get('merged_at'):
        return {'status': 'unsupported', 'url': url, 'reason': 'PR is not merged.'}
    files = github(f'{prefix}/pulls/{number}/files?per_page=100')
    if len(files) == 100 or pr.get('changed_files', 0) > 100:
        return {'status': 'unsupported', 'url': url, 'reason': 'PR has more than 100 changed files.'}
    tests = [f['filename'] for f in files if f.get('status') != 'removed' and
             is_python_test(f.get('filename', ''))]
    source = [f['filename'] for f in files if f.get('filename', '').endswith('.py') and
              f['filename'] not in tests]
    base_tip = pr['base']['sha']
    pull_head = pr['head']['sha']
    merge_commit = pr.get('merge_commit_sha')
    result = {'status': 'candidate' if tests and source else 'unsupported', 'url': url,
              'title': pr['title'], 'owner': owner, 'repo': repo, 'number': int(number),
              'current_base_tip': base_tip, 'pull_head': pull_head,
              'merge_commit': merge_commit, 'pull_commits': pr.get('commits'),
              'tests': tests, 'source_files': source,
              'changed_files': pr['changed_files'], 'merged_at': pr['merged_at'],
              'image': IMAGE}
    missing_check = result['status'] == 'unsupported'
    if not merge_commit or not re.fullmatch('[0-9a-f]{40}', merge_commit):
        result.update(status='unsupported', reason='Could not pin the merged commit.')
        return result
    merged = github(f'{prefix}/commits/{merge_commit}')
    parents = [row['sha'] for row in merged.get('parents', [])]
    if not parents:
        result.update(status='unsupported', reason='Merged commit has no before parent.')
        return result
    if len(parents) == 1 and pr.get('commits', 0) != 1:
        pull_patches = {item['filename']: item.get('patch') for item in files}
        merged_patches = {item['filename']: item.get('patch') for item in merged.get('files', [])}
        if (not pull_patches or any(patch is None for patch in pull_patches.values()) or
                pull_patches != merged_patches):
            result.update(status='unsupported', reason='Multi-commit merge does not match the full PR patch.')
            return result
        result['multi_commit_pin_check'] = 'All changed file patches match the merged commit.'
    result['base'] = parents[0]
    result['head'] = merge_commit
    result['pin_basis'] = 'first parent of actual merged commit versus merged commit'
    if missing_check:
        result['reason'] = 'No changed Python source plus added or modified Python test file.'
    return result


def fetch_pair(info, folder):
    source = folder / 'source'
    source.mkdir()
    remote = f"https://github.com/{info['owner']}/{info['repo']}.git"
    init = command(['git', 'init', '-q', str(source)])
    if init.returncode:
        raise RuntimeError(init.stderr[:300])
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1')
    for sha in (info['base'], info['head']):
        fetched = subprocess.run(['git', '-c', 'credential.helper=', '-C', str(source),
                                  'fetch', '-q', '--depth=2', remote, sha],
                                 capture_output=True, text=True, timeout=120, env=env)
        if fetched.returncode:
            raise RuntimeError('Pinned commit unavailable: ' + fetched.stderr[:300])
    for label in ('base', 'head'):
        sha = info[label]
        checkout = folder / label
        checkout.mkdir()
        archive = subprocess.run(['git', '-C', str(source), 'archive', sha],
                                 capture_output=True, check=True, timeout=60).stdout
        if len(archive) > 35_000_000:
            raise RuntimeError('Pinned source exceeds the 35 MB archive gate.')
        total = 0
        with tarfile.open(fileobj=io.BytesIO(archive)) as listing:
            members = listing.getmembers()
            if len(members) > 1000:
                raise RuntimeError('Pinned source exceeds the 1000-file image gate.')
            for member in members:
                path = member.name.rstrip('/')
                if (not (member.isfile() or member.isdir()) or
                        any(not re.fullmatch(r'[A-Za-z0-9_.+@-]+', part) or part in ('.', '..')
                            for part in path.split('/'))):
                    raise RuntimeError('Pinned source has an unsupported file type or path.')
                if member.isdir():
                    continue
                total += member.size
                if total > 30_000_000 or member.size > 5_000_000:
                    raise RuntimeError('Pinned source exceeds the 30 MB image gate.')
                destination = checkout / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with listing.extractfile(member) as stream:
                    destination.write_bytes(stream.read())
    return folder / 'base', folder / 'head'


def run_control(tree, test_path):
    # Run the changed test file with the framework used by most sampled repos.
    # A zero-test exit cannot satisfy the control even if pytest exits zero.
    args = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--pids-limit', '64', '--memory', '512m', '--cpus', '1',
            '--user', '65534:65534', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
            '-v', f'{tree}:/work:ro', '-w', '/work', '-e', 'PYTHONDONTWRITEBYTECODE=1',
            '-e', 'PYTHONPATH=/work:/work/src',
            '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', IMAGE,
            'python3', '-m', 'pytest', '-q', '--disable-warnings', '--tb=short', test_path]
    try:
        result = command(args, timeout=65)
    except subprocess.TimeoutExpired:
        return {'passed': False, 'tests_run': 0, 'exit': 124, 'output': 'Control timed out.'}
    output = (result.stdout + result.stderr)[-8000:]
    count = sum(int(value) for value in re.findall(r'(\d+) (?:passed|failed|errors?|skipped|xfailed|xpassed)', output))
    return {'passed': result.returncode == 0 and count > 0,
            'tests_run': count, 'exit': result.returncode, 'output': output}


def inspect(url, *, retain=None):
    info = metadata(url)
    if info['status'] != 'candidate':
        return info
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(retain) if retain else Path(tempfile.mkdtemp(prefix='nvidia-pr-intake-', dir=PRIVATE_ROOT))
    root.mkdir(parents=True, exist_ok=True)
    try:
        base, head = fetch_pair(info, root)
        # The head test is held identical on both versions. It is never copied
        # from the base, because a test introduced by the PR would be absent.
        selected = info['tests'][0]
        head_test = head / selected
        if not head_test.is_file() or head_test.is_symlink():
            return {**info, 'status': 'unsupported', 'reason': 'Selected head test is unavailable.'}
        destination = base / selected
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(head_test, destination)
        valid_base = run_control(base, selected)
        valid_head = run_control(head, selected)
        wrong_path = '__nvidia_absent_test__.py'
        wrong_base = run_control(base, wrong_path)
        wrong_head = run_control(head, wrong_path)
        # unittest-discover missing-pattern normally exits 0 with zero tests;
        # our pass predicate rejects it. All four outcomes must be observed.
        controls = {'base_valid': valid_base, 'head_valid': valid_head,
                    'base_wrong': wrong_base, 'head_wrong': wrong_head}
        base_assertion_failure = bool(re.search(r'[1-9][0-9]* failed', valid_base['output'])) and not re.search(
            r'[1-9][0-9]* errors?', valid_base['output'])
        supported = (not valid_base['passed'] and valid_head['passed'] and
                     valid_base['tests_run'] > 0 and valid_head['tests_run'] > 0 and
                     base_assertion_failure and
                     not wrong_base['passed'] and not wrong_head['passed'])
        return {**info, 'status': 'supported_check' if supported else 'unsupported',
                'selected_test': selected, 'controls': controls,
                'reason': ('PR head test passes on head and fails on merge base.' if supported else
                           'Four control outcomes do not establish a runnable regression check.'),
                'scope': 'Automatic regression check candidate; agent task and independence still need review.',
                'estimated_20_attempt_reservation_usd': float(worst_case(160))}
    except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            tarfile.TarError, OSError) as error:
        return {**info, 'status': 'unsupported', 'reason': type(error).__name__ + ': ' + str(error)[:300]}
    finally:
        if not retain:
            shutil.rmtree(root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description='Zero-cost public PR intake')
    parser.add_argument('url')
    parser.add_argument('--retain', type=Path, help='Private folder for pinned source and controls')
    args = parser.parse_args()
    result = inspect(args.url, retain=args.retain)
    if args.retain:
        (args.retain / 'intake.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
