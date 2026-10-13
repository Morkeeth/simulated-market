"""Conservative local spending stop for the authorized NVIDIA live trial.

This is a controller account, not a provider invoice. Missing usage keeps the
full reservation charged against the ceiling so another run cannot spend it.
"""
from __future__ import annotations

from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path

ROOT = Path.home() / '.local/state/sim-provider'
PRIOR = ROOT / 'hosted-spend.json'
RECORD = ROOT / 'nvidia-live-cost.json'
LIMIT = Decimal('10')
MODEL = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
INPUT_RATE = Decimal('0.06')
OUTPUT_RATE = Decimal('0.24')
PRICE_SOURCE = 'https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference'
MAX_PROMPT_BYTES = 60000
MAX_OUTPUT_TOKENS = 1024


def money(value):
    return Decimal(str(value))


def prior_total():
    return sum((money(row['committed_usd']) for row in json.loads(PRIOR.read_text())['runs']), Decimal(0))


def worst_case(calls):
    if type(calls) is not int or calls < 1 or calls > 600:
        raise ValueError('Choose a bounded positive model-call count.')
    # Ten times the published rate is reserved. UTF-8 bytes upper-bound
    # ordinary input token counts; the output has a provider request cap.
    return Decimal(calls) * (Decimal(MAX_PROMPT_BYTES) * INPUT_RATE +
                              Decimal(MAX_OUTPUT_TOKENS) * OUTPUT_RATE) * 10 / Decimal(1_000_000)


def projected(calls, model):
    if model != MODEL:
        raise ValueError('The USD stop is priced only for the exact registered Nemotron Nano model.')
    reserve = worst_case(calls)
    return {'limit_usd': float(LIMIT), 'prior_controller_usd': float(prior_total()),
            'reserved_upper_usd': float(reserve), 'price_source': PRICE_SOURCE,
            'price_basis': '10 times listed token rates; not a provider billing cap or invoice'}


def _locked(update):
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(RECORD, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        raw = stream.read()
        data = json.loads(raw) if raw else {'schema': 'nvidia-live-cost/1', 'runs': {}}
        value = update(data)
        stream.seek(0)
        stream.truncate()
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
        return value


def reserve(identifier, calls, model):
    plan = projected(calls, model)
    amount = money(plan['reserved_upper_usd'])
    def write(data):
        if identifier in data['runs']:
            raise ValueError('This hosted trial already has a cost reservation.')
        committed = sum((money(row['accounted_usd']) for row in data['runs'].values()), Decimal(0))
        if prior_total() + committed + amount > LIMIT:
            raise ValueError('NVIDIA hosted inference would exceed the authorized USD 10 controller ceiling.')
        data['runs'][identifier] = {'model': model, 'max_calls': calls,
                                   'reserved_upper_usd': float(amount),
                                   'accounted_usd': float(amount), 'status': 'reserved',
                                   'price_source': PRICE_SOURCE}
        return {**plan, 'accounted_total_upper_usd': float(prior_total() + committed + amount)}
    return _locked(write)


def settle(identifier, usage, complete):
    def write(data):
        row = data['runs'][identifier]
        prompt = usage.get('prompt_tokens')
        output = usage.get('completion_tokens')
        if complete and type(prompt) is int and type(output) is int and prompt >= 0 and output >= 0:
            measured = (Decimal(prompt) * INPUT_RATE + Decimal(output) * OUTPUT_RATE) / Decimal(1_000_000)
            if measured > money(row['reserved_upper_usd']):
                row['status'] = 'over_reservation_stop'
                row['accounted_usd'] = float(measured)
                row['usage'] = {'prompt_tokens': prompt, 'completion_tokens': output}
                row['stop_reason'] = 'Provider usage exceeded the conservative reservation; stop further hosted runs.'
                return dict(row)
            row['accounted_usd'] = float(measured)
            row['status'] = 'usage_accounted'
            row['usage'] = {'prompt_tokens': prompt, 'completion_tokens': output}
        else:
            row['status'] = 'unknown_usage_reservation_held'
        return dict(row)
    return _locked(write)
