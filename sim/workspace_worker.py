"""One durable background job, invoking only the existing comparison entrypoint."""
import json
import os
from pathlib import Path
import subprocess
import sys
from sim import ROOT
from sim.doc import sha256_bytes
from sim.run import dumps
from sim.workspace import save
from sim.validate import check, semantic
from sim.workspace_snapshot import verify
from sim.counterfactual import delta as compute_delta

RESULT_FILES = ('base.json', 'control.json', 'head.json', 'delta.json', 'REPORT.md',
                'checkpoint.json', 'scenario.json', 'inputs.json', 'base.md', 'head.md', 'source.tar', 'manifest.json')


def result_files(directory):
    job = json.loads((directory / 'job.json').read_text())
    return RESULT_FILES + (('services.jsonl',) if job['config'].get('backend') in ('sponsor', 'tokenfactory-local') else ())


def result_seal(directory):
    out = directory / 'result'
    job = json.loads((directory / 'job.json').read_text())
    manifest = verify(out, job['expected'])
    if manifest['config'] != job['config']: raise ValueError('Run config differs from reviewed job.')
    if manifest['config'].get('backend') in ('sponsor', 'tokenfactory-local'):
        model = manifest['config']['sponsor']['model']
        records = [json.loads(line) for line in (out / 'services.jsonl').read_text().splitlines()]
        chats = [row for row in records if row.get('service') == 'chat']
        if not chats or any(row.get('requested_model') != model
                            or row.get('observed_model') != model
                            or row.get('identity_status') != 'matched' for row in chats):
            raise ValueError('Sponsor response model identity is not verified against the reviewed model.')
    inputs = json.loads((out / 'inputs.json').read_text())
    contract = json.loads((out / 'scenario.json').read_text())
    checkpoint = json.loads((out / 'checkpoint.json').read_text())
    for name in ('base', 'head'):
        if inputs[name]['sha256'] != manifest['files'][name + '.md']:
            raise ValueError('Input provenance differs from saved document.')
    if (checkpoint['scenario_sha256'] != manifest['files']['scenario.json']
            or checkpoint['source_sha256'] != manifest['files']['source.tar']
            or checkpoint['base_id'] != contract['image_id']):
        raise ValueError('Checkpoint differs from reviewed source or runtime.')
    base, control, head, delta = [json.loads((out / (name + '.json')).read_text()) for name in ('base', 'control', 'head', 'delta')]
    if (out / 'base.json').read_bytes() != (out / 'control.json').read_bytes():
        raise ValueError('Control did not match the base run.')
    for run in (base, control, head):
        if check(run) or semantic(run): raise ValueError('Invalid saved run.')
    if check(delta, 'delta.schema.json') or not delta['control']['identical']:
        raise ValueError('Invalid comparison.')
    if delta['base']['run_id'] != base['run_id'] or delta['head']['run_id'] != head['run_id']:
        raise ValueError('Comparison names different runs.')
    for name, run in (('base', base), ('control', control), ('head', head)):
        doc = 'base' if name == 'control' else name
        if manifest['config'].get('backend') in ('sponsor', 'tokenfactory-local'):
            model = manifest['config']['sponsor']['model']
            hybrid = manifest['config']['backend'] == 'tokenfactory-local'
            if (run['labels'] != (['SIMULATED', 'LOCAL'] if hybrid else ['SIMULATED'])
                    or run['backends']['model']['label'] != 'RUNTIME'
                    or run['backends']['sandbox']['label'] != ('LOCAL' if hybrid else 'RUNTIME')
                    or run['backends']['grounding']['label'] not in ('RUNTIME', 'NONE')
                    or run['policy']['model']['name'] != model):
                raise ValueError('Actual result is not the reviewed sponsor backend.')
            for population in run['populations']:
                if population['backend']['label'] != 'RUNTIME':
                    raise ValueError('A local population cannot satisfy a sponsor comparison.')
                if population['id'] == 'coding_agents' and population['harness']['model'] != model:
                    raise ValueError('Agent model differs from reviewed model.')
        elif 'LOCAL' not in run['labels']:
            raise ValueError('Actual result differs from reviewed local backend.')
        pops = {p['id']: p for p in run['populations']}
        if (run['doc']['sha256'] != inputs[doc]['sha256'] or run['seed'] != manifest['config']['seed']
                or pops['humans']['n']['value'] != manifest['config']['n']
                or pops.get('coding_agents', {'n': {'value': 0}})['n']['value'] != manifest['config']['agents']
                or run['target']['scenario']['sha256'] != manifest['files']['scenario.json']
                or run['target']['scenario']['checkpoint_image_id'] != checkpoint['checkpoint_image_id']):
            raise ValueError('Actual run differs from the reviewed inputs, population or checkpoint.')
    base_sha = sha256_bytes((out / 'base.json').read_bytes())
    expected_delta = compute_delta(base, head, base_file='base.json', head_file='head.json', base_sha=base_sha, control_sha=base_sha)
    if delta != expected_delta: raise ValueError('Delta differs from the actual paired runs and control.')
    raw = dumps({name: sha256_bytes((out / name).read_bytes()) for name in result_files(directory)}).encode()
    (directory / 'result-seal.json').write_bytes(raw)
    return sha256_bytes(raw)


def verify_result(directory, expected):
    raw = (directory / 'result-seal.json').read_bytes()
    if sha256_bytes(raw) != expected: raise ValueError('Result identity does not match completion.')
    hashes = json.loads(raw)
    if set(hashes) != set(result_files(directory)): raise ValueError('Result files missing.')
    content = {}
    for name, digest in hashes.items():
        path = directory / 'result' / name
        content[name] = path.read_bytes()
        if path.is_symlink() or sha256_bytes(content[name]) != digest:
            raise ValueError(name + ' no longer matches the completed run.')
    return content


def run(path):
    os.umask(0o077)
    path = Path(path).resolve(); directory = path.parent
    job = json.loads(path.read_text())
    save(directory / 'status.json', {'state': 'running', 'pid': os.getpid()})
    try:
        sponsor = job['config'].get('backend') in ('sponsor', 'tokenfactory-local')
        if sponsor and job.get('allow_sponsor') is not True:
            raise ValueError('Sponsor execution was not authorized by the workspace service.')
        with (directory / 'compare.log').open('wb') as log:
            child = subprocess.run([sys.executable, '-m', 'sim', 'compare', '--prepared', job['snapshot'],
                                    '--expected', job['expected'], '--output', job['output']] + (['--allow-sponsor'] if sponsor else []),
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if child.returncode: raise ValueError('Comparison exited ' + str(child.returncode) + '. Inspect the saved engine log.')
        digest = result_seal(directory)
        save(directory / 'status.json', {'state': 'complete', 'exit_code': 0, 'result_sha256': digest})
    except Exception as e:
        save(directory / 'status.json', {'state': 'failed', 'error': str(e)})


if __name__ == '__main__': run(sys.argv[1])
