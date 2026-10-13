"""Private reviewed snapshots consumed by the existing comparison engine."""
from __future__ import annotations
import json
import shutil
import sys
import os
from pathlib import Path
from sim import ROOT
from sim.doc import Target, sha256_bytes
from sim.run import dumps

FILES = ('scenario.json', 'source.tar', 'base.md', 'head.md', 'inputs.json')


def engine_identity():
    # Only the tool's own fixed source areas, never a user's project or environment files.
    files = sorted([*ROOT.glob('sim/**/*.py'), *ROOT.glob('schema/*.json')])
    return {'python': sys.version, 'local_model': os.environ.get('SIM_LOCAL_MODEL', 'mlx-community/Qwen2.5-7B-Instruct-4bit'),
            'files': {str(p.relative_to(ROOT)): sha256_bytes(p.read_bytes()) for p in files}}


def seal(directory, config):
    manifest = {'version': 1, 'config': config, 'engine': engine_identity(),
                'files': {name: sha256_bytes((directory / name).read_bytes()) for name in FILES}}
    raw = dumps(manifest).encode()
    (directory / 'manifest.json').write_bytes(raw)
    return sha256_bytes(raw)


def verify(directory, expected):
    directory = Path(directory)
    raw = (directory / 'manifest.json').read_bytes()
    if not expected or sha256_bytes(raw) != expected:
        raise ValueError('Preview changed. Prepare and inspect a new snapshot before running.')
    manifest = json.loads(raw)
    if manifest.get('version') != 1 or set(manifest.get('files', {})) != set(FILES):
        raise ValueError('Unsupported prepared comparison.')
    for name, digest in manifest['files'].items():
        if (directory / name).is_symlink() or sha256_bytes((directory / name).read_bytes()) != digest:
            raise ValueError('Prepared inputs changed. Prepare a new snapshot before running.')
    if manifest.get('engine') != engine_identity():
        raise ValueError('Comparison code or runtime changed since preview. Prepare a new snapshot.')
    config = manifest['config']
    basic = {'n', 'agents', 'seed'}
    if (set(config) not in (basic, basic | {'backend', 'sponsor'})
            or any(type(config[k]) is not int for k in basic)
            or not 1 <= config['n'] <= 200 or not 0 <= config['agents'] <= 8):
        raise ValueError('Unsupported population config.')
    if 'backend' in config:
        from uuid import UUID
        if (config['backend'] not in ('sponsor', 'tokenfactory-local')
                or set(config['sponsor']) != ({'model', 'image'} if config['backend'] == 'sponsor' else {'model'})):
            raise ValueError('Unsupported sponsor config.')
        if not isinstance(config['sponsor']['model'], str) or not config['sponsor']['model'].strip():
            raise ValueError('Missing sponsor model.')
        if config['backend'] == 'sponsor': UUID(config['sponsor']['image'])
    return manifest


def restore(directory, expected, output):
    directory, output = Path(directory), Path(output)
    manifest = verify(directory, expected)
    if output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Output must stay outside the tool checkout.')
    output.mkdir(parents=True, exist_ok=False)
    for name in (*FILES, 'manifest.json'):
        shutil.copyfile(directory / name, output / name)
    # Validate the exact copied bytes, not just a prior read of the source files.
    verify(output, expected)
    contract = json.loads((output / 'scenario.json').read_text())
    sources = json.loads((output / 'inputs.json').read_text())
    meta = {'name': contract['name'], 'goal': contract['goal'], 'app_marker': 'SCENARIO_USES_EXPLICIT_PROBES',
            'doc_url': 'inputs.json', 'doc_commit': contract['source']['commit'],
            'section_start': 'Complete supplied document',
            'scenario': {'file': 'scenario.json', 'sha256': manifest['files']['scenario.json']},
            'steps': [{**s, 'check': s['probe']} for s in contract['steps']]}
    inputs = [((output / (name + '.md')).read_bytes(), sources[name]) for name in ('base', 'head')]
    return Target(output, meta), contract, inputs, sources, manifest['config']
