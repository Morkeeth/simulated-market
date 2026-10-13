"""Explicit scenario authoring: read committed source, save only in private storage."""
from pathlib import Path
import secrets
from sim.scenario import git, revision, safe_member, load_contract


def source(body):
    if not isinstance(body.get('repo'), str) or not body['repo'].strip():
        raise ValueError('Choose a local Git repository.')
    if not isinstance(body.get('ref'), str) or not body['ref'].strip():
        raise ValueError('Choose an existing source revision.')
    repo = Path(body['repo']).expanduser().resolve()
    commit = revision(repo, body['ref'])
    files = []
    for entry in git(repo, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not entry: continue
        meta, name = entry.split(b'\t', 1)
        mode, kind, oid = meta.split()
        name = name.decode()
        if mode in (b'100644', b'100755') and kind == b'blob' and safe_member(name):
            files.append(name)
    if len(files) > 10000:
        raise ValueError('This repository has more than 10000 source files. Use an existing explicit scenario for this project.')
    return {'repo': str(repo), 'commit': commit, 'files': files}


def create(ws, body):
    from sim.workspace import save
    with ws.lock:
        contract = body.get('contract')
        if not isinstance(contract, dict) or not isinstance(contract.get('source'), dict):
            raise ValueError('Supply the explicit project, task, setup and success checks.')
        selected = source({'repo': contract['source'].get('repo'), 'ref': contract['source'].get('ref')})
        # New unique file under this workspace, never a browser-chosen output path.
        directory = ws.root / 'scenarios'; directory.mkdir(exist_ok=True, mode=0o700)
        path = directory / (secrets.token_hex(12) + '.json')
        contract = {**contract, 'source': {**contract['source'], 'repo': selected['repo'], 'ref': selected['commit']}}
        try:
            save(path, contract)
            load_contract(path)
            if any(name not in selected['files'] for name in contract['source']['files']):
                raise ValueError('Select only committed regular source files from the inspected revision.')
            if len(set(contract['source']['files'])) != len(contract['source']['files']):
                raise ValueError('Select each source file once.')
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {'path': str(path), 'contract': contract}
