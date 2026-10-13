"""Operator decision history, kept separately from frozen trials and outcomes."""
import datetime as dt
import json
import os

from sim import tool_trial


def path(ws, trial_id):
    from sim.workspace import identifier
    return ws.root / 'tool-decisions' / (identifier(trial_id) + '.jsonl')


def history(ws, trial_id, contract, state_sha):
    target = path(ws, trial_id)
    rows = [json.loads(line) for line in target.read_text().splitlines()] if target.exists() else []
    previous = None
    for index, row in enumerate(rows, 1):
        value = {k:v for k,v in row.items() if k != 'sha256'}
        if (tool_trial.digest(value) != row.get('sha256') or row.get('revision') != index
                or row.get('previous') != previous or row.get('contract') != contract['sha256']
                or row.get('state_sha256') != state_sha or row.get('initial_choice') != contract.get('initial_choice')):
            raise ValueError('Decision history or its bound trial outcome changed. Preserve this record for review.')
        previous = row['sha256']
    return rows


def outcomes(contract, state):
    result = {}
    for arm in ('base', 'head'):
        episodes = [e for e in state['episodes'] if e['arm'] == arm]
        result[arm] = {'planned': len(contract['seeds']), 'observed': len(episodes),
                       'last_task_passed': sum(bool(e.get('completed')) for e in episodes),
                       'ever_passed': sum(bool(e.get('ever_completed')) for e in episodes),
                       'recovered': sum(bool(e.get('recovered')) for e in episodes)}
    return result


def save(ws, body):
    from sim.tool_workspace import result
    with ws.lock:
        data = result(ws, body.get('id'))
        if data.get('decision_protocol'):raise ValueError('Use the sequential decision stages for this comparison.')
        contract, state = data['contract'], data['state']
        if state.get('status') not in ('complete', 'failed') or state.get('contract') != contract['sha256']:
            raise ValueError('Review a completed or failed trial before recording a release decision.')
        if body.get('expected') != contract['sha256'] or body.get('state_sha256') != data['state_sha256']:
            raise ValueError('The trial identity or observed outcome changed. Reopen the exact result.')
        rows = data['decisions']
        if type(body.get('revision')) is not int or body['revision'] != len(rows):
            raise ValueError('Another decision revision was saved. Reopen the result before adding yours.')
        choice, reason = body.get('choice'), body.get('reason')
        if choice not in ('base', 'head', 'defer') or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('Choose baseline, candidate or defer, then explain your reviewed decision.')
        row = {'revision':len(rows)+1, 'previous':rows[-1]['sha256'] if rows else None,
               'contract':contract['sha256'], 'state_sha256':data['state_sha256'],
               'initial_choice':contract['initial_choice'], 'choice':choice, 'reason':reason.strip(),
               'at':dt.datetime.now(dt.timezone.utc).isoformat(), 'outcomes':outcomes(contract, state),
               'trial_status':state['status'], 'policy':state.get('policy'),
               'scope':'Operator declaration after review. A changed choice does not establish an improved decision.'}
        row['sha256'] = tool_trial.digest(row)
        target = path(ws, data['id']); target.parent.mkdir(exist_ok=True, mode=0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
        return result(ws, data['id'])
