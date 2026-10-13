"""Own documents, one frozen scenario, and a control before any reported change."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sim import ROOT
from sim.counterfactual import delta
from sim.doc import sha256_bytes
from sim.run import dumps, execute, write
from sim.scenario import NoGrounding, ScenarioSandbox, freeze, git, revision, safe_member
from sim.validate import check, semantic


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return n


def nonnegative(value):
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return n


def add_parser(sub):
    p = sub.add_parser('compare', help='compare your two docs in an explicit frozen scenario')
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--scenario', help='local JSON scenario contract')
    source.add_argument('--prepared', help='private frozen workspace snapshot')
    p.add_argument('--expected', help='exact reviewed snapshot digest')
    p.add_argument('--base-doc')
    p.add_argument('--head-doc')
    p.add_argument('--repo', help='alternative to doc files: local Git repo')
    p.add_argument('--base', help='base Git ref')
    p.add_argument('--head', help='head Git ref')
    p.add_argument('--doc', default='README.md', help='complete doc path at both Git refs')
    p.add_argument('--output', required=True, help='new directory outside this tool checkout')
    p.add_argument('--n', type=positive, default=24)
    p.add_argument('--agents', type=nonnegative, default=1, help='actual coding agents; 0 explicitly omits them')
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--backend', choices=['local', 'sponsor', 'tokenfactory-local'], default='local')
    p.add_argument('--allow-sponsor', action='store_true', help='authorize paid calls and transfer of reviewed source/docs')


def read_inputs(a):
    if a.repo:
        if a.base_doc or a.head_doc or not a.base or not a.head or not safe_member(a.doc):
            raise ValueError('Use --repo --base --head [--doc], without doc file arguments.')
        out = []
        for ref in (a.base, a.head):
            commit = revision(a.repo, ref)
            mode = git(a.repo, 'ls-tree', commit, '--', a.doc).split(b' ', 1)[0]
            if mode not in (b'100644', b'100755'):
                raise ValueError('Each doc must be a committed regular file.')
            raw = git(a.repo, 'show', commit + ':' + a.doc)
            out.append((raw, {'kind': 'git', 'commit': commit, 'path': a.doc}))
    else:
        if not a.base_doc or not a.head_doc or a.base or a.head:
            raise ValueError('Use both --base-doc and --head-doc, or --repo --base --head.')
        out = [(Path(p).read_bytes(), {'kind': 'file', 'name': Path(p).name}) for p in (a.base_doc, a.head_doc)]
    for raw, _ in out:
        if not raw.decode('utf-8').strip():
            raise ValueError('Input documents must be nonempty UTF-8 text.')
    return out


def summary(base, head, d):
    n = d['n']['value']
    local = 'LOCAL' in base['labels']
    local_model = base['backends']['model']['label'] != 'RUNTIME'
    lines = ['# Documentation comparison', '', ' · '.join(base['labels']), '',
             f"Scenario: {base['target']['name']}", f"Goal: {base['target']['goal']}", '',
             f"Direction among simulated readers: **{d['direction']}**.",
             f"Reached the goal: {d['base']['goal_reached']['value']}/{n} base; {d['head']['goal_reached']['value']}/{n} head.",
             f"Exact paired sign-test p = {d['paired']['p_value']['value']}. Size is uncalibrated.", '',
             ('The control matched the complete base run byte for byte, including agent commands and outcomes.'
              if any(p['id'] == 'coding_agents' for p in base['populations']) else
              'The control matched the complete reader base run byte for byte. Coding agents were not run.'),
             'Reader traits and weights are assumptions. No real users were observed. This is not market demand.',
             'The direction applies only to these docs, this frozen setup and these evaluators.', '',
             '| Step | Readers base | Readers head | Agents base | Agents head |',
             '|---|---:|---:|---:|---:|']
    bp = {p['id']: p for p in base['populations']}
    hp = {p['id']: p for p in head['populations']}
    for i, step in enumerate(base['steps']):
        cells = []
        for pid, pops in [('humans', bp), ('humans', hp), ('coding_agents', bp), ('coding_agents', hp)]:
            p = pops.get(pid)
            cells.append(f"{p['steps'][i]['reached']['value']}/{p['n']['value']}" if p else 'not run')
        lines.append('| ' + step['title'].replace('|', '\\|') + ' | ' + ' | '.join(cells) + ' |')
    for label, pops in [('base', bp), ('head', hp)]:
        if 'coding_agents' in pops:
            pop = pops['coding_agents']
            lines += ['', f"Coding agents on {label}: {pop['backend']['name']} ({pop['backend']['label']})."]
            for user in pop['users']:
                missed = user['dropped_at'] or 'none'
                lines.append(f"Agent {user['id']}: exit {user['exit_status']}; first unmet check: {missed}.")
                for entry in user['log']:
                    if entry['action'] == 'run':
                        command = entry['detail'].replace('`', "'").replace('\n', ' ')[:240]
                        lines.append(f"- Command (exit {entry['exit_code']}): `{command}`")
            lines.append('An agent submission is not a passed goal. A correct alternative path can fail a narrower evaluator; inspect both.')
    lines += ['', 'Source: steps and populations in base.json and head.json; paired statistics in delta.json.',
              ('Scripted readers follow fixed rules. Coding agents use the local model and may repair missing instructions.' if local_model else 'Token Factory directed readers and mini-swe-agent participants. Inspect individual commands; model responses are not real people.'),
              'Repeated deterministic agent paths are not independent evidence of a broader agent population.',
              'No search service ran; no related issues were assumed for your project.', '',
              '## Inspect and repeat', '',
              'Open viewer/index.html offline, then select base.json, head.json and delta.json from this directory.',
              'Read the commands, exit codes and output excerpts in each run. Actual inputs are base.md and head.md.',
              'inputs.json binds both documents to hashes and any resolved Git commits.',
              'scenario.json records the frozen source commit, file hashes, cached image id, setup and evaluators.',
              'checkpoint.json and each run record the exact immutable final checkpoint image id used for all forks.',
              ('source.tar holds only the explicitly allowed committed files. Docker is local; hosted inference, if selected, has unknown cost. Timing includes all selected backends.' if local else 'source.tar contains the reviewed committed allowlist sent to Nebius. Cost is unknown; timing includes remote requests, not isolated fork latency.'),
              'Use the original scenario and same frozen refs for a fresh comparison in a new output directory.', '']
    return '\n'.join(lines)


def cmd_compare(a):
    out = Path(a.output).resolve()
    server = None
    backend = getattr(a, 'backend', 'local')
    try:
        if out.is_relative_to(ROOT.resolve()):
            raise ValueError('Your output must be outside the tool checkout; project data stays separate.')
        if getattr(a, 'prepared', None):
            from sim.workspace_snapshot import restore
            target, contract, inputs, sources, config = restore(a.prepared, a.expected, out)
            a.n, a.agents, a.seed = config['n'], config['agents'], config['seed']
            backend = config.get('backend', 'local')
        else:
            config = {'n': a.n, 'agents': a.agents, 'seed': a.seed}
            if backend in ('sponsor', 'tokenfactory-local'):
                if not getattr(a, 'allow_sponsor', False):
                    raise ValueError('Sponsor execution is off. Review transfer and charges, then explicitly use --allow-sponsor.')
                from importlib import import_module
                adapter = import_module('sim.sponsor' if backend == 'sponsor' else 'sim.tokenfactory_local')
                selection, require_ready = adapter.selection, adapter.require_ready
                config.update(backend=backend, sponsor=selection())
                require_ready(config)
            inputs = read_inputs(a)
            # Fail before side effects if the contract is unsupported.
            from sim.scenario import load_contract
            load_contract(a.scenario)
            out.mkdir(parents=True, exist_ok=False)
            target, contract = (freeze(a.scenario, out, backend='sponsor', image_id=config['sponsor']['image'])
                                if backend == 'sponsor' else freeze(a.scenario, out))
            sources = {}
            for name, (raw, source) in zip(('base', 'head'), inputs):
                (out / (name + '.md')).write_bytes(raw)
                sources[name] = {**source, 'file': name + '.md', 'sha256': sha256_bytes(raw)}
            (out / 'inputs.json').write_text(dumps(sources))
        if backend in ('sponsor', 'tokenfactory-local'):
            if not getattr(a, 'allow_sponsor', False):
                raise ValueError('Sponsor execution is off; --allow-sponsor is required for the frozen sponsor preview.')
            print(f"SIMULATED. Sponsor model: {config['sponsor']['model']}. Cost unknown, not zero.", flush=True)
            print(f"{a.n} model-directed readers; {a.agents} mini-swe-agent participants. Reviewed source/docs reach providers.", flush=True)
            from importlib import import_module
            build = import_module('sim.sponsor' if backend == 'sponsor' else 'sim.tokenfactory_local').build
            policy, agents, sandbox, grounding, workers = build(config, target, contract, out)
        else:
            from sim.cli import make_agents, make_policy
            print(f"SIMULATED · LOCAL. Scenario: {target.meta['name']}. Goal: {target.meta['goal']}", flush=True)
            print(f"{a.n} scripted readers; {a.agents} actual local coding agents. Local stand-ins bill 0 USD.", flush=True)
            print('One frozen offline setup, base/control/head. No real users or search service.', flush=True)
            policy, server, workers = make_policy('scripted', a.seed)
            agents, server = make_agents(a.agents, a.seed, server)
            sandbox, grounding = ScenarioSandbox(contract, out), NoGrounding()
        checkpoint, recipe = sandbox.checkpoint_target(target)
        (out / 'checkpoint.json').write_text(dumps(recipe))
        common = dict(target=target, n=a.n, seed=a.seed, policy=policy, agents=agents,
                      sandbox=sandbox, grounding=grounding, workers=workers)
        runs = {}
        for name, raw, patch in [('base', inputs[0][0], None), ('control', inputs[0][0], None),
                                  ('head', inputs[1][0], {'file': 'head.md', 'sha256': sources['head']['sha256']})]:
            print(f'Running {name} ...', flush=True)
            run, timing = execute(section=raw.decode('utf-8'), patch=patch, **common)
            errors = check(run) + semantic(run)
            if errors:
                raise ValueError('Run validation failed: ' + '; '.join(errors[:8]))
            write(run, out / (name + '.json'))
            (out / (name + '.timing.json')).write_text(dumps(timing))
            runs[name] = run
            if name == 'control' and (out / 'base.json').read_bytes() != (out / 'control.json').read_bytes():
                raise ValueError('CONTROL FAILED: base and same-input rerun differ. No delta reported.')
        sha = sha256_bytes((out / 'base.json').read_bytes())
        d = delta(runs['base'], runs['head'], base_file='base.json', head_file='head.json', base_sha=sha, control_sha=sha)
        errors = check(d, 'delta.schema.json')
        if errors:
            raise ValueError('Delta validation failed: ' + '; '.join(errors))
        (out / 'delta.json').write_text(dumps(d))
        report = summary(runs['base'], runs['head'], d)
        (out / 'REPORT.md').write_text(report)
        shutil.copytree(ROOT / 'web', out / 'viewer')
        print(report)
        print(f'Results: {out}')
        return 0
    except (ValueError, OSError, RuntimeError) as e:
        print(f'Comparison refused: {e}' if backend == 'local' or isinstance(e, ValueError) else
              f'Sponsor comparison stopped ({type(e).__name__}). Check provider access and saved service records; no automatic rerun.')
        return 2
    finally:
        if server is not None:
            server.stop()
