"""Explicit real-backend comparison. Default is a local no-spend readiness check.

Never imports stand-ins. A control mismatch stops before the proposed document.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from sim.adapters import tavily, tokenfactory
from sim.adapters.nebius import NebiusSandbox
from sim.adapters.readiness import readiness, check_access
from sim.counterfactual import delta
from sim.doc import load_target, sha256_bytes
from sim.model_policy import ModelPolicy
from sim.grounding import DisabledGrounding
from sim.errors import NoKey
from sim.run import execute, write, dumps
from sim.validate import check, semantic


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m sim.submission')
    ap.add_argument('--check-access', action='store_true', help='read-only model and image metadata, no paid execution')
    ap.add_argument('--run', action='store_true', help='explicitly authorize billable real service calls')
    ap.add_argument('--with-tavily', action='store_true', help='also authorize optional billable Tavily grounding during --run')
    ap.add_argument('--n', type=positive, default=1)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--output', type=Path, help='new private output directory; required for --run')
    ap.add_argument('--base-doc', type=Path, help='optional complete base section for the pinned dotenv goal')
    ap.add_argument('--head-doc', type=Path, help='optional complete proposed section for the same pinned goal')
    a = ap.parse_args(argv)
    if bool(a.base_doc) != bool(a.head_doc):
        ap.error('use both --base-doc and --head-doc')
    if a.run and a.output is None:
        ap.error('--run requires --output to a new private directory')
    if a.run and a.check_access:
        ap.error('--check-access cannot be combined with --run')
    status = readiness()
    if a.with_tavily:
        status['optional_services'] = {'tavily': 'requested; key required; search runs only with --run'}
        try:
            tavily.load_key()
        except NoKey as exc:
            status['missing'].append(str(exc))
            status['ready'] = False
    print(json.dumps(status, indent=2))
    access = None
    if a.check_access or (a.run and status['ready']):
        access = check_access()
        print(json.dumps(access, indent=2))
    if not status['ready']:
        print('Submission run refused: prerequisites missing; no paid execution started.')
        return 1
    if access is not None:
        usable = (access['token_factory'].get('metadata_access') is True
                  and access['token_factory'].get('selected_model_available') is True
                  and access['sandboxes'].get('image_metadata_access') is True)
        if not usable:
            print('Submission run refused: model or image metadata access failed. No paid execution started.')
            return 1
    if not a.run:
        return 0
    if a.output.exists():
        print('Refused: output directory already exists; choose a new directory.')
        return 1
    target = load_target()
    base_doc = a.base_doc.read_text() if a.base_doc else target.base_section()
    if a.head_doc:
        head_doc = a.head_doc.read_text()
        patch = {'file': a.head_doc.name, 'sha256': sha256_bytes(head_doc.encode())}
    else:
        patch_path = target.dir / 'patches' / 'explicit-steps.md'
        head_doc = patch_path.read_text()
        patch = {'file': patch_path.name, 'sha256': sha256_bytes(head_doc.encode())}
    if not base_doc.strip() or not head_doc.strip():
        print('Refused: documents must be nonempty.')
        return 1
    a.output.mkdir(parents=True, mode=0o700)
    lock = Lock()
    def record(row):
        with lock, (a.output / 'services.jsonl').open('a') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **row}, sort_keys=True) + '\n')
    print('SIMULATED. Real backends selected. Hosted cost unknown, not zero. '
          'Documents, commands and the pinned wheel will reach configured providers. '
          'Remote snapshots can persist. Population uses model-directed readers; coding agents are not run.')
    try:
        # Sandbox metadata check before paying for search or inference.
        box = NebiusSandbox(record=record)
        box.checkpoint(target.wheel, target.meta["wheel_sha256"])
        client = tokenfactory.client()
        client.record = record
        grounding = (tavily.TavilyGrounding(f"{target.meta['name']} quickstart problems",
                                           receipts_path=a.output / 'grounding.jsonl')
                     if a.with_tavily else DisabledGrounding())
        if not a.with_tavily:
            record({'service': 'grounding', 'status': 'not_requested', 'runtime_call': False})
        policy = ModelPolicy(name='TOKEN-FACTORY', client=client, runtime='token-factory', seed=a.seed)
        runs = {}
        for arm, section, change in [('base', base_doc, None), ('control', base_doc, None), ('head', head_doc, patch)]:
            run, timing = execute(target=target, section=section, patch=change, seed=a.seed, n=a.n,
                                  policy=policy, sandbox=box, grounding=grounding, workers=1)
            problems = check(run) + semantic(run)
            if problems:
                raise ValueError('run schema or semantic validation failed')
            write(run, a.output / f'{arm}.json')
            (a.output / f'{arm}.timing.json').write_text(dumps(timing))
            runs[arm] = run
            if arm == 'control' and dumps(runs['base']) != dumps(run):
                print('Control differs from baseline. Stopped before head; no delta is written.')
                return 1
        digest = sha256_bytes(dumps(runs['base']).encode())
        result = delta(runs['base'], runs['head'], base_file='base.json', head_file='head.json',
                       base_sha=digest, control_sha=digest)
        (a.output / 'delta.json').write_text(dumps(result))
        print(f"Comparison saved in {a.output}. SIMULATED; magnitude uncalibrated.")
        return 0
    except Exception as exc:
        # SDK/server messages can include request text, URLs or credentials.
        # Preserve only the error class, and never retry billable actions here.
        record({'event': 'failed', 'error_type': type(exc).__name__})
        print(f'Real-backend run stopped ({type(exc).__name__}). Check provider access, image prerequisites and service records. No automatic retry.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
