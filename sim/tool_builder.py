"""Read-only discovery for the private tool-trial builder. No fetching or execution."""
import json
from pathlib import Path

from sim.scenario import git, revision, safe_member
from sim.standins.docker_sandbox import _docker


def source(body):
    raw = body.get('repo')
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Enter a local Git repository path.')
    repo = Path(raw).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError('Choose an existing local repository. Remote URLs are not supported.')
    root = Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    refs = git(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/tags').decode().splitlines()
    commits = {}
    trees = {}
    unsafe = set()
    for arm in ('base', 'head'):
        ref = body.get(arm, 'HEAD')
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError('Choose a committed ref for each version.')
        commit = revision(root, ref)
        commits[arm] = commit
        tree = {}
        for entry in git(root, 'ls-tree', '-r', '-z', commit).split(b'\0'):
            if not entry:
                continue
            info, name = entry.split(b'\t', 1)
            mode, kind, oid = info.split()
            path = name.decode()
            if mode in (b'100644', b'100755') and kind == b'blob' and safe_member(path):
                tree[path] = oid.decode()
            else:
                unsafe.add(path)
        trees[arm] = tree
    names = sorted(set(trees['base']) | set(trees['head']))
    return {'repo': str(root), 'refs': refs, 'commits': commits,
            'files': [{'path': name, 'available': name not in unsafe,
                       'presence': {arm: name in tree for arm, tree in trees.items()},
                       'changed': trees['base'].get(name) != trees['head'].get(name)} for name in names],
            'scope': 'Committed regular files only. Working-tree edits, ignored files, symlinks and submodules are excluded.'}


def images(body):
    rows = _docker('image', 'ls', '--no-trunc', '--format', '{{json .}}').stdout.decode().splitlines()
    found = {}
    for raw in rows:
        row = json.loads(raw)
        identity = row['ID']
        if not identity.startswith('sha256:'):
            continue
        name = row['Repository'] + ':' + row['Tag']
        found.setdefault(identity, {'id': identity, 'names': []})
        if name != '<none>:<none>':
            found[identity]['names'].append(name)
    return {'images': sorted(found.values(), key=lambda row: (row['names'], row['id'])),
            'scope': 'Already cached local Docker images. No pull or remote lookup.'}
