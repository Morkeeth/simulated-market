"""Hosted Token Factory inference with an explicitly LOCAL Docker scenario.

Docker containers have no network and receive no provider credential. Model
requests leave the host and can include source exposed in agent command output.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from sim.adapters import tokenfactory
from sim.adapters.readiness import check_access
from sim.adapters.coding_agent import CodingAgents, require_harness
from sim.errors import NoKey
from sim.grounding import DisabledGrounding
from sim.model_policy import ModelPolicy
from sim.scenario import ScenarioSandbox
from sim.image_review import SUPPORTED_IMAGE, validate as validate_image_review


def require_supported_image(contract):
    if contract.get('image_id') == SUPPORTED_IMAGE:
        return {'image_id': SUPPORTED_IMAGE, 'status': 'pinned_public_base'}
    if contract.get('image_review') is not None:
        return validate_image_review(contract['image_review'], contract.get('image_id'))
    else:
        raise ValueError('Hosted Token Factory with local Docker supports only reviewed images or '
                         'python@'+SUPPORTED_IMAGE+'. Custom images are not uploaded or substituted. '
                         'Use a local-only trial or provide an explicit image_review manifest.')


def selection():
    model = os.environ.get(tokenfactory.MODEL_ENV, '').strip()
    if not model:
        raise ValueError('Set TOKEN_FACTORY_MODEL to the exact account model ID before preview.')
    return {'model': model}


def prerequisites(agents=0):
    missing = []
    try: tokenfactory.load_key()
    except NoKey as exc: missing.append(str(exc))
    try: selected = selection()
    except ValueError as exc:
        missing.append(str(exc)); selected = {'model': ''}
    if agents:
        try: require_harness()
        except RuntimeError as exc: missing.append(str(exc))
    return {'ready': not missing, 'missing': missing,
            'model_requirement': tokenfactory.model_requirement(selected['model']),
            'supported_base_image': 'python@'+SUPPORTED_IMAGE,
            'execution': 'none; cached Docker image is checked when preparing the scenario',
            'access': 'unverified; no hosted calls made'}


def require_ready(config):
    if selection() != config['sponsor']:
        raise ValueError('Token Factory model changed since preview. Prepare a new preview.')
    state = prerequisites(config['agents'])
    if not state['ready']:
        raise ValueError('Token Factory prerequisites: ' + '; '.join(state['missing']))


def build(config, target, contract, output):
    image_review = require_supported_image(contract)
    require_ready(config)
    access = check_access(include_sandbox=False)['token_factory']
    if not (access.get('metadata_access') is True and access.get('selected_model_available') is True):
        raise ValueError('Token Factory model metadata access failed; no inference started.')
    lock = Lock()
    def record(row):
        with lock, (Path(output) / 'services.jsonl').open('a') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **row}, sort_keys=True)+'\n')
    record({'service': 'image_review', **image_review})
    sandbox = ScenarioSandbox(contract, output)
    checkpoint, _ = sandbox.checkpoint_target(target)
    record({'service': 'sandbox', 'backend': 'docker', 'label': 'LOCAL',
            'checkpoint_image_id': checkpoint, 'hosted_execution': False})
    client = tokenfactory.client(); client.record = record
    policy = ModelPolicy(name='TOKEN-FACTORY', client=client, runtime='token-factory', seed=config['seed'])
    agents = CodingAgents(k=config['agents'], client=client, seed=config['seed']) if config['agents'] else None
    record({'service': 'grounding', 'status': 'not_requested', 'runtime_call': False})
    return policy, agents, sandbox, DisabledGrounding(), 1
