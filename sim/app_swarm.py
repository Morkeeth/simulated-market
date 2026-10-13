"""Test visitors: a small group of model-guided visitors drives an app in a real browser.

Each visitor has a goal. At every step the NVIDIA model reads the page in front of it and
picks one thing to do. The browser is read-only: nothing is typed, no account is used, and
every request that is not a plain read is refused. What a visitor tried, where it stopped
and the screen it saw are kept, so a finished run reopens without another model call.

These visitors are a model, not people. Nothing here is a quote from a human user.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from sim import hosted_cost, tool_trial, task_contract, task_rail, completion_evidence

PROVIDER = 'Nebius Token Factory'
SHARED_STOP_USD = Decimal(os.environ.get('SIM_PROVIDER_STOP_USD', '8'))
RUN_CAP_USD = Decimal('0.25')        # conservative account, held reservations included
MAX_OUTPUT_TOKENS = 220
PAGE_CHARS = 3600
MAX_CHOICES = 36

CAST = [
    {'id': 'newcomer', 'name': 'First-time visitor', 'colour': '#1f6f5c', 'max_steps': 6, 'viewport': (1440, 900),
     'character': 'You have never heard of this app. You give it a fair look.'},
    {'id': 'phone', 'name': 'In a hurry, on a phone', 'colour': '#b4532a', 'max_steps': 4, 'viewport': (390, 844), 'phone': True,
     'character': 'You are on your phone between two things. You leave fast when a page wastes your time.'},
    {'id': 'buyer', 'name': 'Careful visitor', 'colour': '#8a3d6b', 'max_steps': 6, 'viewport': (1440, 900),
     'character': 'You read a page before you click. You do not guess.'},
    {'id': 'reader', 'name': 'Curious visitor', 'colour': '#6b5a1e', 'max_steps': 6, 'viewport': (1440, 900),
     'character': 'You want to see the real thing working, not a description of it.'},
    {'id': 'developer', 'name': 'Sceptic', 'colour': '#3d4a8f', 'max_steps': 6, 'viewport': (1440, 900), 'sceptic': True,
     'character': 'You build software. You distrust marketing words.',
     'goal': 'Before trusting this app, find either what it costs or how it works under the hood.'},
]
FALLBACK_JOB = 'Work out what this app is for and do its main thing'
def needs_write(job):
    """Classify the intended act using the typed local task contract."""
    return task_contract.compile_task(job).intent == 'write'



def personas_for(job):
    """Four visitors try the app's own job. One sceptic keeps its own question."""
    job = job.strip().rstrip('.')
    if needs_write(job):   # a read-only visitor cannot do this; it can only show how far a signed-out person gets
        return [dict(x) if x.get('sceptic') else {**x, 'start_only': True, 'job': job, 'goal': 'Get as far as a signed-out visitor can toward this: ' + job + '. Find the screen where it starts.'} for x in CAST]
    return [dict(x) if x.get('sceptic') else {**x, 'goal': 'Do what people come to this app for: ' + job + '.'} for x in CAST]


PERSONAS = personas_for(FALLBACK_JOB)


def cache_key(url, job, tries):
    """A saved result stands for one address, one task, these visitors and goals, this many tries and this setup."""
    people = personas_for(job)
    setup = {'address': url.strip().rstrip('/'), 'job': job.strip().rstrip('.').casefold(), 'tries': tries, 'model': hosted_cost.MODEL,
             'visitors': [[x['id'], x['goal'], x['max_steps'], list(x['viewport'])] for x in people], 'rules': 4, 'task_contract': task_contract.compile_task(job).payload()}
    return hashlib.sha256(json.dumps(setup, sort_keys=True).encode()).hexdigest()[:32]


def kept_job(root, url):
    kept = Path(root) / 'app-jobs' / (hashlib.sha256(url.rstrip('/').encode()).hexdigest()[:24] + '.json')
    return tool_trial.read(kept) if kept.exists() else None

# Planted control app. Pricing is a dead link and the docs need an account,
# so every visitor sent to find the price must fail. It exists to show a run can go red.
CONTROL_MUST_FAIL = ['newcomer', 'phone', 'buyer', 'reader']
CONTROL_JOB = 'See what Lumen Notes costs'
_CONTROL_STYLE = '<style>body{font:17px/1.5 system-ui;margin:0;color:#1d2330}nav{display:flex;gap:22px;padding:18px 40px;border-bottom:1px solid #d8dbe4}main{max-width:720px;margin:60px auto;padding:0 24px}h1{font-size:40px;margin:0 0 12px}button,.b{background:#2b47d6;color:#fff;border:0;border-radius:8px;padding:11px 18px;font:inherit;text-decoration:none}</style>'
_CONTROL_NAV = '<nav><strong>Lumen Notes</strong><a href="/control/features">Features</a><a href="/control/pricing">Pricing</a><a href="/control/docs">Docs</a><a href="/control/login">Sign in</a></nav>'
CONTROL_PAGES = {
    '/control/': ('Lumen Notes', '<h1>Lumen Notes</h1><p>Lumen Notes keeps your meeting notes in one place and turns them into a short list of who does what.</p><p>Made for small teams that talk more than they write.</p><p><a class="b" href="/control/login">Start now</a></p>'),
    '/control/features': ('Features', '<h1>Features</h1><p>Record a meeting. Get the decisions as a list. Share the list with one link.</p><p>Works with the calendar you already use.</p>'),
    '/control/docs': ('Docs', '<h1>Docs</h1><p>Sign in to read the docs.</p><p><a class="b" href="/control/login">Sign in</a></p>'),
    '/control/login': ('Sign in', '<h1>Sign in</h1><form><p><input placeholder="Email"></p><p><button type="submit">Send me a link</button></p></form>'),
}


def control_page(path):
    """The planted control app. Returns (status, html)."""
    if path == '/control': path = '/control/'
    if path in CONTROL_PAGES:
        title, body = CONTROL_PAGES[path]
        return 200, f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title} · Lumen Notes</title>{_CONTROL_STYLE}{_CONTROL_NAV}<main>{body}</main></html>'
    return 404, f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Not found</title>{_CONTROL_STYLE}<main><h1>404</h1><p>Page not found. This page does not exist.</p></main></html>'


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, html = control_page(urlsplit(self.path).path); raw = html.encode()
        self.send_response(status); self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def log_message(self, *args): pass


def is_control(url):
    u = urlsplit(url)
    return u.hostname in ('127.0.0.1', 'localhost') and u.path.startswith('/control')


def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()


# ---- spend control -------------------------------------------------------------------

class BudgetStop(Exception):
    """The run may not make another paid call."""


def ensure_account():
    """On a machine that never ran this, start the earlier-spend file at zero. An existing file is never opened for writing."""
    path = hosted_cost.PRIOR
    if path.exists(): return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try: fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)      # fails rather than replace a file
    except FileExistsError: return False
    with os.fdopen(fd, 'w') as stream:
        json.dump({'schema': 'hosted-spend/1', 'runs': [], 'cap_usd': float(hosted_cost.LIMIT),
                   'note': 'Started at zero on a machine with no earlier spend record.'}, stream, indent=2); stream.write('\n')
    return True


def require_key():
    """One clear line when the model cannot be reached from this machine."""
    from sim.adapters import tokenfactory
    try: tokenfactory.load_key()
    except Exception:
        raise ValueError('No model key on this machine. Set TOKEN_FACTORY_API_KEY to your Nebius Token Factory key, then start again. Saved runs still open without it.') from None


class Budget:
    """Caps one run. Every call is reserved before it is made and settled after."""

    def __init__(self, run_key, max_calls, run_cap_usd=RUN_CAP_USD):
        self.run_key = str(run_key); self.max_calls = int(max_calls); self.run_cap = Decimal(str(run_cap_usd))
        self.lock = threading.Lock(); self.started = 0; self.rows = []

    def _account(self):
        try:
            with hosted_cost.RECORD.open() as stream:
                fcntl.flock(stream, fcntl.LOCK_SH)   # never read while another call is writing
                raw = stream.read()
            runs = json.loads(raw)['runs'] if raw else {}
        except FileNotFoundError: runs = {}
        total = hosted_cost.prior_total() + sum((Decimal(str(row['accounted_usd'])) for row in runs.values()), Decimal(0))
        mine = sum((Decimal(str(row['accounted_usd'])) for key, row in runs.items() if key.startswith(self.run_key + '/')), Decimal(0))
        return total, mine

    def call(self, client, messages, label, seed, temperature=0):
        one = hosted_cost.worst_case(1); ensure_account()
        with self.lock:
            if self.started >= self.max_calls:
                raise BudgetStop('This run reached its call limit.')
            total, mine = self._account()
            if mine + one > self.run_cap:
                raise BudgetStop('This run reached its spending limit.')
            if total + one > SHARED_STOP_USD:
                raise BudgetStop('The shared spending stop was reached. No model call was made.')
            if len(json.dumps(messages).encode()) > hosted_cost.MAX_PROMPT_BYTES:
                raise BudgetStop('The page was too large to send.')
            key = self.run_key + '/' + label
            hosted_cost.reserve(key, 1, hosted_cost.MODEL)
            self.started += 1
        settled = False; began = time.monotonic()
        try:
            reply = client.chat(messages, temperature=temperature, seed=seed, max_tokens=MAX_OUTPUT_TOKENS,
                                chat_template_kwargs={'enable_thinking': False})
            row = hosted_cost.settle(key, reply.usage, True); settled = True
            entry = {'call': label, 'status': row['status'], 'usage': row.get('usage'), 'accounted_usd': row['accounted_usd'],
                     'model': reply.model, 'ms': round((time.monotonic() - began) * 1000)}
            with self.lock: self.rows.append(entry)
            if reply.model != hosted_cost.MODEL:
                raise RuntimeError('The reply did not come from the registered model.')
            return reply, entry
        finally:
            if not settled:
                row = hosted_cost.settle(key, {}, False)
                with self.lock:
                    self.rows.append({'call': label, 'status': row['status'], 'usage': None, 'accounted_usd': row['accounted_usd'],
                                      'model': None, 'ms': round((time.monotonic() - began) * 1000)})

    def summary(self):
        with self.lock: rows = list(self.rows)
        good = [r for r in rows if r['status'] == 'usage_accounted']
        return {'model': hosted_cost.MODEL, 'provider': PROVIDER, 'model_calls': len(rows), 'max_calls': self.max_calls,
                'run_cap_usd': float(self.run_cap), 'calls_without_usage': len(rows) - len(good),
                'prompt_tokens': sum(r['usage']['prompt_tokens'] for r in good),
                'completion_tokens': sum(r['usage']['completion_tokens'] for r in good),
                'listed_rate_estimate_usd': float(sum((Decimal(str(r['accounted_usd'])) for r in good), Decimal(0))),
                'held_reservation_usd': float(sum((Decimal(str(r['accounted_usd'])) for r in rows if r not in good), Decimal(0))),
                'price_source': hosted_cost.PRICE_SOURCE, 'provider_invoice_usd': None, 'calls': rows}


# ---- what the model may say and do ---------------------------------------------------

ACTIONS = ('click', 'scroll', 'back', 'stuck')
NEEDS_ACCOUNT = re.compile(r'sign.?in|log.?in|sign.?up|register|create (an )?account|my account|subscribe|join now', re.I)
ACCOUNT_PATH = re.compile(r'/(login|signin|sign-in|signup|sign-up|register|auth|account|subscribe)(/|$)', re.I)
CHANGES_DATA = re.compile(r'delete|remove|publish|submit|send|pay\b|checkout|buy|purchase|vote|accept|upload|save|post\b|order', re.I)


WRITE_WORDS = {'save', 'delete', 'remove', 'insert', 'update', 'upsert', 'create', 'add', 'set', 'put', 'post', 'send', 'submit', 'write', 'vote', 'like', 'follow',
               'unfollow', 'join', 'accept', 'invite', 'pay', 'buy', 'mark', 'bump', 'increment', 'record', 'register', 'sign', 'track', 'log', 'publish', 'share', 'claim', 'reset', 'drop', 'grant'}


def is_plain_read(method, url, body=None):
    """True for a request that only reads. Many apps load their own content with a POST
    (a named function, a GraphQL query). Refusing those would break the page and blame
    the app for it. So named functions pass unless the name says it writes, GraphQL
    queries pass, and every other request that is not a plain read is refused."""
    if method in ('GET', 'HEAD', 'OPTIONS'): return True
    if method != 'POST': return False
    path = urlsplit(url).path
    named = re.search(r'/rpc/([A-Za-z0-9_]+)$', path)
    if named: return not (WRITE_WORDS & set(named.group(1).lower().split('_')))     # the app's own read calls pass; a name that says write is refused
    if path.rstrip('/').endswith('/graphql') and body:
        try: query = json.loads(body).get('query', '')
        except (ValueError, AttributeError): return False
        return isinstance(query, str) and query.lstrip().startswith(('query', '{')) and 'mutation' not in query
    return False


def parse_reply(text):
    """One JSON object from the model, or a confused step. Never raises."""
    confused = {'action': 'confused', 'target': None, 'say': '', 'wish': ''}
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match: return confused
    try: raw = json.loads(match.group(0))
    except ValueError: return confused
    if not isinstance(raw, dict) or raw.get('action') not in ACTIONS: return confused
    out = {'action': raw['action'], 'say': str(raw.get('say') or '').strip()[:240], 'wish': str(raw.get('wish') or '').strip()[:240]}
    if out['action'] == 'click':
        try: out['target'] = int(raw.get('target'))
        except (TypeError, ValueError): return confused
    return out


def squash(text): return re.sub(r'\s+', ' ', text or '').strip().casefold()


def quote_on_page(quote, page_text):
    """A visitor only 'got there' when the words it points at are really on the page."""
    q = squash(quote).strip('"\'“”.… ')
    return len(q) >= 20 and q in squash(page_text)


def refusal(element, host):
    """Why this thing may not be clicked, or None. The browser stays read-only."""
    text = element.get('text', ''); href = element.get('href') or ''
    if href:
        u = urlsplit(href)
        if u.scheme not in ('http', 'https'): return 'That opens something outside the browser. It was not followed.'
        if u.hostname != host: return f'That link leaves the app for {u.hostname}.'
        if ACCOUNT_PATH.search(u.path) or NEEDS_ACCOUNT.search(text): return 'That needs an account. Test visitors do not sign in.'
        return None
    if NEEDS_ACCOUNT.search(text): return 'That needs an account. Test visitors do not sign in.'
    if element.get('inForm') or element.get('type') == 'submit' or CHANGES_DATA.search(text):
        return 'That would send or change something. Test visitors only read.'
    return None


LOOK = '''You are {name}, trying a web app for the first time. {character}
Your task: {goal}
Read the text of the screen in front of you. Is your task completed on this screen?
Reply with ONE JSON object and nothing else:
{{"found": true or false, "quote": "if found: the one or two full sentences on this screen that show it, copied exactly"}}
found is true only when this screen itself holds the result of the task. A link, a button, a menu or a heading that only points toward it is not enough.'''

CONFIRM = '''You check whether a task was completed in a web app. Be strict.
The task: {goal}
The next message lists what the visitor did, in order. The last message is all the text of the screen the visitor ended on, and nothing else.
Reply with ONE JSON object and nothing else:
{{"done": true or false, "evidence": "words copied exactly from that screen that show the task was done here, not words that describe or offer it", "why": "at most 18 words"}}
done is true only when that screen itself shows the task completed: the result, the content or the answer is written on it.
When the task has several parts, the list must also show each part was done, in order.
A screen that only offers a link, a button, a menu, a sample to open, a request to sign in or a description of how to do it is not completed.
The visitor must have done the task in this visit. Content that was already there, made by other people, does not count.'''

CONFIRM_START = '''You check one thing about one screen of a web app. Be strict.
People come to this app to: {job}
A signed-out visitor cannot do that. The question is only whether this screen is where a person begins doing it.
The next message lists what the visitor did, in order. The last message is all the text of the screen the visitor ended on, and nothing else.
Reply with ONE JSON object and nothing else:
{{"done": true or false, "evidence": "the words of the form, command or control on that screen that begins it, copied exactly", "why": "at most 18 words"}}
done is true only when the form, the command or the control that begins it is on this screen. A menu link to another page that has it is not enough.
Existing content made by other people is not the start. A page that only explains the app is not the start.'''

MOVES = {'went_somewhere': 'open something beyond the first screen', 'came_back': 'come back to a screen you were on before',
         'wrote': 'do the part that needs an account or saves something, which a read-only visitor cannot do',
         'content_evidence': 'read the actual answer in page content, not a navigation label', 'task_contract': 'clarify the task before calling it complete'}
def required_moves(job):
    return list(task_contract.compile_task(job).required_moves)


def moves_made(trail):
    return task_rail.observed_moves(trail)


def completion(job, screen_confirmed, trail, *, evidence=None, content=None, http_status=None):
    """Keep model confirmation separate from independent task enforcement."""
    if not screen_confirmed:
        return {'state': 'claimed', 'missing': []}
    if content is not None:
        valid, reason = completion_evidence.check(job, evidence, content, http_status)
        if not valid:
            return {'state': 'screen_confirmed', 'missing': ['content_evidence'], 'reason': reason}
    decision = task_rail.enforce(task_contract.compile_task(job), trail)
    return {'state': 'job_completed' if decision.allowed else 'screen_confirmed',
            'missing': list(decision.missing)}


def confirm_messages(person, screen_text, trail=None):
    """The second call. It gets the task, the ordered steps and the text of the named screen. Nothing the visitor said."""
    contract = task_contract.compile_task(person.get('job') if person.get('start_only') else person['goal'])
    did = '\n'.join(f"{i}. On {e.get('url')}: {e.get('action')}" + (f" '{e['target']}'" if e.get('target') else '') for i, e in enumerate(trail or [], 1)) or '(no steps recorded)'
    system = CONFIRM_START.format(job=person['job']) if person.get('start_only') else CONFIRM.format(goal=person['goal'])
    system += '\nTask contract (locally parsed, not model-generated): ' + json.dumps(contract.payload(), ensure_ascii=False)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': 'What the visitor did, in order:\n' + did},
            {'role': 'user', 'content': screen_text or '(no readable text)'}]


def parse_confirm(text):
    match = re.search(r'\{.*\}', text or '', re.S)
    try: raw = json.loads(match.group(0)) if match else {}
    except ValueError: raw = {}
    if not isinstance(raw, dict): raw = {}
    return {'done': raw.get('done') is True, 'evidence': str(raw.get('evidence') or '').strip()[:300], 'why': str(raw.get('why') or '').strip()[:200]}


def confirmed(verdict, screen_text):
    """A yes only counts with evidence, and the evidence must be words that are on that screen."""
    words = squash(verdict.get('evidence', '')).strip('"\'“”.… ')
    return bool(verdict.get('done')) and len(words) >= 6 and words in squash(screen_text)


JOB = '''Below is text from pages of one web app. Reply with ONE JSON object and nothing else:
{"what": "one plain sentence saying what this app is for, at most 22 words",
 "job": "the one task a person comes here to do, starting with a verb, at most 14 words"}
Use only what the pages say. The task must be something a visitor does in the app, not learning about it.'''


def parse_job(text):
    match = re.search(r'\{.*\}', text or '', re.S)
    try: raw = json.loads(match.group(0)) if match else {}
    except ValueError: raw = {}
    if not isinstance(raw, dict) or not str(raw.get('job') or '').strip(): return None
    return {'what': str(raw.get('what') or '').strip()[:240], 'job': str(raw['job']).strip().rstrip('.')[:160]}


SYSTEM = '''You are role-playing one person trying a web app for the first time.
You are: {name}. {character}
Your task: {goal}
You have read the page in front of you and your task is not completed on it. Pick your next move.
You see the page text and a numbered list of things you can click. You cannot type, sign in or create an account.
Reply with ONE JSON object and nothing else:
{{"say": "what you would mutter to yourself, first person, plain words, at most 22 words",
  "action": "click" or "scroll" or "back" or "stuck",
  "target": the number to click (click only),
  "wish": "stuck only: the one change to this app that would have got you through, at most 18 words"}}
Rules:
- Click the one thing most likely to get you to your goal. Go back when a page was a dead end.
- Say stuck when nothing left moves you toward the goal. Say what was in your way, as it is on the page.
- Use only what is on the page. Never invent page content. Never blame the page for something it did not do.
- The numbers only let you point at a thing. Never mention numbers, lists, steps or JSON in say or wish.'''


def look_messages(person, view):
    return [{'role': 'system', 'content': LOOK.format(**person)},
            {'role': 'user', 'content': 'Page address: ' + view['url'] + '\nPage title: ' + (view['title'] or '(none)') + '\nPage text:\n' + (view['text'] or '(no readable text)')}]


def parse_look(text):
    match = re.search(r'\{.*\}', text or '', re.S)
    try: raw = json.loads(match.group(0)) if match else {}
    except ValueError: raw = {}
    if not isinstance(raw, dict): raw = {}
    return {'found': raw.get('found') is True, 'quote': str(raw.get('quote') or '').strip()[:400]}


def describe(element, host):
    href = element.get('href') or ''; locked = ''
    if not href: return f"[button] {element['text']}{locked}"
    u = urlsplit(href)
    where = (u.path or '/') if u.hostname == host else 'another site: ' + str(u.hostname or u.scheme)
    return f"[link] {element['text']} -> {where}{locked}"


def build_messages(person, view, history, step, note):
    last = step >= person['max_steps']
    lines = [f"Step {step} of {person['max_steps']}."]
    if note: lines.append('What just happened: ' + note)
    lines += ['Page address: ' + view['url'], 'Page title: ' + (view['title'] or '(none)')]
    if view.get('http_status') and view['http_status'] >= 400: lines.append(f"The page answered with error {view['http_status']}.")
    more = view['text_total'] > view['offset'] + len(view['text'])
    lines.append(f"Page text{' (further down the page)' if view['offset'] else ''}:\n{view['text'] or '(no readable text)'}" + ('\n(the page continues further down)' if more else ''))
    host = urlsplit(view['url']).hostname
    choices = '\n'.join(f"{e['n']}. {describe(e, host)}" for e in view['elements']) or '(nothing to click)'
    if last: lines.append('You are out of patience and will not click anything else. The action is stuck. Say what was in your way and give your wish.')
    elif not view['elements']: lines.append('There is nothing to click on this page. You can go back, scroll or say stuck.')
    else: lines.append('Things you can click:\n' + choices)
    if view.get('locked'): lines.append('Also on the page, but they need an account or would change something, so you cannot use them: ' + ', '.join(view['locked'][:8]))
    if history: lines.append('Your earlier steps:\n' + '\n'.join(history[-6:]))
    return [{'role': 'system', 'content': SYSTEM.format(**person)}, {'role': 'user', 'content': '\n'.join(lines)}]


# ---- fixes come only from what a visitor hit -----------------------------------------

NO_FIX_NOTE = 'No test visitor got stuck in this run, so there is nothing to fix from it.'


HARNESS_TALK = re.compile(r'\bnumber \d|\bno number\b|\bthe list\b|\bjson\b|\bstep \d|test visitor|cut(ting)? off|rest of the page|out of patience|clickable|not allowed', re.I)


def own_words(text):
    """Drop a line that talks about the test rig instead of the app."""
    return '' if HARNESS_TALK.search(text or '') else (text or '')


def derive_fixes(visitors):
    """One fix per place a visitor stopped. Each one carries its step, screen and page words.

    The place is the last thing that was in the visitor's way (an error page, a door that
    needs an account). When there was none, it is the page where the visitor gave up.
    """
    groups = {}
    for v in visitors:
        if v.get('outcome') != 'stuck': continue
        end = next((s for s in reversed(v['steps']) if s.get('status') == 'stuck'), None)
        if not end: continue
        blocker = next((s for s in reversed(v['steps']) if s.get('hit') and end['order'] - s['order'] <= 2), None)
        hit = blocker['hit'] if blocker else None
        if hit:
            u = urlsplit(hit['url']); key = (hit['kind'], u.hostname, u.path.rstrip('/'), hit['label'] if hit['kind'] == 'needs_account' else '')
            place = {'kind': hit['kind'], 'page': hit['url'], 'page_text': hit['page_text'], 'what_happened': hit['what_happened']}
            shot = hit['screenshot']; order = blocker['order']
        else:
            u = urlsplit(end.get('url') or ''); key = ('gave_up_here', u.hostname, u.path.rstrip('/'), v['id'])  # different goals, so never merged
            place = {'kind': 'gave_up_here', 'page': end.get('url'), 'page_text': end.get('page_text', ''),
                     'what_happened': 'Stopped on this page without finding a way forward.'}
            shot = end.get('screenshot'); order = end['order']
        fix = groups.setdefault(key, {'title': '', 'said': '', **place, 'evidence': []})
        said = own_words(end.get('say', '')); gave_up = bool(end.get('gave_up'))
        if not fix['said'] and said: fix['said'] = said
        if not fix['title'] and not gave_up and own_words(end.get('wish')): fix['title'] = end['wish']
        fix['evidence'].append({'visitor': v['id'], 'name': v['name'], 'goal': v.get('goal', ''), 'step': order, 'screenshot': shot, 'said': said})
    fixes = []
    for fix in groups.values():
        fix['count'] = len(fix['evidence'])
        if not fix['title']: fix['title'] = fix['said'] or fix['what_happened']
        fixes.append(fix)
    fixes.sort(key=lambda f: -f['count'])
    return fixes, ('' if fixes else NO_FIX_NOTE)


def headline(visitors):
    n = len(visitors); through = sum(v['outcome'] == 'got_there' for v in visitors)
    stuck = sum(v['outcome'] == 'stuck' for v in visitors); left = sum(v['outcome'] == 'left_app' for v in visitors); other = n - through - stuck - left
    if n and through == n: text = f'All {n} test visitors got through.'
    else:
        text = f'{through} of {n} test visitors got through.'
        if stuck: text += f' {stuck} got stuck.'
    if left: text += f' {left} left for another site.'
    if other: text += f' {other} did not finish.'
    return text


# ---- the browser ---------------------------------------------------------------------

COLLECT = r'''max => {
  const out = [], seen = new Set();
  document.querySelectorAll('[data-visit-n]').forEach(e => e.removeAttribute('data-visit-n'));
  for (const e of document.querySelectorAll('a[href],button,[role=button],[role=link],[role=tab],summary')) {
    const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    if (r.width < 4 || r.height < 4 || st.visibility === 'hidden' || st.display === 'none' || e.disabled) continue;
    const text = (e.innerText || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ').slice(0, 70);
    if (!text) continue;
    const href = e.tagName === 'A' ? e.href : '';
    if (href && href.split('#')[0] === location.href.split('#')[0]) continue;  // a link to the page you are on
    const key = text + '|' + href;
    if (seen.has(key)) continue;
    seen.add(key);
    e.setAttribute('data-visit-n', String(out.length + 1));
    out.push({n: out.length + 1, tag: e.tagName.toLowerCase(), text, href, inForm: !!e.closest('form'), type: e.getAttribute('type') || ''});
    if (out.length >= max) break;
  }
  return out;
}'''


def _visit_one(p, person, client, budget, url, seed, t0, publish, shared, tag='t1', temperature=0):
    """One visitor, one browser, one goal. Returns the visitor row."""
    from playwright.sync_api import sync_playwright
    row = {'id': person['id'], 'name': person['name'], 'goal': person['goal'], 'colour': person['colour'],
           'phone': bool(person.get('phone')), 'max_steps': person['max_steps'], 'status': 'running', 'outcome': None,
           'steps': [], 'start_ms': round((time.monotonic() - t0) * 1000), 'sceptic': bool(person.get('sceptic')), 'blocked': [], 'claimed': False, 'screen_confirmed': False, 'confirmed': False}
    publish(row)
    host = urlsplit(url).hostname; nav = {'status': None}; history = []; note = ''; offset = 0; tried = {}; refused = set(); at = {'step': 0}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            w, h = person['viewport']
            context = browser.new_context(viewport={'width': w, 'height': h}, is_mobile=bool(person.get('phone')),
                                          has_touch=bool(person.get('phone')), device_scale_factor=1)
            def route(rt):
                req = rt.request; clean = urlsplit(req.url)._replace(query='', fragment='').geturl()
                if not is_plain_read(req.method, req.url, req.post_data if req.method == 'POST' else None):
                    shared['blocked'].append({'visitor': person['id'], 'try': tag, 'method': req.method, 'url': clean})
                    row['blocked'].append({'step': at['step'], 'method': req.method, 'url': clean}); rt.abort(); return
                if req.method == 'POST': shared['read_posts'].append({'visitor': person['id'], 'url': clean})
                rt.continue_()
            context.route('**/*', route); page = context.new_page(); page.set_default_timeout(8000)
            page.on('pageerror', lambda e: shared['errors'].append({'visitor': person['id'], 'error': str(e)[:300]}))
            def on_response(response):
                try:
                    if response.request.is_navigation_request() and response.frame == page.main_frame: nav['status'] = response.status
                except Exception: pass
            page.on('response', on_response)
            def _drive(page):
                nonlocal note, offset
                page.goto(url, wait_until='domcontentloaded', timeout=45000)
                try: page.wait_for_function('document.body && document.body.innerText.trim().length > 80', timeout=8000)
                except Exception: pass
                page.wait_for_timeout(600)
                for n in range(1, person['max_steps'] + 1):
                    began = time.monotonic(); at['step'] = n
                    full = page.locator('body').inner_text()
                    content = page.evaluate(completion_evidence.CONTENT_JS)
                    here = page.url.split('#')[0]
                    elements = [e for e in page.evaluate(COLLECT, MAX_CHOICES) if (e['text'], e['href']) not in tried.get(here, ())]
                    locked = [e['text'] for e in elements if (refusal(e, host) or '').startswith(('That needs', 'That would'))]
                    elements = [e for e in elements if e['text'] not in locked]
                    for shown, e in enumerate(elements, 1): e['mark'] = e['n']; e['n'] = shown
                    view = {'url': page.url, 'title': page.title(), 'http_status': nav['status'], 'offset': offset,
                            'text': full[offset:offset + PAGE_CHARS], 'text_total': len(full), 'elements': elements, 'locked': locked}
                    shot = f"v-{person['id']}-{tag}-{n:02d}.png"
                    page.screenshot(path=str(p / shot), full_page=False)
                    step = {'order': n, 'url': page.url, 'title': view['title'], 'http_status': nav['status'], 'screenshot': shot,
                            'page_text': re.sub(r'\s+', ' ', full[offset:offset + 420]).strip(), 'choices_seen': len(elements), 'needs_account': [x for x in locked if NEEDS_ACCOUNT.search(x)][:6],
                            'start_ms': round((began - t0) * 1000), 'status': 'thinking', 'action': None, 'say': ''}
                    row['steps'].append(step); publish(row)
                    step['page_evidence_text'] = content[:PAGE_CHARS]
                    # First the visitor says whether the task is completed on this screen, and points at the words.
                    note_claim = ''
                    if (here, offset) not in refused:
                        seen, seen_call = budget.call(client, look_messages(person, view), f"{tag}-{person['id']}-{n:02d}-look", seed, temperature)
                        look = parse_look(seen.text)
                        step['look'] = {**look, 'on_page': quote_on_page(look['quote'], full), 'model_ms': seen_call['ms'], 'usage': seen_call['usage']}
                        if look['found'] and step['look']['on_page']:
                            # A claim. A second call gets only the text of this screen and must agree.
                            row['claimed'] = True
                            trail = [{'url': x['url'], 'action': x.get('action'), 'target': x.get('target_text'), 'status': x.get('status')} for x in row['steps'][:-1]] + [{'url': page.url, 'action': 'look'}]
                            second, second_call = budget.call(client, confirm_messages(person, view['text'], trail), f"{tag}-{person['id']}-{n:02d}-confirm", seed, 0)
                            verdict = parse_confirm(second.text); agreed = confirmed(verdict, view['text'])
                            if verdict['done'] and not agreed: verdict['why'] = 'It said yes but pointed at no words on this screen that show it. ' + verdict['why']
                            state = completion(person['goal'], agreed, trail, evidence=verdict['evidence'], content=content, http_status=nav['status'])
                            step['claim'] = {'quote': look['quote'], 'confirmed': agreed, 'why': verdict['why']}; step['claim_evidence'] = verdict['evidence']
                            step['claim_state'] = state; step['trail'] = trail
                            step['confirm_call'] = {'model_ms': second_call['ms'], 'usage': second_call['usage']}
                            if agreed: row['screen_confirmed'] = True
                            if agreed and person.get('start_only'):
                                step.update({'action': 'done', 'quote': look['quote'], 'say': '', 'status': 'reached_start', 'screen': {'url': page.url, 'title': view['title']},
                                             'elapsed_ms': round((time.monotonic() - began) * 1000)})
                                row['outcome'] = 'reached_start'; publish(row); break
                            if state['state'] == 'job_completed':
                                row['confirmed'] = True
                                step.update({'action': 'done', 'quote': look['quote'], 'say': '', 'status': 'got_there', 'screen': {'url': page.url, 'title': view['title']},
                                             'elapsed_ms': round((time.monotonic() - began) * 1000)})
                                row['outcome'] = 'got_there'; publish(row); break
                            refused.add((here, offset))
                            note_claim = ('This screen fits your task, but the task has more parts. You still have to ' + ' and '.join(MOVES[m] for m in state['missing']) + '. ') if agreed else \
                                         ('You thought this screen completed your task. A check of the screen did not agree' + (': ' + verdict['why'] if verdict['why'] else '.') + ' ')
                    reply, call = budget.call(client, build_messages(person, view, history, n, note_claim + note), f"{tag}-{person['id']}-{n:02d}", seed, temperature)
                    move = parse_reply(reply.text)
                    step.update({'action': move['action'], 'say': move['say'], 'model_ms': call['ms'], 'usage': call['usage'], 'model_reply': reply.text[:900]})
                    note = ''; status = 'ok'
                    if move['action'] == 'confused':
                        status = 'confused'; note = 'Your last reply was not the JSON object asked for.'
                    elif move['action'] == 'stuck':
                        status = 'stuck'; step['wish'] = move['wish']
                    elif move['action'] == 'scroll':
                        if offset + PAGE_CHARS >= len(full): status = 'no_effect'; note = 'There is nothing further down this page.'
                        else: offset += PAGE_CHARS
                        page.evaluate('window.scrollBy(0, Math.round(innerHeight * 0.85))'); page.wait_for_timeout(350)
                    elif move['action'] == 'back':
                        before = page.url; nav['status'] = None
                        try: page.go_back(wait_until='domcontentloaded', timeout=8000)
                        except Exception: pass
                        page.wait_for_timeout(500); offset = 0
                        if page.url == before or page.url == 'about:blank':
                            status = 'no_effect'; note = 'There was no earlier page to go back to.'
                            if page.url == 'about:blank': page.goto(before, wait_until='domcontentloaded')
                    elif move['action'] == 'click':
                        target = next((e for e in elements if e['n'] == move['target']), None)
                        if not target: status = 'no_effect'; note = 'That is not one of the things you can click on this page.' if elements else 'There is nothing to click on this page. Go back, or say stuck.'
                        else:
                            step['target_text'] = target['text']; why = refusal(target, host)
                            tried.setdefault(here, set()).add((target['text'], target['href']))
                            if why and 'leaves the app' in why:
                                status = 'left_app'; step['reason'] = why; step['left_for'] = urlsplit(target['href']).hostname
                            elif why:
                                status = 'not_allowed'; step['reason'] = why; note = f"You tried '{target['text']}'. {why}"
                                if 'account' in why:
                                    step['hit'] = {'kind': 'needs_account', 'label': target['text'], 'url': page.url, 'screenshot': shot, 'page_text': step['page_text'],
                                                   'what_happened': f"Tried '{target['text']}'. It needs an account, so the visit could not go on that way."}
                            else:
                                before = page.url; nav['status'] = None
                                try:
                                    page.locator(f'[data-visit-n="{target["mark"]}"]').first.click(timeout=5000)
                                    try: page.wait_for_load_state('domcontentloaded', timeout=8000)
                                    except Exception: pass
                                    page.wait_for_timeout(900); offset = 0
                                    if urlsplit(page.url).hostname != host:
                                        step['reason'] = f'That left the app for {urlsplit(page.url).hostname}.'; status = 'not_allowed'
                                        note = f"'{target['text']}' left the app, so you were brought back."
                                        page.goto(before, wait_until='domcontentloaded'); page.wait_for_timeout(400)
                                    elif nav['status'] and nav['status'] >= 400:
                                        status = 'error_page'; step['http_status'] = nav['status']
                                        after = f"v-{person['id']}-{tag}-{n + 50:02d}.png"; page.screenshot(path=str(p / after), full_page=False)
                                        step['hit'] = {'kind': 'error_page', 'label': target['text'], 'url': page.url, 'screenshot': after,
                                                       'page_text': re.sub(r'\s+', ' ', page.locator('body').inner_text()[:420]).strip(),
                                                       'what_happened': f"Clicked '{target['text']}' and the page answered with error {nav['status']}."}
                                        note = f"'{target['text']}' opened a page that answered with error {nav['status']}."
                                    elif page.url == before and page.locator('body').inner_text() == full:
                                        status = 'no_effect'; note = f"You clicked '{target['text']}' and nothing visible changed."
                                    else: note = f"You clicked '{target['text']}' and a new view opened."
                                except Exception as e:
                                    status = 'no_effect'; step['reason'] = type(e).__name__; note = f"'{target['text']}' could not be clicked."
                    if n == person['max_steps'] and status not in ('got_there', 'stuck', 'left_app'):
                        step['gave_up'] = True; step['last_try'] = status; status = 'stuck'
                    step['status'] = status; step['elapsed_ms'] = round((time.monotonic() - began) * 1000)
                    history.append(f"{n}. {move['action']}" + (f" '{step.get('target_text')}'" if step.get('target_text') else '') + f" -> {status.replace('_', ' ')}")
                    publish(row)
                    if status in ('got_there', 'stuck', 'left_app'):
                        row['outcome'] = status
                        # Said it was done, was not confirmed, and ran out of steps without saying it was stuck.
                        if status == 'stuck' and step.get('gave_up') and row['claimed']: row['outcome'] = 'screen_only' if row['screen_confirmed'] else 'claimed'
                        if status == 'left_app': row['reason'] = f"Left for {step['left_for']} to look there. That is outside the app, so the visit ends here."
                        break
            try: _drive(page)
            except BudgetStop as e: row['outcome'] = 'not_finished'; row['reason'] = str(e)
            except Exception as e:
                row['outcome'] = 'not_finished'; row['reason'] = 'The visit broke off: ' + type(e).__name__; row['error_detail'] = str(e)[:300]
            _finish(row, t0, publish)      # the result is complete here; closing the browser can be slow and must not hold it up
            context.unroute_all(behavior='ignoreErrors'); context.close(); browser.close()
    except BudgetStop as e:
        row['outcome'] = 'not_finished'; row['reason'] = str(e)
    except Exception as e:
        if row['status'] != 'complete':
            row['outcome'] = 'not_finished'; row['reason'] = 'The visit broke off: ' + type(e).__name__
            row['error_detail'] = str(e)[:300]
    if row['status'] != 'complete': _finish(row, t0, publish)
    return row


def _finish(row, t0, publish):
    if not row['outcome']: row['outcome'] = 'not_finished'
    for step in row['steps']:
        if step['status'] == 'thinking': step['status'] = 'not_finished'
    row['status'] = 'complete'; row['end_ms'] = round((time.monotonic() - t0) * 1000)
    row['time_to_goal_ms'] = row['end_ms'] - row['start_ms'] if row['outcome'] in ('got_there', 'reached_start') else None
    publish(row)
    return row


def _early(work, wait=90):
    """Run browser work in its own thread and return what it emits, without waiting for the browser to close."""
    box = []; ready = threading.Event()
    def emit(value): box.append(value); ready.set()
    def body():
        try: work(emit)
        except Exception: pass
        ready.set()
    threading.Thread(target=body).start(); ready.wait(wait)
    return box[0] if box else None


def baseline(p, url, emit=lambda value: None):
    """Plain checks, no model. Kept apart from what the test visitors found."""
    from playwright.sync_api import sync_playwright
    errors = []; out = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True); page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.route('**/*', lambda rt: rt.continue_() if is_plain_read(rt.request.method, rt.request.url, rt.request.post_data if rt.request.method == 'POST' else None) else rt.abort())
            page.on('pageerror', lambda e: errors.append(str(e)[:300]))
            began = time.monotonic(); response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            try: page.wait_for_function('document.body && document.body.innerText.trim().length > 80', timeout=8000)
            except Exception: pass
            page.wait_for_timeout(500); chars = len(page.locator('body').inner_text().strip())
            status = response.status if response else None
            out = [{'label': 'The page loads', 'status': 'passed' if status and status < 400 else 'failed', 'detail': f'Answered {status} in {time.monotonic() - began:.1f}s'},
                   {'label': 'The page shows words', 'status': 'passed' if chars > 80 else 'failed', 'detail': f'{chars:,} characters of text. A sign-in wall or an error message would also pass this.'},
                   {'label': 'No script errors on load', 'status': 'passed' if not errors else 'failed', 'detail': f'{len(errors)} found'}]
            page.screenshot(path=str(p / 'step-01.png'), full_page=False); emit(out); page.unroute_all(behavior='ignoreErrors'); browser.close()
    except Exception as e:
        out = [{'label': 'The page loads', 'status': 'failed', 'detail': 'The page could not be opened: ' + type(e).__name__}]; emit(out)
    return out


def default_client_for(person):
    from sim.adapters import tokenfactory
    from sim.adapters.openai_compat import ChatClient
    return ChatClient(base_url=tokenfactory.BASE_URL, model=hosted_cost.MODEL, label='RUNTIME',
                      api_key=tokenfactory.load_key(), timeout=45.0)


READER_VERBS = {'read', 'find', 'see', 'view', 'browse', 'open', 'look', 'compare', 'start', 'check', 'search', 'explore', 'watch'}
PAST = {'run': 'ran', 'write': 'wrote', 'build': 'built', 'make': 'made', 'put': 'put', 'take': 'took', 'do': 'did', 'get': 'got', 'give': 'gave', 'find': 'found',
        'see': 'saw', 'go': 'went', 'keep': 'kept', 'send': 'sent', 'set': 'set', 'ship': 'shipped', 'plan': 'planned', 'log': 'logged', 'track': 'tracked'}
SAFE_JOB = 'Read one item and return to the list'
JOB_LABELS = {'model': 'Task guessed by the model, not checked by you', 'you': 'Task line set by you', 'fixed': 'Fixed task for the planted app',
              'fallback': 'We could not tell what visitors come to do; edit this line', 'none': 'No task could be read; edit this line'}


def job_label(source): return JOB_LABELS.get(source, JOB_LABELS['model'])


def visitor_task_problem(job, pages_text):
    """Why a task line is not something a visitor does on the site, or None. Read from words, no model.
    A line that names what the author did, or an act the pages only report in the past tense, is refused."""
    words = re.findall(r"[a-z']+", (job or '').lower())
    if not words: return 'There is no task.'
    verb = words[0]; text = pages_text or ''
    if verb in READER_VERBS: return None
    past = PAST.get(verb) or (verb + 'd' if verb.endswith('e') else verb + 'ed')
    if re.search(rf"\b(I|we)\b[^.\n]{{0,25}}\b{past}\b", text, re.I):
        return f"The pages report this in the past tense as something the author did (\"{past}\"). It is not what a visitor comes to do."
    if re.search(rf"\b{past}\b", text, re.I) and not re.search(rf"\b{verb}\b", text, re.I) and past != verb:
        return f"The pages only report this in the past tense (\"{past}\"). It is not something a visitor can do here."
    told = len(re.findall(r"\bI\s+\w+ed\b|\bI\s+(?:put|ran|wrote|built|made|got|did|took|found)\b|\bmy own\b", text))
    if told >= 3 and not needs_write(job):
        return 'These pages are an author telling what they did. A visitor reads or finds things here; this line names what the author does.'
    return None


def read_pages(url, limit=3):
    return _early(lambda emit: _read_pages(url, limit, emit)) or []


def _read_pages(url, limit, emit):
    """Text of the first page and up to two more of the app's own pages. Read-only."""
    from playwright.sync_api import sync_playwright
    host = urlsplit(url).hostname; pages = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True); page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.route('**/*', lambda rt: rt.continue_() if is_plain_read(rt.request.method, rt.request.url, rt.request.post_data if rt.request.method == 'POST' else None) else rt.abort())
        def grab(address):
            page.goto(address, wait_until='domcontentloaded', timeout=30000)
            try: page.wait_for_function('document.body && document.body.innerText.trim().length > 80', timeout=6000)
            except Exception: pass
            page.wait_for_timeout(400)
            pages.append((page.url, page.title(), re.sub(r'[ \t]+', ' ', page.locator('body').inner_text())[:1800]))
        grab(url)
        links = [e for e in page.evaluate(COLLECT, 60) if e['href'] and refusal(e, host) is None]
        liked = re.compile(r'about|how|what|feature|doc|install|start|pricing|guide|faq', re.I)
        links.sort(key=lambda e: 0 if liked.search(e['text'] + ' ' + urlsplit(e['href']).path) else 1)
        seen = {url.split('#')[0].rstrip('/')}
        for e in links:
            if len(pages) >= limit: break
            address = e['href'].split('#')[0]
            if address.rstrip('/') in seen: continue
            seen.add(address.rstrip('/'))
            try: grab(address)
            except Exception: pass
        emit(pages); page.unroute_all(behavior='ignoreErrors'); browser.close()
    return pages


def discover_job(root, url, client=None):
    """Read the app's own pages and have the model say what people come to do. Asked once per address, then kept."""
    folder = Path(root) / 'app-jobs'; key = hashlib.sha256(url.rstrip('/').encode()).hexdigest()[:24]; kept = folder / (key + '.json')
    if kept.exists(): return tool_trial.read(kept)
    pages = read_pages(url)
    if not pages: return {'text': '', 'what': '', 'source': 'none', 'pages_read': []}
    text = '\n\n'.join(f'PAGE {address}\nTitle: {title}\n{body}' for address, title, body in pages)
    read = [address for address, _, _ in pages]; budget = Budget(str(folder / key), 2); rejected = []; note = ''; out = None
    messages = [{'role': 'system', 'content': JOB}, {'role': 'user', 'content': text}]
    for attempt in (1, 2):      # ask, and ask again once when the line is not a visitor's task
        reply, call = budget.call(client or default_client_for(None), messages, f'job-{attempt}-' + stamp(), 0)
        parsed = parse_job(reply.text)
        problem = visitor_task_problem(parsed['job'], text) if parsed else 'The reply held no task.'
        if not problem:
            out = {'text': parsed['job'], 'what': parsed['what'], 'source': 'model', 'pages_read': read, 'asked': attempt, 'rejected': rejected}; break
        rejected.append(parsed['job'] if parsed else ''); note = problem
        messages = messages[:2] + [{'role': 'assistant', 'content': reply.text[:400]},
                                   {'role': 'user', 'content': problem + ' Name one thing a VISITOR does on this site: read, find, compare or start something. Reply with the JSON object again.'}]
    if not out:
        out = {'text': SAFE_JOB, 'what': '', 'source': 'fallback', 'pages_read': read, 'asked': 2, 'rejected': rejected,
               'note': 'We could not tell what visitors come to do. Edit this line.', 'why_rejected': note}
    folder.mkdir(parents=True, exist_ok=True); tool_trial.dump(kept, out)
    return out


def _place(v):
    """Where a stuck visitor stopped: the last thing in its way, or the page where it gave up."""
    end = next((s for s in reversed(v['steps']) if s.get('status') == 'stuck'), None)
    if not end: return None
    blocker = next((s for s in reversed(v['steps']) if s.get('hit') and end['order'] - s['order'] <= 2), None)
    if blocker:
        hit = blocker['hit']; u = urlsplit(hit['url'])
        return {'key': (hit['kind'], u.hostname, u.path.rstrip('/') + '?' + u.query, ''), 'kind': hit['kind'], 'page': hit['url'], 'page_text': hit['page_text'],
                'what_happened': hit['what_happened'], 'screenshot': hit['screenshot'], 'step': blocker['order'], 'end': end}
    u = urlsplit(end.get('url') or ''); doors = end.get('needs_account') or []
    what = 'Stopped on this page without finding a way forward.' + (' On this page, these need an account: ' + ', '.join(doors) + '.' if doors else '')
    return {'key': ('gave_up_here', u.hostname, u.path.rstrip('/') + '?' + u.query, v.get('goal', '')), 'kind': 'gave_up_here', 'page': end.get('url'),
            'page_text': end.get('page_text', ''), 'what_happened': what, 'screenshot': end.get('screenshot'), 'step': end['order'], 'end': end}


def summarize(tries, needs_write=False):
    """Put the tries side by side. A visitor's verdict and every finding need two of three tries to agree.
    The sceptic has its own question and is counted apart. A task that needs a write is never reported as done."""
    n = len(tries); need = 2 if n >= 3 else n; ids = [v['id'] for v in tries[0]]
    visitors = []; groups = {}; order = []; sceptic = None
    for vid in ids:
        rows = [next((v for v in t if v['id'] == vid), None) for t in tries]; rows = [v for v in rows if v]
        outcomes = [v.get('outcome') or 'not_finished' for v in rows]; apart = bool(rows[0].get('sceptic'))
        confirmed_n = outcomes.count('got_there'); stuck = outcomes.count('stuck'); screen = sum(bool(v.get('screen_confirmed')) or v.get('outcome') == 'got_there' for v in rows)
        if apart:
            verdict = 'sceptic'; sceptic = {'name': rows[0]['name'], 'goal': rows[0].get('goal', ''), 'outcomes': outcomes, 'answered': confirmed_n, 'tries': n}
        elif needs_write: verdict = 'reaches_start' if screen >= need else 'gets_stuck' if stuck >= need else 'unclear'
        else: verdict = 'gets_through' if confirmed_n >= need else 'gets_stuck' if stuck >= need else 'unclear'
        visitors.append({**{k: rows[0].get(k) for k in ('id', 'name', 'goal', 'colour', 'phone', 'max_steps')}, 'sceptic': apart, 'outcomes': outcomes,
                         'claimed': sum(bool(v.get('claimed')) or v.get('outcome') in ('got_there', 'reached_start') for v in rows),
                         'screen_confirmed': screen, 'confirmed': 0 if needs_write and not apart else confirmed_n,
                         'verdict': verdict, 'agreement': max(outcomes.count(o) for o in set(outcomes))})
        for i, v in enumerate(rows):
            if v.get('outcome') != 'stuck': continue
            place = _place(v)
            if not place: continue
            end = place.pop('end'); key = place.pop('key')
            said = own_words(end.get('say', '')); gave_up = bool(end.get('gave_up'))
            if key not in groups: groups[key] = {'title': '', 'said': '', **{k: place[k] for k in ('kind', 'page', 'page_text', 'what_happened')}, 'evidence': [], 'per_visitor': {}, 'refused': 0}; order.append(key)
            g = groups[key]
            if not g['said'] and said: g['said'] = said
            if not g['title'] and not gave_up and own_words(end.get('wish')): g['title'] = end['wish']
            g['evidence'].append({'visitor': vid, 'name': v['name'], 'goal': v.get('goal', ''), 'try': i + 1, 'step': place['step'], 'screenshot': place['screenshot'], 'said': said})
            g['per_visitor'][vid] = g['per_visitor'].get(vid, 0) + 1; g['refused'] += len(v.get('blocked') or [])
    findings = []; set_aside = []; seen_once = 0; shown = set()
    for key in order:
        if max(groups[key]['per_visitor'].values()) >= need: shown.update(vid for vid, k in groups[key]['per_visitor'].items() if k >= need)
    # A visitor stuck in two of three tries, each time somewhere else, is still one finding.
    for v in visitors:
        loose = [e for key in order for e in groups[key]['evidence'] if e['visitor'] == v['id']]
        if n > 1 and v['id'] not in shown and len(loose) >= need:
            last = next(g for key in reversed(order) for g in [groups[key]] if any(e['visitor'] == v['id'] for e in g['evidence']))
            refused = sum(groups[key]['refused'] for key in order if any(e['visitor'] == v['id'] for e in groups[key]['evidence']))
            findings.append({'title': last['title'] or last['said'] or 'Stopped in a different place each time.', 'said': last['said'], 'kind': 'different_places', 'page': last['page'],
                             'page_text': last['page_text'], 'what_happened': f"Got stuck in {len(loose)} of {n} tries, on different pages. The screen shown is the last one.",
                             'evidence': loose, 'hits': len(loose), 'tries': n, 'count': len(loose), 'refused': refused})
            for key in order: groups[key]['evidence'] = [e for e in groups[key]['evidence'] if e['visitor'] != v['id']]; groups[key]['per_visitor'].pop(v['id'], None)
    for key in order:
        g = groups[key]
        if not g['evidence']: continue
        hits = max(g['per_visitor'].values())
        if hits < need: seen_once += len(g['evidence']); continue
        g.update({'hits': hits, 'tries': n, 'count': len(g['evidence'])}); g.pop('per_visitor')
        if not g['title']: g['title'] = g['said'] or g['what_happened']
        findings.append(g)
    # A stop in a visit where the rig refused one of the app's own requests may be the rig's doing. It is not offered as a fix.
    for g in findings:
        refused = g.pop('refused', 0)
        if refused:
            g['rig_suspect'] = True; g['what_happened'] += f' This is possibly caused by the test rig: it refused {refused} request{"" if refused == 1 else "s"} the app made during these visits.'
            set_aside.append(g)
    findings = sorted((g for g in findings if not g.get('rig_suspect')), key=lambda g: -g['count'])
    main = [v for v in visitors if not v['sceptic']]
    c = {'visitors': len(main), 'gets_through': sum(v['verdict'] == 'gets_through' for v in main),
         'gets_stuck': sum(v['verdict'] == 'gets_stuck' for v in main), 'unclear': sum(v['verdict'] == 'unclear' for v in main),
         'claimed': sum(v['claimed'] for v in main), 'screen_confirmed': sum(v['screen_confirmed'] for v in main), 'confirmed': sum(v['confirmed'] for v in main),
         'sessions': n * len(main), 'same_every_try': sum(v['agreement'] == n for v in main)}
    how = f'in at least {need} of {n} tries' if n > 1 else 'in one try'
    if needs_write:
        c['reaches_start'] = sum(v['verdict'] == 'reaches_start' for v in main)
        text = ('The task itself was not tested: it needs sign-in or saves something, and this tool only reads. '
                f"{c['reaches_start']} of {c['visitors']} test visitors reached the screen where it starts {how}.")
    else: text = f"{c['gets_through']} of {c['visitors']} test visitors got the job done {how}."
    if c['gets_stuck']: text += f" {c['gets_stuck']} got stuck."
    if c['unclear']: text += f" {c['unclear']} had no clear result."
    note = '' if findings else ('No finding showed up in at least two of three tries, so none is shown.' if n > 1 else NO_FIX_NOTE)
    return {'visitors': visitors, 'sceptic': sceptic, 'findings': findings, 'set_aside': set_aside, 'seen_once': seen_once, 'counts': c, 'headline': text, 'findings_note': note}


def run(p, personas=None, client_for=None, max_calls=None, run_cap_usd=RUN_CAP_USD):
    """Run every visitor, in one or three tries, write the result as it goes, return it."""
    p = Path(p); r = tool_trial.read(p / 'result.json'); client_for = client_for or default_client_for
    n = 3 if r.get('tries_planned') == 3 else 1; lock = threading.Lock(); t_run = time.monotonic()
    r.update({'status': 'running', 'browser': 'Playwright Chromium', 'model': hosted_cost.MODEL, 'provider': PROVIDER, 'tries_planned': n, 'tries': [], 'rounds': []})
    with lock: tool_trial.dump(p / 'result.json', r)
    if not (r.get('job') or {}).get('text'):
        found = {'text': CONTROL_JOB, 'source': 'fixed'} if r.get('control') else discover_job(p.parent.parent, r['url'])
        r['job'] = found if found.get('text') else {**found, 'text': SAFE_JOB, 'source': 'fallback'}
    r['job']['task_contract'] = task_contract.compile_task(r['job']['text']).payload()
    r['job']['needs_write'] = needs_write(r['job']['text']); r['job']['label'] = job_label(r['job'].get('source'))
    custom = personas is not None; personas = personas or personas_for(r['job']['text'])
    if not custom: r['cache_key'] = cache_key(r['url'], r['job']['text'], n)
    budget = Budget(str(p) + '/visit', max_calls or n * sum(3 * x['max_steps'] for x in personas), run_cap_usd)
    shared = {'blocked': [], 'errors': [], 'read_posts': []}
    r['baseline'] = _early(lambda emit: baseline(p, r['url'], emit)) or [{'label': 'The page loads', 'status': 'failed', 'detail': 'The page could not be opened in time.'}]
    for t in range(n):
        t0 = time.monotonic()
        r['tries'].append([{'id': x['id'], 'name': x['name'], 'goal': x['goal'], 'colour': x['colour'], 'phone': bool(x.get('phone')),
                            'max_steps': x['max_steps'], 'sceptic': bool(x.get('sceptic')), 'status': 'waiting', 'outcome': None, 'steps': []} for x in personas])
        r['rounds'].append({'try': t + 1, 'elapsed_ms': 0})
        def publish(row, t=t, t0=t0):
            with lock:
                r['tries'][t] = [row if v['id'] == row['id'] else v for v in r['tries'][t]]
                r['rounds'][t]['elapsed_ms'] = round((time.monotonic() - t0) * 1000)
                r['elapsed_ms'] = round((time.monotonic() - t_run) * 1000); tool_trial.dump(p / 'result.json', r)
        for i, person in enumerate(personas):
            threading.Thread(target=_visit_one, args=(p, person, client_for(person), budget, r['url'], t * 100 + i, t0, publish, shared, f't{t + 1}', 0.5 if n > 1 else 0)).start()
        deadline = time.monotonic() + 420      # each visitor reports when its result is complete; its browser may still be closing
        while time.monotonic() < deadline:
            with lock:
                if all(v.get('status') == 'complete' for v in r['tries'][t]): break
            time.sleep(0.2)
        with lock:
            for v in r['tries'][t]:
                if v.get('status') != 'complete': v.update({'status': 'complete', 'outcome': 'not_finished', 'reason': 'The visit did not end in time.'})
        r['rounds'][t]['elapsed_ms'] = max([v.get('end_ms', 0) for v in r['tries'][t]] + [0])
    s = summarize(r['tries'], r['job']['needs_write'])
    r.update({'visitors': s['visitors'], 'findings': s['findings'], 'fixes': s['findings'], 'fixes_note': s['findings_note'], 'seen_once': s['seen_once'], 'sceptic': s['sceptic'], 'set_aside': s['set_aside'],
              'headline': s['headline'], 'verdict': s['headline']})
    spend = budget.summary(); r['spend'] = spend
    r['model_calls'] = spend['model_calls']; r['model_cost_usd'] = spend['listed_rate_estimate_usd']
    r['counts'] = {**s['counts'], 'steps': sum(len(v['steps']) for t in r['tries'] for v in t)}
    if r.get('control'):
        ran = {v['id']: v for v in s['visitors']}
        failed = [x for x in CONTROL_MUST_FAIL if x in ran and ran[x]['confirmed'] == 0]
        r['control_result'] = {'must_fail': CONTROL_MUST_FAIL, 'failed_as_planted': failed, 'not_run': [x for x in CONTROL_MUST_FAIL if x not in ran],
                               'held': bool(failed) and all(ran[x]['confirmed'] == 0 for x in CONTROL_MUST_FAIL if x in ran)}
    r['raw'] = {'page_errors': shared['errors'], 'blocked_write_requests': shared['blocked'], 'allowed_read_posts': shared['read_posts']}
    r['held_back'] = len(shared['blocked'])
    r['limitations'] = ['Test visitors are an NVIDIA model reading and clicking your pages. They are not people, and nothing here is a quote from a real user.',
                        'They only read. Nothing was typed, no account was used, and anything behind sign-in was left untested.',
                        'Three states are kept apart. Claimed: the visitor said the job was done. Screen confirmed: a second call, given the steps and the text of that screen, agreed and pointed at words on it. Job completed: the steps also show every part the task names. A task that needs sign-in or a save is never counted as completed. The model calls can be wrong.']
    if shared['blocked']:
        r['limitations'].append(f"{len(shared['blocked'])} background requests from the app were held back because they were not plain reads. If part of a page did not load for the visitors, that can be the cause, not your app.")
    r.update({'status': 'complete', 'finished_at': stamp(), 'elapsed_ms': round((time.monotonic() - t_run) * 1000)})
    tool_trial.dump(p / 'result.json', r)
    return r
