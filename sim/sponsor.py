"""Explicit sponsor selection shared by CLI and the private workspace."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from sim.adapters import tokenfactory, nebius
from sim.adapters.readiness import readiness, check_access
from sim.adapters.coding_agent import CodingAgents, require_harness
from sim.adapters.scenario import NebiusScenarioSandbox
from sim.model_policy import ModelPolicy
from sim.grounding import DisabledGrounding


def selection():
    model = os.environ.get(tokenfactory.MODEL_ENV, '').strip()
    if not model:
        raise ValueError('Set TOKEN_FACTORY_MODEL to the exact account model ID before sponsor preview.')
    return {'model': model, 'image': nebius.configured_image()}


def prerequisites(agents=0):
    state = readiness()
    if agents:
        try: require_harness()
        except RuntimeError as e: state['missing'].append(str(e))
    state['ready'] = not state['missing']
    return state


def require_ready(config):
    if selection() != config['sponsor']:
        raise ValueError('Sponsor model or image changed since preview. Prepare a new preview.')
    state = prerequisites(config['agents'])
    if not state['ready']:
        raise ValueError('Sponsor prerequisites: ' + '; '.join(state['missing']))


def build(config, target, contract, output):
    require_ready(config)
    access = check_access()
    if not (access['token_factory'].get('metadata_access') is True
            and access['token_factory'].get('selected_model_available') is True
            and access['sandboxes'].get('image_metadata_access') is True):
        raise ValueError('Sponsor metadata access failed. Run python -m sim.submission --check-access; no paid operation started.')
    lock = Lock()
    def record(row):
        with lock, (Path(output) / 'services.jsonl').open('a') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **row}, sort_keys=True)+'\n')
    sandbox = NebiusScenarioSandbox(contract, output, record=record)
    sandbox.checkpoint_target(target)
    client = tokenfactory.client(); client.record = record
    policy = ModelPolicy(name='TOKEN-FACTORY', client=client, runtime='token-factory', seed=config['seed'])
    agents = CodingAgents(k=config['agents'], client=client, seed=config['seed']) if config['agents'] else None
    grounding = DisabledGrounding()
    record({'service': 'grounding', 'status': 'not_requested', 'runtime_call': False})
    return policy, agents, sandbox, grounding, 1
