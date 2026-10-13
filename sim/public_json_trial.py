"""Registered public CPython JSON Lines PR, with task and checker frozen locally."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess

from sim import ROOT, tool_preflight, tool_trial, tool_workspace
from sim.image_review import SUPPORTED_IMAGE
from sim.scenario import git

URL = 'https://github.com/python/cpython/pull/29858'
BASE = '634cb61909b1392f0eef3e749931777adb54f16e'
HEAD = 'c8ebbd89d6a661e44b8b50ac256151ddb0334d07'
PATHS = ['Lib/json/tool.py', 'Lib/test/test_json/test_tool.py',
         'Misc/NEWS.d/next/Library/2021-11-30-07-15-32.bpo-45929.EeKtTK.rst']
ARTIFACT = '/agent/answer.jsonl'
TASK = ('Create /agent/answer.jsonl from /work/events.jsonl for a deployment handoff. '
        'Keep every nonblank event in its original order. Each event line must be compact '
        'valid JSON; blank separator lines may remain. You may use the supplied CLI or your '
        'own shell method. The controller checks the final file, not your final prose.')


def public_metadata() -> dict:
    from sim.pr_intake import github
    pr = github('repos/python/cpython/pulls/29858')
    commit = github('repos/python/cpython/commits/' + HEAD)
    parents = [item['sha'] for item in commit['parents']]
    if pr.get('head', {}).get('sha') != HEAD or BASE not in parents or not isinstance(pr.get('title'), str):
        raise ValueError('The public PR identity changed. No agent run was prepared.')
    return {'title': pr['title'], 'state': pr['state'], 'head': HEAD, 'parents': parents}


def fetch_source(destination: Path) -> None:
    destination.mkdir(parents=True, mode=0o700)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'}
    commands = [['git', '-c', 'credential.helper=', 'init', '-q', str(destination)]]
    for ref in (BASE, HEAD):
        commands.append(['git', '-c', 'credential.helper=', '-C', str(destination), 'fetch', '-q',
                         '--depth=1', '--filter=blob:none', 'https://github.com/python/cpython.git', ref])
    for command in commands:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=120, env=env)
    for ref in (BASE, HEAD):
        if git(destination, 'rev-parse', ref + '^{commit}').decode().strip() != ref:
            raise ValueError('Fetched Git commit identity differs from the registered PR.')
    changed = git(destination, 'diff', '--name-only', BASE, HEAD).decode().splitlines()
    if changed != sorted(PATHS):
        raise ValueError('The public PR file diff differs from its registered three paths.')


def contract(source: Path, seed: int) -> dict:
    fixture_ref = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    folder = 'studies/cpython-jsonlines-handoff/'
    return {'version': 1, 'name': 'CPython public PR: JSON Lines handoff',
            'repo': str(source), 'base': BASE, 'head': HEAD, 'files': PATHS,
            'discovery': folder+'DISCOVERY.md', 'image': SUPPORTED_IMAGE,
            'setup': ['python3 '+folder+'materialize.py'],
            'command': ['python3', '/work/Lib/json/tool.py'],
            'task': TASK,
            'artifact': ARTIFACT,
            'check': {'repo': str(ROOT), 'ref': fixture_ref, 'path': folder+'check.py'},
            'fixtures': {'repo': str(ROOT), 'ref': fixture_ref,
                         'files': [folder+'materialize.py', folder+'DISCOVERY.md']},
            'budget': 8, 'seeds': [seed], 'initial_choice': 'defer'}


def prepare(ws, url: str):
    if url != URL:
        raise ValueError('This public PR has no registered task and checker.')
    with ws.lock:
        identity = secrets.token_hex(12)
        source = ws.root / 'public-pr-sources' / identity
        metadata = public_metadata()
        fetch_source(source)
        path = tool_workspace.directory(ws, identity)
        frozen = tool_trial.prepare(contract(source, secrets.randbelow(2**31)), path)
        tool_trial.dump(path/'public-url.json',
                        {'url': url, 'base': BASE, 'head': HEAD, 'title': metadata['title'],
                         'pr_state': metadata['state'], 'source': str(source),
                         'scope': 'Public pinned source, task and checker frozen before inference.'})
    cases = [
        {'kind': 'valid', 'label': 'Complete deployment-event handoff',
         'reason': 'The registered source file contains all three events and one blank separator.',
         'args': ['--json-lines', '--compact', '/work/events.jsonl'],
         'expected': {'base': False, 'head': True}},
        {'kind': 'wrong', 'label': 'Missing event source',
         'reason': 'A different or missing file cannot satisfy the registered handoff.',
         'args': ['--json-lines', '--compact', '/work/missing.jsonl'],
         'expected': {'base': False, 'head': False}},
    ]
    tool_preflight.prepare(ws, {'id': identity, 'expected': frozen['sha256'],
                                'policy': 'tokenfactory-shell-agent', 'cases': cases})
    return tool_workspace.result(ws, identity)
