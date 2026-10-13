"""Local controller reservation -> sealed forecast -> later outcomes.

Integrity checks are local, not an authenticated timestamp or proof of independence.
No existing exploratory trial is implicitly promoted to prospective evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import secrets

from calib.score import score as direction_score

ARMS = ('base', 'head')
IDENTITY = ('trial', 'tool', 'task', 'model', 'scaffold', 'checker', 'environment', 'population', 'seed_family')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write('\n')


def _read(path):
    return json.loads(Path(path).read_text())


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('expected SHA256 identity')


def _prob(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('probability must be finite in [0,1]')


def reserve(path, identity, seeds, exploratory, *, mode='prospective'):
    """exploratory rows: {run_id, seeds, trace_sha256}; declare all prior exposure.

    identity contains SHA256s for every required component, plus tool {base,head}.
    Task hash must cover task text, discovery, setup, budget and outcome definition.
    """
    if mode not in ('prospective', 'historical-fixture'):
        raise ValueError('unknown evidence mode')
    if set(identity) != set(IDENTITY) or set(identity['tool']) != set(ARMS):
        raise ValueError('complete frozen identity required')
    for k in IDENTITY:
        for v in identity[k].values() if k == 'tool' else [identity[k]]:
            _hash(v)
    if not seeds or any(type(s) is not int or s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('unique nonnegative integer seeds required')
    used = set(); run_ids = set()
    for row in exploratory:
        if not row.get('run_id') or row['run_id'] in run_ids or not row.get('seeds'):
            raise ValueError('distinct exploratory run IDs and seeds required')
        if not isinstance(row.get('trace_sha256'), list) or not row['trace_sha256']:
            raise ValueError('exploratory execution trace hashes required')
        for trace in row['trace_sha256']: _hash(trace)
        run_ids.add(row['run_id']); used.update(row['seeds'])
    if used.intersection(seeds):
        raise ValueError('reserved seeds overlap exploratory exposure')
    root = Path(path); root.mkdir(parents=True, exist_ok=False)
    value = {'schema': 'tool-forecast/1', 'mode': mode, 'identity': identity,
             'seeds': seeds, 'exploratory': exploratory, 'nonce': secrets.token_hex(32),
             'baseline': {'name': 'constant-half', 'probability': .5},
             'labels': ['SIMULATED', 'LOCAL'] + (['HISTORICAL-FIXTURE'] if mode == 'historical-fixture' else [])}
    _write(root / 'reservation.json', value)
    return digest(value)


def seal(path, expected_reservation, probabilities, *, abstention_reason=None):
    root = Path(path); reservation = _read(root / 'reservation.json')
    if digest(reservation) != expected_reservation:
        raise ValueError('reservation changed')
    if set(probabilities) != set(ARMS):
        raise ValueError('both arm predictions required')
    for p in probabilities.values():
        if p is not None: _prob(p)
        elif not isinstance(abstention_reason, str) or not abstention_reason.strip():
            raise ValueError('abstention requires reason')
    value = {'reservation': expected_reservation, 'probabilities': probabilities,
             'abstention_reason': abstention_reason}
    _write(root / 'forecast.json', value)
    return digest(value)


def _bound(path, expected_seal):
    root = Path(path); reservation = _read(root / 'reservation.json'); forecast = _read(root / 'forecast.json')
    if digest(forecast) != expected_seal or digest(reservation) != forecast['reservation']:
        raise ValueError('seal or reserved contract changed')
    return root, reservation, forecast


def start(path, expected_seal, identity, run_id):
    """Called by controller before a newly launched reserved batch, never on import."""
    root, reservation, _ = _bound(path, expected_seal)
    if identity != reservation['identity']:
        raise ValueError('execution identity differs')
    if not isinstance(run_id, str) or not run_id.strip() or run_id in [r['run_id'] for r in reservation['exploratory']]:
        raise ValueError('new reserved run identity required')
    receipt = {'seal': expected_seal, 'run_id': run_id, 'identity': identity,
               'nonce': secrets.token_hex(32)}
    _write(root / 'start.json', receipt)
    return digest(receipt)


def observe(path, expected_seal, expected_start, identity, run_id, arm, seed, completed, *, trace_sha256, status):
    root, reservation, _ = _bound(path, expected_seal)
    started = _read(root / 'start.json')
    if digest(started) != expected_start or started['seal'] != expected_seal:
        raise ValueError('wrong start receipt')
    if identity != reservation['identity'] or started['identity'] != identity or run_id != started['run_id']:
        raise ValueError('outcome contract or run changed')
    if arm not in ARMS or type(seed) is not int or seed not in reservation['seeds']:
        raise ValueError('outcome is not a reserved slot')
    if type(completed) is not bool or not isinstance(status, str) or not status.strip():
        raise ValueError('controller boolean outcome and exit status required')
    _hash(trace_sha256)
    if trace_sha256 in {h for r in reservation['exploratory'] for h in r['trace_sha256']}:
        raise ValueError('exploratory execution cannot be scored as later evidence')
    value = {'start': expected_start, 'run_id': run_id, 'arm': arm, 'seed': seed,
             'completed': completed, 'trace_sha256': trace_sha256, 'status': status}
    _write(root / f'outcome-{arm}-{seed}.json', value)
    return digest(value)


def evaluate(path, expected_seal, expected_start, expected_outcomes):
    root, reservation, forecast = _bound(path, expected_seal)
    started = _read(root / 'start.json')
    if digest(started) != expected_start or started['seal'] != expected_seal or started['identity'] != reservation['identity']:
        raise ValueError('start receipt changed')
    losses = []; baseline_matched = []; baseline_all = []; counts = {}; trace_ids = set()
    slots = {f'{arm}-{seed}' for arm in ARMS for seed in reservation['seeds']}
    if set(expected_outcomes) != slots:
        raise ValueError('receipts for every reserved outcome required')
    for arm in ARMS:
        outcomes = []
        for seed in reservation['seeds']:
            row = _read(root / f'outcome-{arm}-{seed}.json')  # Missing slots refuse, never disappear.
            if digest(row) != expected_outcomes[f'{arm}-{seed}']:
                raise ValueError('outcome receipt changed')
            if (row['start'] != expected_start or row['run_id'] != started['run_id'] or row['arm'] != arm
                    or row['seed'] != seed or type(row['completed']) is not bool):
                raise ValueError('outcome binding changed')
            _hash(row['trace_sha256'])
            if row['trace_sha256'] in trace_ids:
                raise ValueError('duplicate execution trace')
            trace_ids.add(row['trace_sha256'])
            y = int(row['completed']); outcomes.append(y); baseline_all.append((.5-y)**2)
            p = forecast['probabilities'][arm]
            if p is not None:
                losses.append((p-y)**2); baseline_matched.append((.5-y)**2)
        counts[arm] = {'reached': sum(outcomes), 'n': len(outcomes)}
    pbase, phead = (forecast['probabilities'][a] for a in ARMS)
    direction = None
    if pbase is not None and phead is not None:
        change = phead - pbase
        direction = direction_score({'direction': 'helps' if change > 0 else 'hurts' if change < 0 else 'no detectable change',
                                     'magnitude': {'goal_rate_change': change}}, [counts])
    mean = lambda xs: sum(xs)/len(xs) if xs else None
    return {'labels': reservation['labels'], 'mode': reservation['mode'], 'seal': expected_seal,
            'n_reserved': len(baseline_all), 'n_scored': len(losses), 'coverage': len(losses)/len(baseline_all),
            'brier': mean(losses), 'baseline_brier_all': mean(baseline_all),
            'baseline_brier_matched': mean(baseline_matched), 'counts': counts,
            'abstention_reason': forecast['abstention_reason'], 'direction': direction,
            'claim': 'Historical fixture only' if reservation['mode'] == 'historical-fixture' else 'Local controller-reported reserved outcomes; independence not externally attested',
            'limits': 'Descriptive single-contract score; no calibrated advantage, human inference or authenticated chronology.'}
