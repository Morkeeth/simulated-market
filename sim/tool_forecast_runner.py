"""Controller-owned constant-half forecast, then a fresh local shell-agent batch.

No historical import route. A forecast here is a fixed baseline, not learned skill.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from sim import ROOT
from sim import tool_forecast as forecast

CODE = ('sim/tool_trial.py', 'sim/tool_shell.py', 'sim/tool_shell_agent.py',
        'sim/tool_gateway.py', 'sim/agent_protocol.py', 'sim/standins/local_model.py',
        'sim/adapters/openai_compat.py', 'sim/standins/docker_sandbox.py',
        'sim/tool_forecast.py', 'sim/tool_forecast_runner.py')


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def tree_hash(path):
    path = Path(path).resolve()
    files = {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if not files: raise ValueError('empty frozen asset tree: ' + str(path))
    return forecast.digest(files)


def inventory(registry, exclude=None):
    """Conservatively reserve against every tool trial beneath declared registry."""
    rows = []
    for path in sorted(Path(registry).resolve().rglob('contract.json')):
        if exclude and path.parent == Path(exclude).resolve(): continue
        data = json.loads(path.read_text())
        if data.get('kind') != 'agent-tool-trial': continue
        state_path = path.parent / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        traces = [forecast.digest(ep) for ep in state.get('episodes', [])]
        rows.append({'run_id': str(path.parent), 'seeds': data['seeds'],
                     'trace_sha256': traces or [file_hash(path)]})
    return rows


def identities(trial_dir, model_snapshot, population, seed_family):
    from sim import tool_trial as trial
    frozen = json.loads((Path(trial_dir)/'contract.json').read_text())
    frozen = trial.verify(Path(trial_dir), frozen['sha256'], execution=True)
    from sim.standins.local_model import MODEL
    if Path(MODEL).resolve() != Path(model_snapshot).resolve():
        raise ValueError('SIM_LOCAL_MODEL must be the exact cached snapshot path')
    # Hash installed runtime code rather than trusting a package version string.
    runtimes = {name: tree_hash(ROOT/name/'lib') for name in ('.venv-agent', '.venv-model')}
    code = {name: file_hash(ROOT/name) for name in CODE}
    return {'trial': frozen['sha256'],
            'tool': {arm: file_hash(Path(trial_dir)/(arm+'.tar')) for arm in forecast.ARMS},
            'task': forecast.digest({k:frozen[k] for k in ('task','discovery','fixtures','setup','command','budget','integrity')}),
            'model': forecast.digest({'snapshot': tree_hash(model_snapshot), 'runtime': runtimes['.venv-model'], 'temperature':0, 'max_tokens':1024}),
            'scaffold': forecast.digest({'code':code, 'agent_runtime':runtimes['.venv-agent']}),
            'checker': file_hash(Path(trial_dir)/'check.py'),
            'environment': forecast.digest({'image':frozen['image'], 'network':'none', 'runtimes':runtimes}),
            'population': forecast.digest(population), 'seed_family': forecast.digest(seed_family)}


def population_metadata(population, task_family, seeds):
    """Explicit task-family declaration; execution model/harness remain byte-bound."""
    if (not isinstance(population,dict) or set(population) != {'kind','description'}
            or population['kind'] != 'local-shell-agent'
            or not isinstance(population['description'],str) or not population['description'].strip()):
        raise ValueError('declare local-shell-agent population and nonempty description')
    if (not isinstance(task_family,dict) or set(task_family) != {'name','sampling'}
            or any(not isinstance(v,str) or not v.strip() for v in task_family.values())):
        raise ValueError('declare task family name and sampling rule')
    return dict(population), {**task_family, 'seeds':list(seeds)}


def prepare(path, contract, registry, model_snapshot, *, population, task_family, mode='prospective'):
    from sim import tool_trial as trial
    path = Path(path).resolve()
    population, seed_family = population_metadata(population,task_family,contract['seeds'])
    prior = inventory(registry)
    used = {s for row in prior for s in row['seeds']}
    if used.intersection(contract['seeds']): raise ValueError('seed exposed or reserved in trial registry')
    path.mkdir(parents=True, exist_ok=False)
    trial.prepare(contract, path/'trial')
    identity = identities(path/'trial', model_snapshot, population, seed_family)
    reserved = forecast.reserve(path/'forecast', identity, contract['seeds'], prior, mode=mode)
    sealed = forecast.seal(path/'forecast', reserved, {'base':.5,'head':.5})
    manifest = {'mode':mode, 'identity':identity, 'seal':sealed, 'reservation':reserved,
                'registry':str(Path(registry).resolve()), 'model_snapshot':str(Path(model_snapshot).resolve()),
                'population':population, 'seed_family':seed_family, 'forecast_source':'fixed constant-half baseline, not learned',
                'sealed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    forecast._write(path/'adapter.json', manifest)
    return forecast.digest(manifest)


def execute(path, expected_adapter):
    from sim import tool_shell
    path = Path(path).resolve(); m = forecast._read(path/'adapter.json')
    if forecast.digest(m) != expected_adapter: raise ValueError('adapter manifest changed')
    identity = identities(path/'trial', m['model_snapshot'], m['population'], m['seed_family'])
    if identity != m['identity']: raise ValueError('frozen execution bytes changed')
    used = {s for row in inventory(m['registry'], path/'trial') for s in row['seeds']}
    if used.intersection(m['seed_family']['seeds']): raise ValueError('new conflicting trial reserved these seeds')
    run_id = str(path/'trial')
    receipt = forecast.start(path/'forecast', m['seal'], identity, run_id)
    forecast._write(path/'launch.json', {'start':receipt,'adapter':expected_adapter,'at':dt.datetime.now(dt.timezone.utc).isoformat()})
    state = tool_shell.run(path/'trial', identity['trial'])
    # Verify bytes again before accepting any outcome; no silent score after drift.
    if identities(path/'trial', m['model_snapshot'], m['population'], m['seed_family']) != identity:
        raise ValueError('execution bytes changed during run; preserved batch not scored')
    return ingest(path, m, receipt, state)


def ingest(path, manifest, receipt, state):
    """Controller result adapter; retained files bind checker + participant traces."""
    path = Path(path); identity = manifest['identity']
    if state.get('contract') != identity['trial'] or state.get('policy') != 'local-shell-agent' or state.get('status') != 'complete':
        raise ValueError('runner did not complete the reserved shell batch')
    expected = {(a,s) for a in forecast.ARMS for s in manifest['seed_family']['seeds']}
    episodes = state['episodes']
    if len(episodes) != len(expected) or {(e['arm'],e['seed']) for e in episodes} != expected:
        raise ValueError('missing or duplicate reserved runner episodes')
    outcomes = {}
    for ep in episodes:
        if ep.get('evidence_error'): raise ValueError('controller evidence collection failed')
        proofs = [e['check'] for e in ep['events'] if e.get('action') == 'invoke']
        completed = proofs[-1]['passed'] if proofs else False
        if type(completed) is not bool or completed != ep['completed']:
            raise ValueError('controller checker and reported completion disagree')
        episode_dir = path/'trial'/f"{ep['arm']}-{ep['seed']}"
        trace = {'episode':ep, 'files':{p.name:file_hash(p) for p in sorted(episode_dir.glob('*')) if p.is_file()}}
        key = f"{ep['arm']}-{ep['seed']}"
        outcomes[key] = forecast.observe(path/'forecast',manifest['seal'],receipt,identity,str(path/'trial'),ep['arm'],ep['seed'],completed,
                                        trace_sha256=forecast.digest(trace),status=ep['status'])
    forecast._write(path/'outcome-receipts.json',outcomes)
    score = forecast.evaluate(path/'forecast',manifest['seal'],receipt,outcomes)
    score.update(forecast_source=manifest['forecast_source'], cost=state.get('cost'), elapsed_seconds=state.get('elapsed_seconds'))
    forecast._write(path/'score.json',score)
    return score


def review(path, expected_adapter):
    """Read-only replay for UI. Never launches models or recomputes mutable runtimes."""
    from sim import tool_trial as trial
    path = Path(path).resolve(); m = forecast._read(path/'adapter.json')
    if forecast.digest(m) != expected_adapter: raise ValueError('adapter manifest changed')
    trial.verify(path/'trial',m['identity']['trial'])
    _, reservation, sealed = forecast._bound(path/'forecast',m['seal'])
    view = {'contract':m['identity']['trial'], 'seal':m['seal'], 'mode':m['mode'],
            'labels':reservation['labels'], 'probabilities':sealed['probabilities'],
            'forecast_source':m['forecast_source'], 'status':'sealed-unscored', 'score':None}
    if not (path/'score.json').exists(): return view
    launch = forecast._read(path/'launch.json')
    if launch['adapter'] != expected_adapter: raise ValueError('launch changed')
    receipts = forecast._read(path/'outcome-receipts.json')
    result = forecast.evaluate(path/'forecast',m['seal'],launch['start'],receipts)
    state = forecast._read(path/'trial/state.json')
    expected = {(a,s) for a in forecast.ARMS for s in m['seed_family']['seeds']}
    if (state.get('status') != 'complete' or state.get('contract') != m['identity']['trial']
            or state.get('policy') != 'local-shell-agent' or len(state.get('episodes',[])) != len(expected)
            or {(e['arm'],e['seed']) for e in state['episodes']} != expected):
        raise ValueError('recorded batch is incomplete or changed')
    for ep in state['episodes']:
        episode_dir = path/'trial'/f"{ep['arm']}-{ep['seed']}"
        trace = {'episode':ep, 'files':{p.name:file_hash(p) for p in sorted(episode_dir.glob('*')) if p.is_file()}}
        observed = forecast._read(path/'forecast'/f"outcome-{ep['arm']}-{ep['seed']}.json")
        if observed['trace_sha256'] != forecast.digest(trace): raise ValueError('recorded execution trace changed')
    saved = forecast._read(path/'score.json')
    result.update(forecast_source=m['forecast_source'],cost=state.get('cost'),elapsed_seconds=state.get('elapsed_seconds'))
    if saved != result: raise ValueError('saved score changed')
    view.update(status='scored',score=result)
    return view


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare')
    for key in ('path','contract','registry','model-snapshot','population','task-family'):p.add_argument('--'+key,required=True)
    p.add_argument('--mode',choices=('prospective','historical-fixture'),default='prospective')
    r=sub.add_parser('run');r.add_argument('--path',required=True);r.add_argument('--expected',required=True)
    a=ap.parse_args()
    if a.action=='prepare': result=prepare(a.path,json.loads(Path(a.contract).read_text()),a.registry,a.model_snapshot,
        population=json.loads(Path(a.population).read_text()),task_family=json.loads(Path(a.task_family).read_text()),mode=a.mode)
    else: result=execute(a.path,a.expected)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
