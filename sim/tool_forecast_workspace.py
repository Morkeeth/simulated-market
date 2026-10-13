"""Workspace-owned prospective local agent batches.

Imported forecast receipts never acquire execution authority. Ownership is a
server-created record bound to the workspace's own batch directory and adapter.
"""
from pathlib import Path
import os
import secrets
import subprocess
import sys

from sim import ROOT, tool_trial as trial


def owned(ws, id):
    from sim.tool_workspace import directory
    marker = directory(ws, id) / 'forecast-owned.json'
    if not marker.is_file():
        return None
    record = trial.read(marker)
    batch = (ws.root / 'forecast-batches' / id).resolve()
    reference = trial.read(directory(ws, id) / 'forecast-reference.json')
    if (record.get('schema') != 'workspace-forecast/1' or record.get('id') != id
            or record.get('path') != str(batch) or reference.get('path') != str(batch)
            or record.get('adapter') != reference.get('adapter')
            or record.get('contract') != reference.get('contract')):
        raise ValueError('Workspace forecast ownership changed.')
    return batch, record


def prepare(ws, body):
    from sim import tool_forecast_runner as runner
    from sim.tool_decision_protocol import initialize
    from sim.tool_forecast_view import review
    from sim.tool_workspace import directory, result
    with ws.lock:
        if set(body) != {'contract', 'modelSnapshot', 'population', 'taskFamily'}:
            raise ValueError('Freeze contract, local model snapshot, population and task family.')
        snapshot = body['modelSnapshot']
        if not isinstance(snapshot, str) or not snapshot.strip() or not Path(snapshot).is_absolute() or not Path(snapshot).is_dir():
            raise ValueError('Choose an existing absolute local model snapshot directory.')
        id = secrets.token_hex(12)
        batch = ws.root / 'forecast-batches' / id
        batch.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        adapter = runner.prepare(batch, body['contract'], ws.root, snapshot,
                                 population=body['population'], task_family=body['taskFamily'])
        manifest = trial.read(batch / 'adapter.json')
        reference = {'path': str(batch.resolve()), 'adapter': adapter,
                     'contract': manifest['identity']['trial'],
                     'scope': 'Workspace-owned prospective local batch; fixed 50/50 baseline, not learned.'}
        target = directory(ws, id)
        target.mkdir(parents=True, exist_ok=False, mode=0o700)
        trial.dump(target / 'forecast-reference.json', reference)
        trial.dump(target / 'forecast-owned.json', {'schema': 'workspace-forecast/1',
                   'id': id, 'path': str(batch.resolve()), 'adapter': adapter,
                   'contract': reference['contract']})
        trial_path = batch / 'trial'
        initialize(ws, id, trial.read(trial_path / 'contract.json'),
                   trial.read(trial_path / 'state.json'), review(reference), started=False)
        return result(ws, id)


def start(ws, body):
    from sim.tool_preflight import require_passed
    with ws.lock:
        id = body.get('id')
        relation = owned(ws, id)
        if relation is None:
            raise ValueError('Imported forecast batches are read-only.')
        batch, record = relation
        if body.get('expected') != record['contract'] or body.get('policy') != 'local-shell-agent':
            raise ValueError('Use the exact frozen local shell-agent comparison.')
        if not ws.allow_agents:
            raise ValueError('Start this workspace with --allow-agents to run the cached local model.')
        trial.verify(batch / 'trial', record['contract'], execution=True)
        require_passed(ws, id, record['contract'], 'local-shell-agent')
        from sim.standins.local_model import SERVER_BIN
        if not SERVER_BIN.exists() or not (ROOT / '.venv-agent/bin/python').exists():
            raise ValueError('Cached local model and mini-swe-agent runtimes are required.')
        claim = batch / 'workspace-launch'
        with os.fdopen(os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
            stream.write(record['adapter'] + '\n')
        log = (batch / 'worker.log').open('ab')
        try:
            process = subprocess.Popen([sys.executable, '-m', 'sim.tool_forecast_workspace',
                                        '--batch', str(batch), '--adapter', record['adapter']],
                                       cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        except OSError as error:
            trial.dump(batch / 'workspace-error.json', {'error': type(error).__name__ + ': ' + str(error)})
            raise
        finally:
            log.close()
        trial.dump(batch / 'worker.json', {'pid': process.pid})
        return {'id': id, 'status': 'starting'}


def execute(batch, adapter):
    from sim.tool_forecast_runner import execute as run
    try:
        return run(batch, adapter)
    except Exception as error:
        trial.dump(Path(batch) / 'workspace-error.json', {'error': type(error).__name__ + ': ' + str(error)[:700]})
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--adapter', required=True)
    args = parser.parse_args()
    execute(args.batch, args.adapter)
