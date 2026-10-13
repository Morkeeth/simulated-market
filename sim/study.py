"""Read a completed registered campaign into the private workspace.

The campaign remains outside the repository. Loading checks the frozen model,
registration, forecast, evaluation, and each raw trial before showing a replay.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def sealed(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not isinstance(value.get('sha256'), str):
        raise ValueError('Campaign object has no seal: ' + Path(path).name)
    content = dict(value)
    expected = content.pop('sha256')
    if digest(content) != expected:
        raise ValueError('Campaign object changed: ' + Path(path).name)
    return value


class HeldoutStudy:
    def __init__(self, folder, model_path):
        self.folder = Path(folder).expanduser().resolve()
        self.model_path = Path(model_path).expanduser().resolve()
        self.snapshot = self._read()

    def _read(self):
        root = self.folder
        manifest = sealed(root / 'manifest.json')
        lock = sealed(root / 'forecast-lock.json')
        evaluation = sealed(root / 'evaluation.json')
        model = sealed(self.model_path)
        result = json.loads((root / 'result.json').read_text())
        if result.get('status') != 'complete' or result.get('completed_episodes') != len(manifest['trials']):
            raise ValueError('The registered campaign is not complete.')
        if not (manifest['stage'] == 'heldout' and result['manifest_sha256'] == manifest['sha256']
                and lock['target_manifest_sha256'] == manifest['sha256']
                and evaluation['target_manifest_sha256'] == manifest['sha256']
                and lock['model_sha256'] == model['sha256'] == evaluation['model_sha256']
                and evaluation['forecast_lock_sha256'] == lock['sha256']):
            raise ValueError('Campaign identities do not match.')
        if evaluation.get('kind') != 'heldout-prediction-evaluation' or len(evaluation['episodes']) != len(manifest['trials']):
            raise ValueError('Evaluation does not cover every registered trial.')
        if set(manifest['family_registry']) & set(model['training_families']):
            raise ValueError('Heldout family was used for training.')
        if any(x['split'] != 'heldout' for x in manifest['family_registry'].values()):
            raise ValueError('A source family is not registered as heldout.')
        for family, versions in manifest['documents'].items():
            if family not in manifest['family_registry'] or set(versions) != {'base', 'guidance', 'formatting'}:
                raise ValueError('Campaign documents differ from the registered families.')
            for variant, document in versions.items():
                expected = manifest['family_registry'][family]['variant_hashes'][variant]
                if document['sha256'] != expected or hashlib.sha256(document['text'].encode()).hexdigest() != expected:
                    raise ValueError('Registered document changed: ' + family + '/' + variant)

        registered = {trial['id']: trial for trial in manifest['trials']}
        if len(registered) != len(manifest['trials']):
            raise ValueError('Duplicate registered trial.')
        rows = {row['id']: row for row in evaluation['episodes']}
        if set(rows) != set(registered):
            raise ValueError('Evaluation omitted or added a trial.')
        episodes = []
        for identity, trial in registered.items():
            directory = root / 'trials' / identity
            outcome = sealed(directory / 'outcome.json')
            transcript = (directory / 'steps.json').read_bytes()
            if (outcome['trial'] != trial or outcome['manifest_sha256'] != manifest['sha256']
                    or outcome['transcript_sha256'] != hashlib.sha256(transcript).hexdigest()):
                raise ValueError('Raw trial differs from registration: ' + identity)
            transcript_data = json.loads(transcript)
            steps = transcript_data['steps']
            row = rows[identity]
            if any(row[key] != value for key, value in {
                'family': trial['family'], 'variant': trial['variant'], 'seed': trial['seed'],
                'final_pass': outcome['final']['passed'], 'exit': outcome['exit'],
                'transcript_sha256': outcome['transcript_sha256'],
            }.items()):
                raise ValueError('Evaluation disagrees with a raw trial: ' + identity)
            states = [outcome['before']['state']]
            for step in steps:
                state = (step.get('observed') or {}).get('state', states[-1])
                states.append('unknown' if state == 'observer_error' else state)
            if outcome['exit'] != 'LimitsExceeded':
                states[-1] = 'completed' if outcome['final']['passed'] is True else 'stopped'
            if row['states'] != states:
                raise ValueError('Evaluation changed a recorded journey: ' + identity)
            episodes.append({**row, 'error_type': transcript_data.get('error_type'), 'steps': [
                {'command': step.get('command', ''), 'returncode': step.get('returncode'),
                 'state': (step.get('observed') or {}).get('state', 'unobserved')}
                for step in steps], 'checks': outcome['final']['checks']})

        # Recompute the registered final-correctness score from raw checked outcomes.
        grouped = defaultdict(list)
        for row in episodes:
            grouped[row['family']].append(row)
        family_scores = []
        for family, group in grouped.items():
            base = [row for row in group if row['variant'] == 'base']
            base_rate = sum(row['final_pass'] is True for row in base) / len(base)
            variants = []
            for variant in ('guidance', 'formatting'):
                observed = [row for row in group if row['variant'] == variant]
                prediction = lock['predictions'][variant]
                point = prediction['supported_goal_probability'] + .5 * prediction['unsupported_mass']
                variants.append((
                    sum((point - int(row['final_pass'] is True)) ** 2 for row in observed) / len(observed),
                    sum((base_rate - int(row['final_pass'] is True)) ** 2 for row in observed) / len(observed),
                    sum((model['pooled_outcome_probability'] - int(row['final_pass'] is True)) ** 2 for row in observed) / len(observed),
                ))
            family_scores.append(tuple(sum(pair[i] for pair in variants) / 2 for i in range(3)))
        calculated = [sum(score[i] for score in family_scores) / len(family_scores) for i in range(3)]
        reported = [evaluation[key] for key in ('brier', 'no_change_brier', 'pooled_brier')]
        if any(not math.isclose(a, b, abs_tol=1e-12) for a, b in zip(calculated, reported)):
            raise ValueError('Evaluation score disagrees with raw outcomes.')

        return {
            'kind': 'recorded-heldout-study', 'status': 'complete',
            'labels': ['SIMULATED', 'HOSTED', 'UNCALIBRATED'],
            'identities': {'manifest': manifest['sha256'], 'forecast': lock['sha256'],
                           'model': model['sha256'], 'evaluation': evaluation['sha256']},
            'task': manifest['task'], 'tasks': manifest['tasks'],
            'training': {'episodes': len(model['training_ids']), 'families': model['training_families']},
            'population': {'model': manifest['population']['model'],
                'harness': manifest['population']['harness'], 'seeds': manifest['population']['seeds'],
                'step_limit': manifest['population']['step_limit'], 'image_id': manifest['population']['image_id']},
            'families': manifest['family_registry'], 'documents': manifest['documents'],
            'forecast': lock['predictions'], 'results': evaluation['families'],
            'scores': dict(zip(('brier', 'no_change_brier', 'pooled_brier'), reported)),
            'episodes': episodes, 'controller': result['controller'],
            'finished_at': result['finished_at'],
            'limits': {'inference': evaluation['inference'], 'cost_scope': evaluation['cost_scope'],
                       'model_scope': 'The frozen model uses intervention categories, state and call budget. It does not read arbitrary patches. All three forecasts abstain.'},
        }

    def read(self):
        current = self._read()
        if current['identities'] != self.snapshot['identities']:
            raise ValueError('Campaign changed after the workspace opened.')
        return current
