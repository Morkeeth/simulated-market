"""Local prerequisites only. No inference, search, upload or sandbox operation."""
import os
from importlib.metadata import version, PackageNotFoundError
from sim.adapters import nebius, tokenfactory
from sim.errors import NoKey


def readiness():
    missing = []
    for module in (tokenfactory, nebius):
        try:
            module.load_key()
        except NoKey as exc:
            missing.append(str(exc))
    model = os.environ.get(tokenfactory.MODEL_ENV, '').strip()
    if not model:
        missing.append('Set TOKEN_FACTORY_MODEL to the exact model ID available to your account; use a Nemotron ID for sponsor evaluation.')
    try:
        nebius.configured_image()
    except NoKey as exc:
        missing.append(str(exc))
    try:
        installed = version('contree-sdk') == '0.3.6'
    except PackageNotFoundError:
        installed = False
    if not installed:
        missing.append('Install requirements-sponsor.txt in this Python environment.')
    return {'ready': not missing, 'missing': missing,
            'access': 'unverified; local configuration is not account entitlement',
            'model_requirement': tokenfactory.model_requirement(model),
            'optional_services': {'tavily': 'not requested; no key required'},
            'execution': 'none; readiness does not make service calls'}


def check_access(*, include_sandbox=True):
    """Read-only models/image metadata. Never performs inference/search/import/run."""
    import json
    import urllib.request
    import urllib.error
    rows = {}
    try:
        key = tokenfactory.load_key()
        request = urllib.request.Request(tokenfactory.BASE_URL + '/models', headers={'Authorization': 'Bearer ' + key})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        model = os.environ.get(tokenfactory.MODEL_ENV, '').strip()
        available = any(row.get('id') == model for row in payload['data']) if model else False
        rows['token_factory'] = {'metadata_access': True, 'selected_model_available': available,
                                 'inference_verified': False,
                                 'nvidia_nemotron_candidates': sorted(row['id'] for row in payload['data']
                                     if isinstance(row, dict) and isinstance(row.get('id'), str)
                                     and tokenfactory.model_requirement(row['id'])['nvidia_nemotron_candidate'])}
    except NoKey:
        rows['token_factory'] = {'metadata_access': 'not checked', 'reason': 'key missing'}
    except urllib.error.HTTPError as exc:
        rows['token_factory'] = {'metadata_access': False, 'http_status': exc.code}
    except Exception as exc:
        rows['token_factory'] = {'metadata_access': False, 'error_type': type(exc).__name__}
    if not include_sandbox:
        rows['sandboxes'] = {'image_metadata_access': 'not requested', 'execution_verified': False}
        rows['tavily'] = {'search_verified': False, 'reason': 'not requested'}
        return rows
    try:
        box = nebius.NebiusSandbox()
        box.preflight()
        rows['sandboxes'] = {'image_metadata_access': True, 'execution_verified': False}
    except NoKey as exc:
        rows['sandboxes'] = {'image_metadata_access': 'not checked', 'reason': str(exc)}
    except Exception as exc:
        rows['sandboxes'] = {'image_metadata_access': False, 'error_type': type(exc).__name__}
    rows['tavily'] = {'search_verified': False, 'reason': 'search is billable; not part of this check'}
    return rows
