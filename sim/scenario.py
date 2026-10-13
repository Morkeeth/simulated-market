"""Explicit offline source scenarios. User code only executes inside networkless Docker."""
from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from sim.doc import Target, sha256_bytes
from sim.standins.docker_sandbox import DockerSandbox, DockerUnavailable, Fork, _docker


def git(repo, *args) -> bytes:
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    if p.returncode:
        raise ValueError('Git input could not be read: ' + p.stderr.decode(errors='replace').strip()[:300])
    return p.stdout


def revision(repo, ref):
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()


def safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '.git' not in p.parts


def load_contract(path):
    doc = json.loads(Path(path).read_text())
    keys = {'version', 'name', 'source', 'image', 'setup', 'goal', 'steps'}
    if not isinstance(doc, dict) or set(doc) not in (keys, keys | {'image_review'}) or type(doc['version']) is not int or doc['version'] != 1:
        raise ValueError('Scenario requires version:1, name, source, image, setup, goal, steps; image_review is optional.')
    for k in ('name', 'image', 'goal'):
        if not isinstance(doc[k], str) or not doc[k].strip():
            raise ValueError(f'Scenario {k} must be a nonempty string.')
    if 'image_review' in doc and not isinstance(doc['image_review'], str):
        raise ValueError('image_review must name an explicit review manifest file.')
    src = doc['source']
    if not isinstance(src, dict) or set(src) != {'repo', 'ref', 'files'}:
        raise ValueError('source requires repo, ref and an explicit files allowlist.')
    if not all(isinstance(src[k], str) and src[k] for k in ('repo', 'ref')):
        raise ValueError('source repo/ref must be nonempty strings.')
    if not isinstance(src['files'], list) or not src['files'] or not all(isinstance(x, str) and safe_member(x) for x in src['files']):
        raise ValueError('source files must be safe relative paths, without .git or traversal.')
    if not isinstance(doc['setup'], list) or not all(isinstance(x, str) and x.strip() for x in doc['setup']):
        raise ValueError('setup must be a list of shell commands (empty is allowed).')
    steps = doc['steps']
    if not isinstance(steps, list) or not steps:
        raise ValueError('steps must contain at least one ordered success check.')
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'id', 'title', 'probe'} or not all(isinstance(v, str) and v.strip() for v in step.values()):
            raise ValueError('Each step requires nonempty id, title and probe strings.')
    if len({s['id'] for s in steps}) != len(steps):
        raise ValueError('Step ids must be unique.')
    return doc


def freeze(path, output, backend="local", image_id=None):
    """Read one immutable Git commit, never the live checkout or ignored files."""
    contract = load_contract(path)
    repo = (Path(path).resolve().parent / contract['source']['repo']).resolve()
    commit = revision(repo, contract['source']['ref'])
    names = contract['source']['files']
    blobs = {}
    entries = git(repo, 'ls-tree', '-r', '-z', commit).split(b'\0')
    tree = {}
    for entry in entries:
        if not entry:
            continue
        info, name = entry.split(b'\t', 1)
        mode, kind, oid = info.split()
        tree[name.decode()] = (mode, kind, oid.decode())
    for name in names:
        if name not in tree or tree[name][0] not in (b'100644', b'100755') or tree[name][1] != b'blob':
            raise ValueError(f'Source must name committed regular files explicitly: {name}')
        blobs[name] = git(repo, 'cat-file', 'blob', tree[name][2])
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in sorted(blobs.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), int(tree[name][0], 8), 0
            archive.addfile(info, io.BytesIO(data))
    source = stream.getvalue()
    contract['source'] = {'commit': commit, 'files': {k: sha256_bytes(v) for k, v in sorted(blobs.items())},
                          'archive': 'source.tar', 'sha256': sha256_bytes(source)}
    # Resolve the image once; no pull or mutable tag can alter the three arms.
    if backend == 'sponsor':
        from uuid import UUID
        try:
            contract['image_id'] = str(UUID(image_id or ''))
        except ValueError:
            raise ValueError('Set NEBIUS_SANDBOX_IMAGE to an existing Python sandbox image UUID before preview.') from None
        contract['image'] = contract['image_id']
    elif backend == 'local':
        image = _docker('image', 'inspect', contract['image'], '--format', '{{.Id}}', check=False)
        if image.returncode:
            raise DockerUnavailable('Scenario image is not cached. No image was downloaded.')
        contract['image_id'] = image.stdout.decode().strip()
    else:
        raise ValueError('Choose local or sponsor backend.')
    if 'image_review' in contract:
        review_path = (Path(path).resolve().parent / contract['image_review']).resolve()
        if not review_path.is_file() or review_path.stat().st_size > 2_000_000:
            raise ValueError('Choose an image review manifest under 2 MB.')
        contract['image_review'] = json.loads(review_path.read_text())
    raw = (json.dumps(contract, sort_keys=True, indent=2) + '\n').encode()
    (output / 'scenario.json').write_bytes(raw)
    (output / 'source.tar').write_bytes(source)
    meta = {'name': contract['name'], 'goal': contract['goal'], 'app_marker': 'SCENARIO_USES_EXPLICIT_PROBES',
            'doc_url': 'inputs.json', 'doc_commit': commit, 'section_start': 'Complete supplied document',
            'scenario': {'file': 'scenario.json', 'sha256': sha256_bytes(raw)},
            'steps': [{**s, 'check': s['probe']} for s in contract['steps']]}
    return Target(output, meta), contract


class ScenarioSandbox(DockerSandbox):
    RECIPE_LABEL = 'com.simulated-market.recipe'

    def __init__(self, contract, output):
        self.contract, self.output = contract, output
        self._checkpoint = None
        self._recipe = None
        self._recipe_key = None

    def checkpoint_target(self, target):
        recipe = {'scenario_sha256': target.meta['scenario']['sha256'],
                  'source_sha256': self.contract['source']['sha256'],
                  'base_id': self.contract['image_id'], 'workdir': '/work', 'network': 'none',
                  'source_boundary': 'empty-workdir-and-no-credential-env-v1'}
        # A source allowlist cannot account for private data inherited from an image.
        # Never print environment values. The immutable base id binds this check.
        env = json.loads(_docker('image', 'inspect', self.contract['image_id'],
                                '--format', '{{json .Config.Env}}').stdout)
        if env is not None and not isinstance(env, list):
            raise ValueError('Cannot inspect base image environment.')
        credential_names = []
        for entry in env or []:
            name, _, value = entry.partition('=')
            if value and re.search(r'TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|CREDENTIAL', name, re.I):
                credential_names.append(name)
        if credential_names:
            raise ValueError('Base image contains credential-like environment names; use a clean image: '
                             + ', '.join(sorted(credential_names)))
        key = self.recipe_sha(recipe)
        if self._checkpoint is not None:
            if key != self._recipe_key:
                raise ValueError('This comparison already froze a different scenario checkpoint.')
            return self._checkpoint, dict(self._recipe)
        # A tag is only a cache lookup. Resolve it once, then never use it for a fork.
        # The label catches accidental stale/wrong entries, not a hostile Docker daemon.
        tag = 'simmarket-scenario-v2:' + key[:16]
        cached = _docker('image', 'inspect', tag, check=False)
        if cached.returncode == 0:
            obj = json.loads(cached.stdout)[0]
            if (obj.get('Config', {}).get('Labels') or {}).get(self.RECIPE_LABEL) != key:
                raise ValueError('Cached checkpoint recipe label does not match; refusing cache tag.')
            image_id = obj['Id']
        else:
            import secrets
            name = 'simmarket-build-' + secrets.token_hex(8)
            _docker('run', '--pull', 'never', '-d', '--network', 'none', '--name', name,
                    self.contract['image_id'], 'sleep', 'infinity')
            try:
                # Refuse inherited task state before staging or running setup.
                _docker('exec', name, 'python', '-I', '-c',
                        "from pathlib import Path; p=Path('/work'); "
                        "assert not p.is_symlink(), 'base /work must not be a symlink'; "
                        "assert not p.exists() or (p.is_dir() and not any(p.iterdir())), 'base /work must be empty'")
                _docker('exec', name, 'mkdir', '-p', '/work')
                _docker('cp', '-', name + ':/work', input=(self.output / 'source.tar').read_bytes())
                for command in self.contract['setup']:
                    _docker('exec', '-w', '/work', '-e', 'PIP_NO_INDEX=1', name, 'bash', '-c', command)
                built = _docker('commit', '--change', 'WORKDIR /work', '--change', 'ENV PIP_NO_INDEX=1',
                        '--change', 'ENV PYTHONDONTWRITEBYTECODE=1',
                        '--change', f'LABEL {self.RECIPE_LABEL}={key}', name, tag)
                # docker commit returns the exact newly created image id, avoiding a tag lookup race.
                image_id = built.stdout.decode().strip()
            finally:
                _docker('rm', '-f', name, check=False)
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
            raise ValueError('Docker did not return an immutable checkpoint image id.')
        recipe['checkpoint_image_id'] = image_id
        self._checkpoint, self._recipe, self._recipe_key = image_id, recipe, key
        return image_id, dict(recipe)

    def fork(self, checkpoint, name):
        if self._checkpoint is None or checkpoint != self._checkpoint:
            raise ValueError('Fork must use this comparison’s frozen checkpoint image id.')
        _docker('run', '--pull', 'never', '-d', '--rm', '--network', 'none', '--name', name,
                self._checkpoint, 'sleep', 'infinity')
        return Fork(name)


class NoGrounding:
    name = 'none-requested'
    items_source = 'no grounding sources requested for this scenario'
    label = 'LOCAL-FIXTURE'
    def items(self): return []
    def for_topic(self, topic): return None
    def record(self, query, receipts_path=None): return None
