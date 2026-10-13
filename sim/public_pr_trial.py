"""One public PR intake backed by a previously registered task and checker.

The current supported URL is deliberately narrow. An arbitrary PR has no
independent task or success criterion merely because GitHub can serve it.
"""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import re
import secrets
import subprocess
import json
from urllib.request import Request, urlopen

from sim import ROOT, tool_preflight, tool_trial, tool_workspace
from sim.scenario import git

URL = 'https://github.com/microsoft/markitdown/pull/2587'
HEAD = 'a86a2c499c43d3b3a285a6e3784962ded0b681a2'
BASE = '2b61a335a4bec721144498fe425a61f23e9e3d6e'
IMAGE = 'sha256:88e7e94776662aedfb92f3d9a51d0a030c7602832bd668fd37cb4637142693ad'


def canonical(url: str) -> str:
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError('Paste one public GitHub pull request URL.')
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)(?:/)?', url.strip())
    if not match:
        raise ValueError('Use a public GitHub pull request URL, without a query string or fragment.')
    return 'https://github.com/' + '/'.join(match.groups()[:2]) + '/pull/' + match.group(3)


def inspect(ws, body):
    """Classify one URL and reopen a retained result without fetching or running it."""
    url = canonical(body.get('url'))
    from sim import public_json_trial
    trials = ws.root / 'tools'
    if trials.exists():
        for path in sorted(trials.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            receipt = path / 'public-url.json'
            if not path.is_dir() or not receipt.exists():
                continue
            if tool_trial.read(receipt).get('url') != url:
                continue
            result = tool_workspace.result(ws, path.name)
            if result['state']['status'] == 'complete':
                return {'status': 'recorded_result', 'url': url, 'trial': result,
                        'reason': 'This workspace already has a completed comparison for this exact link. Reopening it makes no model request.'}
    if url == public_json_trial.URL:
        return {'status': 'registered_unrun', 'url': url,
                'reason': 'This exact PR has a frozen JSON Lines task and independent checker. This workspace has no completed agent result for it.'}
    if url == URL:
        return {'status': 'blocked_environment', 'url': url,
                'reason': 'This PR has a registered task, but its workbook dependencies exceed the current reviewed image boundary. No agent run is available for this link.'}
    from sim import pr_intake
    receipts = ws.root / 'public-pr-intakes'
    receipt = receipts / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    if receipt.exists():
        return tool_trial.read(receipt)
    result = pr_intake.inspect(url)
    if not result.get('reason', '').startswith(('RuntimeError:', 'TimeoutExpired:', 'CalledProcessError:', 'OSError:')):
        with ws.lock:
            receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
            tool_trial.dump(receipt, result)
    return result


def fetch_registered_source(destination: Path) -> None:
    destination.mkdir(parents=True, mode=0o700)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'}
    commands = [
        ['git', '-c', 'credential.helper=', 'init', '-q', str(destination)],
        ['git', '-c', 'credential.helper=', '-C', str(destination), 'fetch', '-q', '--depth=2',
         'https://github.com/microsoft/markitdown.git', 'pull/2587/head'],
    ]
    for command in commands:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=120, env=env)
    head = git(destination, 'rev-parse', 'FETCH_HEAD').decode().strip()
    base = git(destination, 'rev-parse', 'FETCH_HEAD^').decode().strip()
    if (base, head) != (BASE, HEAD):
        raise ValueError('The public PR changed since this task and checker were registered. No agent run was prepared.')


def public_metadata() -> dict:
    request = Request('https://api.github.com/repos/microsoft/markitdown/pulls/2587',
                      headers={'User-Agent': 'simulated-market-private-study',
                               'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    if payload.get('head', {}).get('sha') != HEAD or not isinstance(payload.get('title'), str):
        raise ValueError('The public PR title or head changed. No agent run was prepared.')
    return {'title': payload['title'], 'state': payload['state'], 'fetched_head': payload['head']['sha']}


def contract(source: Path, seed: int) -> dict:
    files = git(source, 'ls-tree', '-r', '--name-only', BASE).decode().splitlines()
    files = [name for name in files if name.startswith('packages/markitdown/src/') or name in
             ('README.md', 'LICENSE', 'packages/markitdown/pyproject.toml')]
    fixture_ref = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    return {'version': 1, 'name': 'MarkItDown public PR: release handoff', 'repo': str(source),
            'base': BASE, 'head': HEAD, 'files': files, 'discovery': 'README.md', 'image': IMAGE,
            'setup': ['python3 studies/markitdown-handoff/materialize.py'],
            'command': ['env', 'PYTHONPATH=/work/packages/markitdown/src', 'python3', '-m', 'markitdown'],
            'task': ('Convert the synthetic release handoff workbook at /work/release-handoff.xlsx '
                     'to a Markdown table using the supplied CLI. Preserve all four ticket IDs, owners, '
                     'instructions, due-day counts and artifact names, including the literal path. '
                     'The separate controller checks registered CLI output, not final prose.'),
            'check': {'repo': str(ROOT), 'ref': fixture_ref,
                      'path': 'studies/markitdown-handoff/check.py'},
            'fixtures': {'repo': str(ROOT), 'ref': fixture_ref,
                         'files': ['studies/markitdown-handoff/materialize.py']},
            'budget': 8, 'seeds': [seed], 'initial_choice': 'defer'}


def prepare(ws, body):
    url = canonical(body.get('url'))
    from sim import public_json_trial
    if url == public_json_trial.URL:
        return public_json_trial.prepare(ws, url)
    if url != URL:
        raise ValueError('This PR has no registered task and independent checker yet. Try '+URL+' or '+public_json_trial.URL)
    with ws.lock:
        identity = secrets.token_hex(12)
        source = ws.root / 'public-pr-sources' / identity
        metadata = public_metadata()
        fetch_registered_source(source)
        frozen = tool_trial.prepare(contract(source, secrets.randbelow(2**31)),
                                    tool_workspace.directory(ws, identity))
        path = tool_workspace.directory(ws, identity)
        tool_trial.dump(path / 'public-url.json', {'url': url, 'base': BASE, 'head': HEAD,
                        'title': metadata['title'], 'pr_state': metadata['state'],
                        'source': str(source), 'scope': 'Live public Git fetch; task and checker were registered before this intake.'})
    cases = [
        {'kind': 'valid', 'label': 'Documented XLSX conversion',
         'reason': 'The task names this workbook and accepts the documented extension hint.',
         'args': ['-x', 'xlsx', '/work/release-handoff.xlsx'],
         'expected': {'base': True, 'head': True}},
        {'kind': 'wrong', 'label': 'Wrong workbook path',
         'reason': 'A different workbook cannot satisfy the registered source-bound task.',
         'args': ['-x', 'xlsx', '/work/not-the-handoff.xlsx'],
         'expected': {'base': False, 'head': False}},
    ]
    tool_preflight.prepare(ws, {'id': identity, 'expected': frozen['sha256'],
                                'policy': 'tokenfactory-shell-agent', 'cases': cases})
    return tool_workspace.result(ws, identity)
