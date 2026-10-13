"""Small agent-facing entry to the local, registered swarm trial."""
from __future__ import annotations

import time

from sim import public_pr_trial, tool_trial, tool_workspace

CONSENT = 'run this paid local swarm trial'


def start(ws, body):
    """Start one registered public PR; unknown PRs never trigger inference."""
    url = public_pr_trial.canonical(body.get('pr_url'))
    found = public_pr_trial.inspect(ws, {'url': url})
    if found['status'] == 'recorded_result':
        return {'status': 'recorded_result', 'pr_url': url,
                'run_id': found['trial']['id'], 'result': summary(found['trial'])}
    if found['status'] != 'registered_unrun':
        return {'status': 'unsupported', 'pr_url': url,
                'reason': found.get('reason', 'No independent task and checker registered.'),
                'model_calls': 0}
    if body.get('consent') != CONSENT:
        return {'status': 'needs_consent', 'pr_url': url,
                'required_consent': CONSENT,
                'reason': 'A registered run makes paid hosted Nemotron calls and executes the task in local Docker.',
                'model_calls': 0}
    if not ws.allow_sponsor:
        return {'status': 'blocked', 'pr_url': url,
                'reason': 'Start the private workspace with --allow-sponsor.', 'model_calls': 0}
    with ws.lock:
        existing = None
        tools = ws.root / 'tools'
        if tools.exists():
            for path in tools.iterdir():
                receipt = path / 'public-url.json'
                if path.is_dir() and receipt.exists() and tool_trial.read(receipt).get('url') == url:
                    existing = tool_workspace.result(ws, path.name)
                    break
        if existing and existing['state']['status'] != 'prepared':
            return {'status': 'existing_' + existing['state']['status'],
                    'pr_url': url, 'run_id': existing['id'],
                    'result_path': '/api/swarm/result/' + existing['id'],
                    'reason': 'This private workspace already prepared this exact PR; no second run was launched.'}
        prepared = existing or public_pr_trial.prepare(ws, {'url': url})
    run_id, expected = prepared['id'], prepared['contract']['sha256']
    checked = prepared
    for _ in range(90):
        state = (checked.get('preflight') or {}).get('state') or {}
        if state.get('status') in ('complete', 'failed'):
            break
        time.sleep(2)
        checked = tool_workspace.result(ws, run_id)
    state = (checked.get('preflight') or {}).get('state') or {}
    if state.get('status') != 'complete' or not state.get('passed'):
        return {'status': 'blocked', 'pr_url': url, 'run_id': run_id,
                'reason': 'The independent preflight did not pass; no model request was made.',
                'preflight_status': state.get('status'), 'model_calls': 0}
    preview = tool_workspace.sponsor_preview(ws, {'id': run_id, 'expected': expected})
    digest = preview['sponsor']['preview']['sha256']
    launch = tool_workspace.start(ws, {'id': run_id, 'expected': expected,
                                       'policy': 'tokenfactory-shell-agent',
                                       'sponsorPreview': digest, 'sponsorConsent': digest})
    return {'status': launch['status'], 'pr_url': url, 'run_id': run_id,
            'result_path': '/api/swarm/result/' + run_id,
            'scope': 'One registered task and independent checker; local Docker, hosted Nemotron.'}


def summary(trial):
    state = trial['state']
    episodes = state.get('episodes', [])
    story = None
    if state.get('status') == 'complete' and episodes:
        base = [e for e in episodes if e.get('arm') == 'base']
        head = [e for e in episodes if e.get('arm') == 'head']
        story = (f"Before the change, {sum(e.get('completed') is True for e in base)} of {len(base)} agents finished; "
                 f"after it, {sum(e.get('completed') is True for e in head)} of {len(head)} finished. "
                 'A separate controller checked each final task artifact. '
                 'These local attempts do not predict release safety or user impact.')
    return {'status': state.get('status'), 'model': state.get('model'),
            'provider_runtime_verified': state.get('provider_runtime_verified', False),
            'episodes': [{'arm': e.get('arm'), 'status': e.get('status'),
                          'completed': e.get('completed'), 'model_calls': e.get('model_calls')}
                         for e in episodes],
            'usage_totals': state.get('usage_totals'),
            'controller_cost': state.get('cost', {}).get('controller_account'),
            'story': story, 'story_source': 'deterministic controller summary; guide follow-up is not live',
            'limits': 'This reports a local feasibility trial, not predicted PR safety or outside use.'}


def result(ws, run_id):
    trial = tool_workspace.result(ws, run_id)
    if not trial.get('publicPr'):
        raise ValueError('This is not a public PR swarm run.')
    return {'run_id': run_id, 'pr_url': trial['publicPr']['url'],
            'result': summary(trial)}
