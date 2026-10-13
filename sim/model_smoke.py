"""A single explicitly authorized provider call; default is a no-network preview.

This exercises the app's ChatClient, not a population or product-effect study.
"""
import argparse
import hashlib
import json
from pathlib import Path
from sim.adapters import tokenfactory
from sim.adapters.openai_compat import ChatClient

MODEL = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
MESSAGES = [{'role': 'user', 'content': 'Reply with exactly OK.'}]
MAX_TOKENS = 256


def preview():
    request = {'model': MODEL, 'messages': MESSAGES, 'temperature': 0.0,
               'seed': 7, 'max_tokens': MAX_TOKENS}
    return {'endpoint': tokenfactory.BASE_URL+'/chat/completions',
            'request': request,
            'request_sha256': hashlib.sha256(json.dumps(request).encode()).hexdigest(),
            'request_bytes': len(json.dumps(request).encode()),
            'max_inference_requests': 1, 'automatic_retries': 0,
            'exposure': 'Only the fixed public prompt above, API credential in Authorization, and normal connection metadata. No project files, tools, Docker, history or source upload.',
            'claim_limit': 'Adapter response/model identity only. No comparison, agent task completion or predictive validity.',
            'cost_projection': {'currency': 'USD', 'price_checked': '2026-10-08',
                'input_per_million': 0.06, 'output_per_million': 0.24,
                'input_token_planning_allowance': 2048,
                'output_token_request_cap': MAX_TOKENS,
                'planning_cost': 0.00018432,
                'context_input_upper_allowance': 262144,
                'context_allowance_cost': 0.01579008,
                'note': 'Input allowances are not measured token counts. Costs assume published per-token rates and provider enforcement of max_tokens; no provider billing cap is configured.',
                'source': 'https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference'}}


def read_receipt(path):
    if not path.is_file():
        return {'state': 'not_run', 'plan': preview()}
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    final = rows[-1]
    response = next((row for row in rows if row.get('service') == 'chat' and row.get('identity_status') == 'matched'), None)
    if final.get('event') == 'result':
        usage = final['usage']
        prompt = usage.get('prompt_tokens')
        completion = usage.get('completion_tokens')
        estimated = (round(prompt * 0.06 / 1_000_000 + completion * 0.24 / 1_000_000, 10)
                     if isinstance(prompt, int) and isinstance(completion, int) else None)
        return {'state': 'complete', 'model': response.get('model') if response else None,
                'request_id': response.get('request_id') if response else None,
                'usage': usage, 'estimated_usd': estimated, 'reply': final['reply'],
                'receipt': str(path), 'scope': 'One real provider connection check. No agent or product trial.'}
    return {'state': 'stopped' if final.get('event') == 'stopped' else 'running',
            'error_type': final.get('error_type'), 'receipt': str(path),
            'scope': 'One provider connection check; billing status may be unknown.'}


def run(path):
    plan = preview()
    with path.open('x', encoding='utf-8') as receipt:
        path.chmod(0o600)
        def record(row):
            receipt.write(json.dumps(row, sort_keys=True)+'\n'); receipt.flush()
        record({'event': 'authorized_plan', **plan})
        try:
            client = ChatClient(base_url=tokenfactory.BASE_URL, model=MODEL, label='RUNTIME',
                                api_key=tokenfactory.load_key(), record=record)
            reply = client.chat(MESSAGES, temperature=0.0, seed=7, max_tokens=MAX_TOKENS)
            record({'event': 'result', 'model_identity': 'matched', 'usage': reply.usage,
                    'reply': reply.text[:512], 'exact_OK': reply.text.strip() == 'OK',
                    'nonempty': bool(reply.text.strip())})
        except Exception as exc:
            record({'event': 'stopped', 'error_type': type(exc).__name__})
    return read_receipt(path)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='authorize exactly one billable inference attempt')
    parser.add_argument('--output', type=Path, help='new private receipt file')
    args = parser.parse_args(argv)
    plan = preview()
    if not args.run:
        print(json.dumps(plan, indent=2)); return 0
    if args.output is None: parser.error('--run requires --output')
    result = run(args.output)
    print(json.dumps(result))
    return 0 if result['state'] == 'complete' and result['reply'].strip() == 'OK' else 1


if __name__ == '__main__':
    raise SystemExit(main())
