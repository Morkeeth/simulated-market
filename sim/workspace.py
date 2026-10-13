"""Loopback-only, single-user workspace for the fixed offline comparison command."""
from __future__ import annotations
import argparse
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlsplit
from sim import ROOT
from sim.compare import read_inputs
from sim.doc import sha256_bytes
from sim.run import dumps
from sim.scenario import freeze, load_contract
from sim.workspace_snapshot import seal, verify


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(dumps(data))
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load(path):
    return json.loads(path.read_text())


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{24}', value):
        raise ValueError('Unknown comparison.')
    return value


class Workspace:
    def __init__(self, root, allow_agents=False, allow_sponsor=False, study_dir=None, study_model=None):
        self.root = Path(root).expanduser().resolve()
        if self.root.is_relative_to(ROOT.resolve()):
            raise ValueError('Private workspace must be outside the tool checkout.')
        if self.root.exists() and any(self.root.iterdir()):
            if not ((self.root / '.token').is_file() and (self.root / 'drafts').is_dir() and (self.root / 'jobs').is_dir()):
                raise ValueError('Choose an empty directory or an existing comparison workspace; unrelated directories are not modified.')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.allow_agents = allow_agents
        self.allow_sponsor = allow_sponsor
        self.lock = threading.RLock()
        self.guard = (self.root / '.lock').open('a')
        fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        token = self.root / '.token'
        if not token.exists():
            token.write_text(secrets.token_urlsafe(32)); token.chmod(0o600)
        self.token = token.read_text()
        (self.root / 'drafts').mkdir(exist_ok=True, mode=0o700)
        (self.root / 'jobs').mkdir(exist_ok=True, mode=0o700)
        if bool(study_dir) != bool(study_model):
            raise ValueError('A recorded study needs both its campaign directory and frozen model.')
        if study_dir:
            from sim.study import HeldoutStudy
            self.study = HeldoutStudy(study_dir, study_model)
        else:
            self.study = None

    def run_model_smoke(self):
        if not self.allow_sponsor:
            raise ValueError('Start the workspace with --allow-sponsor for a real provider call.')
        from sim.model_smoke import run
        return run(self.root / 'model-smoke.jsonl')

    def study_decisions(self):
        if not self.study: raise ValueError('No recorded study was selected at startup.')
        path = self.root / 'study-decisions.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        manifest = self.study.snapshot['identities']['manifest']
        return [row for row in rows if row['manifest'] == manifest]

    def save_study_decision(self, body):
        if not self.study: raise ValueError('No recorded study was selected at startup.')
        import datetime as dt
        with self.lock:
            study = self.study.read()
            family, choice, reason = body.get('family'), body.get('choice'), body.get('reason')
            if (body.get('manifest') != study['identities']['manifest']
                    or body.get('forecast') != study['identities']['forecast']
                    or family not in study['families']
                    or choice not in ('base', 'guidance', 'formatting', 'defer')
                    or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000):
                raise ValueError('Choose a registered family and decision, then give a reason.')
            row = {'id': secrets.token_hex(12), 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'manifest': study['identities']['manifest'], 'forecast': study['identities']['forecast'],
                   'family': family, 'choice': choice, 'reason': reason.strip()}
            path = self.root / 'study-decisions.jsonl'
            with path.open('a') as stream:
                stream.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
                stream.flush(); os.fsync(stream.fileno())
            path.chmod(0o600)
            return {'decisions': self.study_decisions()}

    def comparison_decisions(self, draft_id):
        path = self.path(draft_id)
        if not (path / 'draft.json').is_file():
            raise ValueError('Unknown comparison.')
        decisions = path / 'decisions.jsonl'
        return [json.loads(line) for line in decisions.read_text().splitlines()] if decisions.exists() else []

    def save_comparison_decision(self, body):
        """Keep the unaided choice before execution and the reviewed choice after it."""
        import datetime as dt
        with self.lock:
            draft_id = identifier(body.get('id'))
            state = load(self.path(draft_id) / 'draft.json')
            preview = state.get('preview')
            stage, choice, reason = body.get('stage'), body.get('choice'), body.get('reason')
            if (stage not in ('initial', 'reviewed') or choice not in ('base', 'head', 'defer')
                    or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000):
                raise ValueError('Choose a version or defer, then explain the decision.')
            rows = self.comparison_decisions(draft_id)
            if stage == 'initial':
                if (not preview or body.get('expected') != preview['expected']
                        or body.get('snapshot') != preview['id']):
                    raise ValueError('Choose against the current frozen preview.')
                if any(run['snapshot'] == preview['id'] for run in state['runs']):
                    raise ValueError('This comparison has already started. Prepare a new preview for an unaided choice.')
                if any(row['stage'] == 'initial' and row['snapshot'] == preview['id'] for row in rows):
                    raise ValueError('The choice before execution is already frozen for this preview.')
                snapshot, result_sha = preview['id'], None
                job_id = None
            else:
                job_id = identifier(body.get('job'))
                run = next((run for run in state['runs'] if run['id'] == job_id), None)
                if run is None:
                    raise ValueError('This run does not belong to the comparison.')
                status = self._job(job_id)
                if status['state'] != 'complete':
                    raise ValueError('Review a completed, verified run before deciding.')
                snapshot, result_sha = run['snapshot'], status['result_sha256']
                if not any(row['stage'] == 'initial' and row['snapshot'] == snapshot for row in rows):
                    raise ValueError('No choice was frozen before this run.')
            row = {'id': secrets.token_hex(12), 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'stage': stage, 'draft': draft_id, 'snapshot': snapshot, 'job': job_id,
                   'result_sha256': result_sha, 'choice': choice, 'reason': reason.strip()}
            path = self.path(draft_id) / 'decisions.jsonl'
            with path.open('a') as stream:
                stream.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
                stream.flush(); os.fsync(stream.fileno())
            path.chmod(0o600)
            return {'decisions': self.comparison_decisions(draft_id)}

    def path(self, id):
        return self.root / 'drafts' / identifier(id)

    def form(self, value):
        if isinstance(value, dict):
            value = {**value, 'backend': value.get('backend', 'local')}
        fields = {'backend', 'title', 'scenario', 'mode', 'base_doc', 'head_doc', 'repo', 'base', 'head', 'doc', 'n', 'agents', 'seed'}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError('Unsupported comparison fields.')
        for key in fields - {'n', 'agents', 'seed'}:
            if not isinstance(value[key], str) or len(value[key]) > 4096:
                raise ValueError('Invalid ' + key)
        if (value['backend'] not in ('local', 'sponsor', 'tokenfactory-local') or value['mode'] not in ('files', 'git') or not value['title'].strip()
                or any(type(value[x]) is not int for x in ('n', 'agents', 'seed'))
                or not 1 <= value['n'] <= 200 or not 0 <= value['agents'] <= 8):
            raise ValueError('Choose a title, input mode and supported population counts.')
        return value

    def draft(self, body):
        form = self.form(body['form'])
        with self.lock:
            id = identifier(body['id']) if body.get('id') else secrets.token_hex(12)
            path = self.path(id); path.mkdir(exist_ok=True, mode=0o700)
            state = load(path / 'draft.json') if (path / 'draft.json').exists() else {'id': id, 'revision': 0, 'runs': []}
            if body.get('revision', 0) != state['revision']:
                raise ValueError('This draft changed in another tab. Reopen it before editing.')
            if state.get('form') != form:
                state.pop('preview', None)
            state.update(form=form, revision=state['revision'] + 1)
            save(path / 'draft.json', state)
            return state

    def prepare(self, body):
        with self.lock:
            state = self.draft(body)
            f = state['form']; scenario = Path(f['scenario']).expanduser().resolve()
            if not scenario.is_file() or scenario.stat().st_size > 256_000:
                raise ValueError('Choose an existing scenario JSON under 256 KB.')
            load_contract(scenario)
            args = SimpleNamespace(**f)
            if f['mode'] == 'files':
                args.repo = args.base = args.head = None
                for k in ('base_doc', 'head_doc'):
                    p = Path(f[k]).expanduser().resolve()
                    if not p.is_file() or p.stat().st_size > 1_000_000:
                        raise ValueError('Choose complete UTF-8 documents under 1 MB each.')
                    setattr(args, k, str(p))
            else:
                args.base_doc = args.head_doc = None
            inputs = read_inputs(args)
            if any(len(raw) > 1_000_000 for raw, _ in inputs):
                raise ValueError('Choose documents under 1 MB each.')
            snapshot = secrets.token_hex(12)
            path = self.path(state['id']) / snapshot; path.mkdir(mode=0o700)
            config = {key: f[key] for key in ('n', 'agents', 'seed')}
            if f['backend'] in ('sponsor', 'tokenfactory-local'):
                from importlib import import_module
                adapter = import_module('sim.sponsor' if f['backend'] == 'sponsor' else 'sim.tokenfactory_local')
                selected = adapter.selection()
                config.update(backend=f['backend'], sponsor=selected)
                target, contract = (freeze(scenario, path, backend='sponsor', image_id=selected['image'])
                                    if f['backend'] == 'sponsor' else freeze(scenario, path))
                if f['backend'] == 'tokenfactory-local': adapter.require_supported_image(contract)
            else:
                target, contract = freeze(scenario, path)
            sources = {}
            for name, (raw, source) in zip(('base', 'head'), inputs):
                (path / (name + '.md')).write_bytes(raw)
                sources[name] = {**source, 'file': name + '.md', 'sha256': sha256_bytes(raw)}
            (path / 'inputs.json').write_text(dumps(sources))
            expected = seal(path, config)
            state['preview'] = {'id': snapshot, 'expected': expected, 'contract': contract, 'sources': sources,
                                'config': config, 'engine': load(path / 'manifest.json')['engine'], 'documents': {name: (path / (name + '.md')).read_text() for name in sources}}
            save(self.path(state['id']) / 'draft.json', state)
            return state

    def start(self, body):
        with self.lock:
            state = load(self.path(body['id']) / 'draft.json')
            preview = state.get('preview')
            if (body.get('revision') != state['revision'] or not preview
                    or body.get('expected') != preview['expected']):
                raise ValueError('Inspect the current exact preview before starting.')
            sponsor = preview['config'].get('backend') in ('sponsor', 'tokenfactory-local')
            if sponsor:
                if not self.allow_sponsor:
                    raise ValueError('Sponsor execution is off. Restart with --allow-sponsor only after authorizing provider charges and transfer of the reviewed source/docs. Preview remains local.')
                from importlib import import_module
                adapter = import_module('sim.sponsor' if preview['config']['backend'] == 'sponsor' else 'sim.tokenfactory_local')
                adapter.require_ready(preview['config'])
                if body.get('sponsorConsent') != preview['expected']:
                    raise ValueError('Confirm provider transfer and unknown cost for this exact preview.')
            if not sponsor and preview['config']['agents'] and not self.allow_agents:
                raise ValueError('Coding agents are not authorized by this local service. Restart with --allow-agents only when you intend to use the cached local model, or choose readers only and preview again.')
            if any(self.job(p.name)['state'] in ('starting', 'running', 'unconfirmed') for p in (self.root / 'jobs').iterdir()):
                raise ValueError('A comparison is already running here. Wait for its actual result before starting another.')
            if any(run['snapshot'] == preview['id'] for run in state['runs']):
                raise ValueError('This snapshot already started. Prepare a new preview for another run.')
            path = self.path(state['id']) / preview['id']
            verify(path, preview['expected'])
            id = secrets.token_hex(12); jobdir = self.root / 'jobs' / id; jobdir.mkdir(mode=0o700)
            job = {'id': id, 'draft': state['id'], 'snapshot': str(path), 'expected': preview['expected'],
                   'output': str(jobdir / 'result'), 'config': preview['config'], 'allow_sponsor': sponsor and self.allow_sponsor}
            save(jobdir / 'job.json', job)
            save(jobdir / 'status.json', {'state': 'starting'})
            state['runs'].append({'id': id, 'snapshot': preview['id']})
            save(self.path(state['id']) / 'draft.json', state)
            # Fixed module plus server-owned path. No browser command enters a host shell.
            try:
                with (jobdir / 'worker.log').open('wb') as log:
                    proc = subprocess.Popen([sys.executable, '-m', 'sim.workspace_worker', str(jobdir / 'job.json')],
                                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as e:
                save(jobdir / 'status.json', {'state': 'failed', 'error': 'Worker could not start: ' + str(e)})
            else:
                save(jobdir / 'launch.json', {'pid': proc.pid})
                threading.Thread(target=proc.wait, daemon=True).start()
            return {'id': id}

    def job(self, id):
        with self.lock:
            return self._job(id)

    def _job(self, id):
        directory = self.root / 'jobs' / identifier(id)
        status = load(directory / 'status.json')
        if status['state'] in ('starting', 'running'):
            launch = directory / 'launch.json'
            group = status.get('pid') or (load(launch)['pid'] if launch.exists() else None)
            try:
                probe = subprocess.run(['ps', '-ax', '-o', 'pid=', '-o', 'pgid=', '-o', 'command='], capture_output=True, text=True)
                rows = [line.strip().split(None, 2) for line in probe.stdout.splitlines() if line.strip()]
                valid = probe.returncode == 0 and all(len(r) == 3 and r[0].isdigit() and r[1].isdigit() for r in rows)
            except OSError:
                valid, rows = False, []
            owned = any(('sim.workspace_worker' in r[2] and str(directory / 'job.json') in r[2]) or
                        ('sim compare' in r[2] and str(directory / 'result') in r[2]) for r in rows if len(r) == 3)
            group_alive = group and any(r[1] == str(group) for r in rows if len(r) == 3)
            # Worker owns terminal records. Re-read after the process probe; never write
            # an observation over a concurrently completed result.
            status = load(directory / 'status.json')
            if status['state'] in ('starting', 'running'):
                if not valid or (group_alive and not owned):
                    status = {**status, 'state': 'unconfirmed', 'error': 'Process state is unconfirmed. A new run is held; no automatic retry.'}
                elif not owned:
                    status = {**status, 'state': 'interrupted', 'error': 'No owned worker or comparison process remains. No automatic retry; preserved files may be inspected.'}
                else:
                    status = {**status, 'state': 'running'}
        if status['state'] == 'complete':
            from sim.workspace_worker import verify_result
            try: verify_result(directory, status['result_sha256'])
            except (ValueError, OSError, KeyError) as e:
                status = {**status, 'state': 'failed', 'error': 'Saved result changed or is incomplete: ' + str(e)}
        log = directory / 'compare.log'
        return {**status, 'id': id, 'log': log.read_text(errors='replace')[-20000:] if log.exists() else '',
                'output': str(directory / 'result'), 'job': load(directory / 'job.json')}

    def listing(self):
        return [load(p / 'draft.json') for p in sorted((self.root / 'drafts').iterdir()) if (p / 'draft.json').exists()]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # private paths and token never logged

    def respond(self, code, data, kind='application/json'):
        raw = dumps(data).encode() if kind == 'application/json' else data
        self.send_response(code); self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'SAMEORIGIN'); self.end_headers(); self.wfile.write(raw)

    def route(self):
        ws = self.server.workspace
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Host') != origin[7:]:
            return self.respond(403, {'error': 'Loopback Host required.'})
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            if (self.headers.get('Origin') not in (None, origin)
                    or not hmac.compare_digest(self.headers.get('X-Workspace-Token', ''), ws.token)):
                return self.respond(403, {'error': 'Open the private link printed by your local workspace command.'})
            if self.command == 'POST':
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('JSON required.')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 128_000: raise ValueError('Request too large or empty.')
                body = json.loads(self.rfile.read(size))
                from sim import human_trial, workspace_setup, tool_workspace, tool_builder, tool_decision, tool_forecast_view, tool_forecast_workspace, tool_preflight, public_pr_trial
                from sim import tool_decision_protocol
                from sim import tool_mcp_view
                from sim import swarm_api
                from sim import swarm_guide
                if path.startswith('/api/tool/') and body.get('id') and (tool_workspace.directory(ws,body['id'])/'mcp-import.json').exists():
                    raise ValueError('Recorded MCP evidence is read-only; no execution, release choice or forecast action is available.')
                from sim import app_check
                actions = {'/api/app-check/start': lambda b: app_check.start(ws,b),
                           '/api/app-check/job': lambda b: app_check.job(ws,b),
                           '/api/app-check/report': lambda b: app_check.report(ws,b),
                           '/api/tool/mcp-import': lambda b: tool_mcp_view.import_record(ws,b),
                           '/api/swarm/start': lambda b: swarm_api.start(ws,b),
                           '/api/swarm/guide': lambda b: swarm_guide.first_turn(ws,b),
                           '/api/tool/public-pr/inspect': lambda b: public_pr_trial.inspect(ws,b),
                           '/api/tool/public-pr': lambda b: public_pr_trial.prepare(ws,b),
                           '/api/tool/prospective-prepare': lambda b: tool_forecast_workspace.prepare(ws,b),
                           '/api/tool/decision-stage': lambda b: tool_decision_protocol.save(ws, b),
                           '/api/tool/source-diff': lambda b: tool_workspace.source_diff(ws, b),
                           '/api/tool/sponsor-preview': lambda b: tool_workspace.sponsor_preview(ws, b),
                           '/api/tool/preflight': lambda b: tool_preflight.prepare(ws, b),
                           '/api/tool/source': tool_builder.source,
                           '/api/tool/forecast': lambda b: tool_forecast_view.open_forecast(ws, b),
                           '/api/tool/decision': lambda b: tool_decision.save(ws, b),
                           '/api/tool/images': tool_builder.images,
                           '/api/tool/import': lambda b: tool_workspace.import_trial(ws, b),
                           '/api/tool/prepare': lambda b: tool_workspace.prepare(ws, b),
                           '/api/tool/start': lambda b: tool_workspace.start(ws, b),
                           '/api/model-smoke/run': lambda b: ws.run_model_smoke(),
                           '/api/save': ws.draft, '/api/preview': ws.prepare, '/api/start': ws.start,
                           '/api/source': workspace_setup.source,
                           '/api/scenario': lambda b: workspace_setup.create(ws, b),
                           '/api/trial/create': lambda b: human_trial.create(ws, b),
                           '/api/trial/record': lambda b: human_trial.record(ws, b),
                           '/api/trial/close': lambda b: human_trial.close(ws, b),
                           '/api/decision': ws.save_comparison_decision,
                           '/api/study/decision': ws.save_study_decision}
                if path not in actions: return self.respond(404, {'error': 'Unknown action.'})
                return self.respond(200, actions[path](body))
            if path.startswith('/api/app-check/media/'):
                from sim import app_check
                parts=path.split('/')
                if len(parts)!=6 or not app_check.MEDIA.fullmatch(parts[5]):raise ValueError('Unknown visit screen.')
                media=app_check.folder(ws,parts[4])/parts[5]
                return self.respond(200,media.read_bytes(),'image/png')
            if path == '/api/app-check/results':
                from sim import app_check
                return self.respond(200,app_check.listing(ws))
            if path.startswith('/api/app-check/result/'):
                from sim import app_check
                return self.respond(200,app_check.read(ws,path.rsplit('/',1)[1]))
            if path == '/api/tools':
                from sim.tool_workspace import listing
                return self.respond(200, listing(ws))
            if path == '/api/swarm/guide/latest':
                from sim.swarm_guide import latest
                return self.respond(200, latest(ws))
            if path.startswith('/api/swarm/result/'):
                from sim import swarm_api
                return self.respond(200, swarm_api.result(ws, identifier(path.rsplit('/', 1)[1])))
            if path == '/api/model-smoke':
                from sim.model_smoke import read_receipt
                return self.respond(200, read_receipt(ws.root / 'model-smoke.jsonl'))
            if path.startswith('/api/tool/'):
                from sim.tool_workspace import result
                return self.respond(200, result(ws, path.rsplit('/', 1)[1]))
            if path == '/api/drafts':
                from sim.sponsor import prerequisites
                from sim.tokenfactory_local import prerequisites as tokenfactory_prerequisites
                return self.respond(200, {'drafts': ws.listing(), 'allowAgents': ws.allow_agents, 'allowSponsor': ws.allow_sponsor, 'sponsorReadiness': prerequisites(1), 'tokenFactoryReadiness': tokenfactory_prerequisites(1), 'root': str(ws.root)})
            if path == '/api/study':
                if not ws.study: return self.respond(404, {'error': 'No recorded study was selected at startup.'})
                return self.respond(200, {'study': ws.study.read(), 'decisions': ws.study_decisions()})
            if path.startswith('/api/decisions/'):
                return self.respond(200, {'decisions': ws.comparison_decisions(identifier(path.rsplit('/', 1)[1]))})
            if path.startswith('/api/trial/'):
                from sim.human_trial import read
                return self.respond(200, read(ws, path.rsplit('/', 1)[1]))
            if path.startswith('/api/job/'):
                return self.respond(200, ws.job(path.rsplit('/', 1)[1]))
            if path.startswith('/api/result/'):
                id = identifier(path.rsplit('/', 1)[1]); state = ws.job(id)
                if state['state'] != 'complete': raise ValueError('No completed control-verified result is available.')
                from sim.workspace_worker import verify_result
                content = verify_result(ws.root / 'jobs' / id, state['result_sha256'])
                return self.respond(200, {name: json.loads(content[name + '.json']) for name in ('base', 'head', 'delta')})
            return self.respond(404, {'error': 'Unknown resource.'})
        if self.command != 'GET': return self.respond(405, {'error': 'Method not allowed.'})
        static = {'/': ('web/index.html', 'text/html'), '/index.html': ('web/index.html', 'text/html'),
                  '/score.js': ('web/score.js', 'application/javascript'), '/workspace': ('workspace/index.html', 'text/html'),
                  '/workspace.html': ('workspace/index.html', 'text/html'),
                  '/workspace.js': ('workspace/app.js', 'application/javascript'),
                  '/study.js': ('workspace/study.js', 'application/javascript')}
        static['/tools'] = ('workspace/app-test.html', 'text/html')
        static['/agent-report'] = ('workspace/tools.html', 'text/html')
        static['/app-test.js'] = ('workspace/app-test.js', 'application/javascript')
        static['/tools.js'] = ('workspace/tools.js', 'application/javascript')
        static['/recorded-replay.js'] = ('workspace/recorded-replay.js', 'application/javascript')
        static['/recorded-evidence.json'] = ('workspace/recorded-evidence.json', 'application/json; charset=utf-8')
        static['/swarm-example.json'] = ('workspace/swarm-example.json', 'application/json; charset=utf-8')
        static['/swarm-example.js'] = ('workspace/swarm-example.js', 'application/javascript')
        static['/forecast-review.js'] = ('workspace/forecast-review.js', 'application/javascript')
        static['/visit-trace.js'] = ('workspace/visit-trace.js', 'application/javascript')
        if path.startswith('/control'):
            # Planted broken app for the control run. Static, read-only, no workspace data.
            from sim import app_swarm
            status, html = app_swarm.control_page(path)
            return self.respond(status, html.encode(), 'text/html')
        if path not in static: return self.respond(404, {'error': 'Not found.'})
        file, kind = static[path]; raw = (ROOT / file).read_bytes()
        return self.respond(200, raw, kind)

    def do_GET(self): self.handle_route()
    def do_POST(self): self.handle_route()
    def handle_route(self):
        try: self.route()
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as e:
            self.respond(400, {'error': str(e)[:700]})


def add_parser(sub):
    p = sub.add_parser('workspace', help='private loopback comparison preparation and results')
    p.add_argument('--store', required=True, help='private directory outside the tool checkout')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--allow-app-swarm', action='store_true', help='permit full runs: model-guided test visitors on a public app, each run capped by the spend control')
    p.add_argument('--allow-app-report', action='store_true', help='permit one bounded deeper app report per retained visit under the reporting stop')
    p.add_argument('--allow-sponsor', action='store_true', help='permit explicitly confirmed paid sponsor runs and reviewed source transfer')
    p.add_argument('--allow-agents', action='store_true', help='explicitly permit cached local model runs')
    p.add_argument('--study-dir', help='completed registered campaign to review, outside this repository')
    p.add_argument('--study-model', help='frozen model used by that campaign')


def cmd_workspace(a):
    os.umask(0o077)
    ws = Workspace(a.store, a.allow_agents, a.allow_sponsor, a.study_dir, a.study_model)
    ws.allow_app_report = bool(getattr(a,'allow_app_report',False))
    ws.allow_app_swarm = bool(getattr(a,'allow_app_swarm',False))
    server = ThreadingHTTPServer(('127.0.0.1', a.port), Handler); server.workspace = ws
    print(f'Private workspace: http://127.0.0.1:{server.server_port}/workspace#token={ws.token}', flush=True)
    print('Private workspace. Local execution by default; sponsor execution requires explicit authorization and preview confirmation.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); ws.guard.close()
    return 0
