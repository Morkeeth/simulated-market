"""Stdio MCP bridge to a private loopback NVIDIA swarm workspace.

Set SWARM_WORKSPACE_URL and SWARM_WORKSPACE_TOKEN. This process only calls the
two agent-facing API routes; it does not hold a provider credential.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen


TOOLS = [
    {'name': 'start_swarm', 'description': 'Start a registered public PR trial with explicit paid-run consent, or get an unsupported reason.',
     'inputSchema': {'type': 'object', 'properties': {
         'pr_url': {'type': 'string'}, 'consent': {'type': 'string', 'description': 'Required exact phrase for a paid run: run this paid local swarm trial'}},
         'required': ['pr_url'], 'additionalProperties': False}},
    {'name': 'read_swarm_result', 'description': 'Read current status and observed outcomes for a run ID returned by start_swarm.',
     'inputSchema': {'type': 'object', 'properties': {'run_id': {'type': 'string'}},
                     'required': ['run_id'], 'additionalProperties': False}},
]


def request(method, path, payload=None):
    origin = os.environ.get('SWARM_WORKSPACE_URL', '').rstrip('/')
    token = os.environ.get('SWARM_WORKSPACE_TOKEN', '')
    if not origin.startswith('http://127.0.0.1:') or not token:
        raise ValueError('Set a private 127.0.0.1 workspace URL and token.')
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'X-Workspace-Token': token}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    call = Request(origin + path, data=data, headers=headers, method=method)
    with urlopen(call, timeout=300) as response:
        return json.load(response)


def handle(message):
    method = message.get('method')
    if method == 'notifications/initialized':
        return None
    if method == 'initialize':
        return {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'nvidia-local-swarm', 'version': '0.1.0'}}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        params = message.get('params') or {}
        name, args = params.get('name'), params.get('arguments') or {}
        if name == 'start_swarm':
            path, verb, payload = '/api/swarm/start', 'POST', args
        elif name == 'read_swarm_result':
            path, verb, payload = '/api/swarm/result/' + args['run_id'], 'GET', None
        else:
            raise ValueError('Unknown tool.')
        result = request(verb, path, payload)
        return {'content': [{'type': 'text', 'text': json.dumps(result, sort_keys=True)}],
                'isError': False}
    raise ValueError('Unknown MCP method.')


def main():
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line)
            if 'id' not in message:
                continue
            reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': handle(message)}
        except Exception as error:
            reply = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                     'error': {'code': -32603, 'message': str(error)[:300]}}
        sys.stdout.write(json.dumps(reply, separators=(',', ':')) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
