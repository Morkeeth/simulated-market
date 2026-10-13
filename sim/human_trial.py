"""Private, operator-reported human trials bound to completed comparisons.

One cohort is one calibration row. Participants never become independent claims
about predictor accuracy. This module never executes commands or calls providers.
"""
from __future__ import annotations

import datetime
import json
import secrets
from calib.score import score
from sim.doc import sha256_bytes
from sim.run import dumps


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be nonempty text under {limit} characters.')
    return value.strip()


def completed(ws, id):
    from sim.workspace_worker import verify_result
    from sim.workspace import identifier, load
    directory = ws.root / 'jobs' / identifier(id)
    status = load(directory / 'status.json')
    if status.get('state') != 'complete':
        raise ValueError('A human trial needs a completed, control-verified comparison.')
    content = verify_result(directory, status['result_sha256'])
    return directory, status['result_sha256'], content


def read(ws, id):
    from sim.workspace import load
    directory, seal, content = completed(ws, id)
    path = directory / 'human-trial.json'
    if not path.exists():
        return {'trial': None}
    state = load(path)
    if state['plan']['result_sha256'] != seal:
        raise ValueError('Trial belongs to a different completed result.')
    if sha256_bytes(dumps(state['plan']).encode()) != state['plan_sha256']:
        raise ValueError('Frozen trial plan changed.')
    delta = json.loads(content['delta.json'])
    totals = {arm: {'reached': 0, 'n': 0, 'withdrawn': 0, 'pending': 0} for arm in ('base', 'head')}
    for slot in state['plan']['participants']:
        result = state['observations'].get(slot['id'], {}).get('outcome')
        t = totals[slot['arm']]
        if result is None: t['pending'] += 1
        elif result == 'withdrawn': t['withdrawn'] += 1
        else:
            t['n'] += 1
            t['reached'] += result == 'reached'
    # A incomplete cohort is not evidence, and repeated participant observations
    # never inflate the number of independent outcome rows.
    row = None
    if state['state'] == 'closed':
        row = {arm: {k: totals[arm][k] for k in ('reached', 'n')} for arm in totals}
        row.update(base_doc_sha256=delta['base']['doc_sha256'], head_doc_sha256=delta['head']['doc_sha256'],
                   source='Operator-reported human trial: ' + state['plan']['recruitment'],
                   trial_id=state['plan']['id'], result_sha256=seal,
                   evidence_kind='operator-reported; not independently verified', study_design='parallel-single-arm')
    return {'trial': state, 'totals': totals, 'outcome_row': row,
            'score': score(delta, [row] if row else []),
            'prediction': {'direction': delta['direction'], 'labels': delta['labels']},
            'documents': {arm: content[arm + '.md'].decode() for arm in totals},
            'limits': 'Descriptive comparison of one cohort. Recruitment, consent, environment and outcomes are reported by the operator, not independently verified. Withdrawal can bias the comparison. This does not establish causal impact or market calibration.'}


def create(ws, body):
    from sim.workspace import save
    with ws.lock:
        directory, seal, content = completed(ws, body['id'])
        path = directory / 'human-trial.json'
        if path.exists():
            raise ValueError('This comparison already has a frozen trial. Reopen it; do not replace its cohort.')
        n = body.get('participants')
        if type(n) is not int or not 2 <= n <= 200 or n % 2:
            raise ValueError('Choose an even cohort size from 2 to 200, balanced between documents.')
        minutes = body.get('minutes')
        if type(minutes) is not int or not 1 <= minutes <= 240:
            raise ValueError('Choose a fixed session limit from 1 to 240 minutes.')
        scenario = json.loads(content['scenario.json'])
        inputs = json.loads(content['inputs.json'])
        arms = ['base'] * (n // 2) + ['head'] * (n // 2)
        secrets.SystemRandom().shuffle(arms)
        plan = {'version': 1, 'id': secrets.token_hex(12), 'created_at': now(), 'job_id': body['id'],
                'result_sha256': seal, 'goal': scenario['goal'], 'checks': scenario['steps'],
                'source': scenario['source'], 'image_id': scenario['image_id'], 'setup': scenario['setup'],
                'documents': {arm: inputs[arm]['sha256'] for arm in ('base', 'head')},
                'recruitment': text(body.get('recruitment'), 'Recruitment and eligibility'),
                'environment': text(body.get('environment'), 'Identical starting environment'),
                'minutes': minutes, 'participants': [{'id': f'P{i+1:03}', 'arm': arm} for i, arm in enumerate(arms)]}
        save(path, {'plan': plan, 'plan_sha256': sha256_bytes(dumps(plan).encode()),
                    'state': 'collecting', 'revision': 1, 'observations': {}, 'history': []})
        return read(ws, body['id'])


def record(ws, body):
    from sim.workspace import save
    with ws.lock:
        result = read(ws, body['id']); state = result['trial']
        if state is None: raise ValueError('Prepare the human trial first.')
        if state['state'] != 'collecting': raise ValueError('This cohort is closed. Its observations are preserved.')
        if body.get('revision') != state['revision']:
            raise ValueError('The trial changed in another tab. Reopen before recording.')
        participant = body.get('participant')
        if participant not in {p['id'] for p in state['plan']['participants']}:
            raise ValueError('Unknown participant slot.')
        outcome = body.get('outcome')
        if outcome not in ('reached', 'not_reached', 'withdrawn'):
            raise ValueError('Choose reached, not reached, or withdrew.')
        if body.get('consent') is not True:
            raise ValueError('Confirm the person consented to this observation; do not record personal details.')
        evidence = text(body.get('evidence'), 'What you observed')
        correction = text(body.get('correction'), 'Reason for correction') if participant in state['observations'] else None
        observation = {'outcome': outcome, 'evidence': evidence, 'consent_reported': True, 'recorded_at': now()}
        state['history'].append({'participant': participant, 'previous': state['observations'].get(participant),
                                 'observation': observation, 'correction': correction})
        state['observations'][participant] = observation
        state['revision'] += 1
        save(ws.root / 'jobs' / body['id'] / 'human-trial.json', state)
        return read(ws, body['id'])


def close(ws, body):
    from sim.workspace import save
    with ws.lock:
        result = read(ws, body['id']); state = result['trial']
        if state is None: raise ValueError('Prepare the human trial first.')
        if state['state'] == 'closed': return result
        if body.get('revision') != state['revision']:
            raise ValueError('The trial changed in another tab. Reopen before closing.')
        if any(t['pending'] or not t['n'] for t in result['totals'].values()):
            raise ValueError('Account for every slot, with at least one observed session per document. Withdrawals are shown separately.')
        state.update(state='closed', closed_at=now(), revision=state['revision'] + 1)
        save(ws.root / 'jobs' / body['id'] / 'human-trial.json', state)
        return read(ws, body['id'])
