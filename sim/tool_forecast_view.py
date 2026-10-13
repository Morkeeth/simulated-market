"""Read-only workspace references to controller-owned forecast batches."""
from pathlib import Path
import secrets

from sim import tool_trial


def review(reference):
    from sim.tool_forecast_runner import review as verify
    data = verify(reference['path'], reference['adapter'])
    if data['contract'] != reference['contract']:
        raise ValueError('Forecast belongs to a different frozen trial.')
    return data


def open_forecast(ws, body):
    from sim.tool_workspace import directory, result
    from sim.tool_forecast import digest
    with ws.lock:
        raw = body.get('path')
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('Choose a local controller forecast receipt directory.')
        source = Path(raw).expanduser().resolve()
        if not source.is_dir():
            raise ValueError('The local forecast directory does not exist.')
        manifest = tool_trial.read(source/'adapter.json')
        reference = {'path':str(source), 'adapter':digest(manifest), 'contract':manifest['identity']['trial'],
                     'scope':'Read-only reference to a controller batch; opening it does not execute or copy an attempt.'}
        review(reference)
        root = ws.root/'tools';root.mkdir(exist_ok=True, mode=0o700)
        for existing in root.iterdir():
            if (existing/'forecast-reference.json').exists():
                prior = tool_trial.read(existing/'forecast-reference.json')
                if prior['adapter'] == reference['adapter'] and prior['path'] == reference['path']:
                    return result(ws,existing.name)
        id = secrets.token_hex(12);target=directory(ws,id);target.mkdir(mode=0o700)
        tool_trial.dump(target/'forecast-reference.json',reference)
        if body.get('decisionProtocol'):
            from sim.tool_decision_protocol import initialize
            trial_path=source/'trial'
            initialize(ws,id,tool_trial.read(trial_path/'contract.json'),tool_trial.read(trial_path/'state.json'),review(reference),started=(trial_path/'started.json').exists())
        return result(ws,id)
