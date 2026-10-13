"""The test visitors: model-guided, bounded, replayable, and honest about what they hit.

No test here calls a provider. The model is a scripted double defined in this file.
"""
import json
import re
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from sim import ROOT, app_check, app_swarm, hosted_cost


class Reply(SimpleNamespace):
    pass


class Scripted:
    """Test double. Returns queued texts in order and counts calls."""
    model = hosted_cost.MODEL

    def __init__(self, texts):
        self.texts = list(texts); self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        text = self.texts.pop(0) if self.texts else '{"action":"stuck","say":"Nothing left to try."}'
        return Reply(text=text, model=self.model, usage={'prompt_tokens': 100, 'completion_tokens': 20},
                     finish_reason='stop')


@pytest.fixture(autouse=True)
def a_key_that_is_never_sent(monkeypatch):
    monkeypatch.setenv('TOKEN_FACTORY_API_KEY', 'test-value-never-sent')


@pytest.fixture
def account(tmp_path, monkeypatch):
    prior = tmp_path / 'prior.json'; prior.write_text(json.dumps({'runs': []}))
    record = tmp_path / 'cost.json'
    monkeypatch.setattr(hosted_cost, 'PRIOR', prior); monkeypatch.setattr(hosted_cost, 'RECORD', record)
    return record


def test_reply_is_parsed_and_nonsense_becomes_a_confused_step():
    good = app_swarm.parse_reply('```json\n{"action":"click","target":"3","say":"Docs, maybe."}\n```')
    assert good == {'action': 'click', 'target': 3, 'say': 'Docs, maybe.', 'wish': ''}
    assert app_swarm.parse_reply('{"action":"done","quote":"Free"}')['action'] == 'confused'
    assert app_swarm.parse_look('{"found": true, "quote": "Free for one person."}') == {'found': True, 'quote': 'Free for one person.'}
    assert app_swarm.parse_look('{"found": "yes"}')['found'] is False and app_swarm.parse_look('maybe')['found'] is False
    assert app_swarm.parse_reply('I would click the docs link')['action'] == 'confused'
    assert app_swarm.parse_reply('{"action":"format-disk"}')['action'] == 'confused'
    assert app_swarm.parse_reply('{"action":"click"}')['action'] == 'confused'


def test_a_visitor_only_gets_there_with_words_that_are_on_the_page():
    page = 'Lumen Notes\nFree for one person.  Teams pay 4 USD a month.'
    assert app_swarm.quote_on_page('free for one person. teams pay', page)
    assert not app_swarm.quote_on_page('Pricing starts at 9 USD', page)
    assert not app_swarm.quote_on_page('', page)
    assert not app_swarm.quote_on_page('free for one', page)


def test_links_that_need_an_account_or_change_data_are_never_clicked():
    host = 'app.example'
    def el(**kw): return {'text': 'Docs', 'href': 'https://app.example/docs', 'tag': 'a', 'inForm': False, 'type': '', **kw}
    assert app_swarm.refusal(el(), host) is None
    assert 'account' in app_swarm.refusal(el(text='Sign in'), host)
    assert 'account' in app_swarm.refusal(el(href='https://app.example/login', text='Go'), host)
    assert app_swarm.refusal(el(text='Delete project', tag='button', href=''), host)
    assert app_swarm.refusal(el(text='Go', tag='button', href='', inForm=True), host)
    assert 'leaves the app for github.com' in app_swarm.refusal(el(href='https://github.com/x/y', text='Source'), host)
    assert app_swarm.refusal(el(href='mailto:a@b.c', text='Mail us'), host)


def test_talk_about_the_test_rig_never_becomes_a_fix_and_an_old_blocker_is_not_blamed():
    old_hit = {'kind': 'needs_account', 'label': 'Sign in', 'url': 'https://x/', 'screenshot': 'v-phone-01.png', 'page_text': 'Home', 'what_happened': 'Tried Sign in.'}
    steps = [{'order': 1, 'status': 'not_allowed', 'hit': old_hit}, {'order': 2, 'status': 'ok'}, {'order': 3, 'status': 'ok'},
             {'order': 4, 'action': 'stuck', 'status': 'stuck', 'say': 'no number 1 to click', 'wish': 'add a number 1 to the list',
              'url': 'https://x/install', 'screenshot': 'v-phone-04.png', 'page_text': 'Install'}]
    fixes, _ = app_swarm.derive_fixes([visitor('phone', 'Phone', 'stuck', steps)])
    assert len(fixes) == 1 and fixes[0]['kind'] == 'gave_up_here' and fixes[0]['page'] == 'https://x/install'
    assert fixes[0]['title'] == 'Stopped on this page without finding a way forward.' and fixes[0]['said'] == ''


def test_only_plain_reads_leave_the_browser():
    ok = app_swarm.is_plain_read
    assert ok('GET', 'https://x/a') and not ok('DELETE', 'https://x/a') and not ok('PUT', 'https://x/a')
    assert ok('POST', 'https://db.example/rest/v1/rpc/read_day_card') and ok('POST', 'https://db.example/rest/v1/rpc/grinder_recent_builders')
    assert not ok('POST', 'https://db.example/rest/v1/rpc/save_run') and not ok('POST', 'https://db.example/rest/v1/rpc/thread_delete')
    assert not ok('POST', 'https://db.example/rest/v1/runs') and not ok('POST', 'https://x/api/feedback')
    assert ok('POST', 'https://x/graphql', '{"query":"query Feed { runs { id } }"}')
    assert not ok('POST', 'https://x/graphql', '{"query":"mutation { like(id: 1) }"}') and not ok('POST', 'https://x/graphql', 'not json')


def visitor(pid, name, outcome, steps):
    return {'id': pid, 'name': name, 'goal': 'g', 'outcome': outcome, 'steps': steps}


def test_no_fix_is_written_when_nobody_got_stuck():
    fixes, note = app_swarm.derive_fixes([visitor('a', 'A', 'got_there', [
        {'order': 1, 'action': 'done', 'say': 'Found it.', 'status': 'ok', 'url': 'https://x/', 'screenshot': 'v-a-01.png', 'page_text': 'hello'}])])
    assert fixes == []
    assert note == 'No test visitor got stuck in this run, so there is nothing to fix from it.'


def test_each_fix_points_at_the_step_the_screen_and_the_page_words():
    stuck = {'order': 3, 'action': 'stuck', 'say': 'I cannot find a price anywhere.', 'wish': 'Put the price on the first page.',
             'status': 'stuck', 'url': 'https://x/pricing', 'screenshot': 'v-buyer-03.png', 'page_text': 'Page not found. Go home.'}
    same = dict(stuck, order=2, screenshot='v-dev-02.png', say='No price here.', wish='')
    fixes, note = app_swarm.derive_fixes([
        visitor('buyer', 'Careful buyer', 'stuck', [{'order': 1, 'action': 'click', 'status': 'ok', 'say': 'Pricing.'}, stuck]),
        visitor('dev', 'Sceptical developer', 'stuck', [same]),
        visitor('new', 'First-time visitor', 'got_there', [{'order': 1, 'action': 'done', 'status': 'ok', 'say': 'Clear.'}]),
        visitor('late', 'Late', 'not_finished', [])])
    assert note == ''
    assert len(fixes) == 2      # two visitors with different goals on one page stay two fixes
    fix = fixes[0]
    assert fix['title'] == 'Put the price on the first page.'
    assert fix['said'] == 'I cannot find a price anywhere.'
    assert fix['page'] == 'https://x/pricing' and fix['page_text'] == 'Page not found. Go home.'
    assert fix['evidence'] == [{'visitor': 'buyer', 'name': 'Careful buyer', 'goal': 'g', 'step': 3, 'screenshot': 'v-buyer-03.png', 'said': 'I cannot find a price anywhere.'}]
    assert fixes[1]['title'] == 'No price here.' and fixes[1]['evidence'][0]['screenshot'] == 'v-dev-02.png'
    assert fix['count'] == 1 and fix['kind'] == 'gave_up_here'


def test_a_fix_points_at_the_thing_that_was_in_the_way_not_where_the_visitor_wandered_after():
    hit = {'kind': 'error_page', 'label': 'Pricing', 'url': 'https://x/pricing', 'screenshot': 'v-buyer-51.png', 'page_text': '404 Page not found',
           'what_happened': "Clicked 'Pricing' and the page answered with error 404."}
    fixes, _ = app_swarm.derive_fixes([visitor('buyer', 'Careful buyer', 'stuck', [
        {'order': 1, 'action': 'click', 'status': 'error_page', 'hit': hit, 'url': 'https://x/', 'screenshot': 'v-buyer-01.png'},
        {'order': 2, 'action': 'back', 'status': 'ok', 'url': 'https://x/pricing'},
        {'order': 3, 'action': 'stuck', 'status': 'stuck', 'say': 'The price link is broken.', 'wish': '', 'url': 'https://x/', 'screenshot': 'v-buyer-03.png', 'page_text': 'Home'}])])
    assert fixes == [{'title': 'The price link is broken.', 'said': 'The price link is broken.', 'kind': 'error_page', 'page': 'https://x/pricing',
                      'page_text': '404 Page not found', 'what_happened': "Clicked 'Pricing' and the page answered with error 404.", 'count': 1,
                      'evidence': [{'visitor': 'buyer', 'name': 'Careful buyer', 'goal': 'g', 'step': 1, 'screenshot': 'v-buyer-51.png', 'said': 'The price link is broken.'}]}]


def test_the_fixed_sentences_are_gone_from_the_product():
    source = (ROOT / 'sim/app_check.py').read_text() + (ROOT / 'sim/app_swarm.py').read_text()
    for old in ('Show one clear first action', 'Explain sign-in before blocking the path', 'Show an example before setup',
                'Make a first story easy to choose', 'Keep estimate and actual charge separate', 'reviewer hypotheses'):
        assert old not in source


def test_spend_control_caps_a_run_by_calls(account):
    budget = app_swarm.Budget('run-x', max_calls=2)
    client = Scripted(['{"action":"scroll","say":"a"}'] * 5)
    for n in (1, 2):
        budget.call(client, [{'role': 'user', 'content': 'x'}], f'p-{n:02d}', seed=0)
    with pytest.raises(app_swarm.BudgetStop, match='call limit'):
        budget.call(client, [{'role': 'user', 'content': 'x'}], 'p-03', seed=0)
    assert client.calls == 2
    rows = json.loads(account.read_text())['runs']
    assert sorted(rows) == ['run-x/p-01', 'run-x/p-02']
    assert all(row['status'] == 'usage_accounted' for row in rows.values())
    assert budget.summary()['model_calls'] == 2


def test_spend_control_refuses_at_the_shared_stop_without_touching_the_account(account):
    account.write_text(json.dumps({'runs': {'held': {'accounted_usd': 7.99, 'status': 'unknown_usage_reservation_held'}}}))
    before = account.read_bytes(); client = Scripted([])
    with pytest.raises(app_swarm.BudgetStop, match='shared spending stop'):
        app_swarm.Budget('run-y', max_calls=5).call(client, [{'role': 'user', 'content': 'x'}], 'p-01', seed=0)
    assert client.calls == 0 and account.read_bytes() == before


def test_spend_control_caps_a_run_in_dollars_when_calls_fail(account):
    class Broken(Scripted):
        def chat(self, messages, **kwargs):
            self.calls += 1; raise RuntimeError('chat call failed: URLError')
    client = Broken([]); budget = app_swarm.Budget('run-z', max_calls=50, run_cap_usd=0.08)
    for n in (1, 2):
        with pytest.raises(RuntimeError): budget.call(client, [{'role': 'user', 'content': 'x'}], f'p-{n:02d}', seed=0)
    with pytest.raises(app_swarm.BudgetStop, match='spending limit'):
        budget.call(client, [{'role': 'user', 'content': 'x'}], 'p-03', seed=0)
    assert client.calls == 2


def test_full_run_is_refused_when_test_visitors_are_off(tmp_path):
    ws = SimpleNamespace(root=tmp_path, allow_app_swarm=False)
    with pytest.raises(ValueError, match='switched off'):
        app_check.start(ws, {'url': 'https://example.com/', 'mode': 'swarm'})
    assert not list(tmp_path.glob('app-checks/*'))


def test_reopening_a_finished_run_costs_nothing(tmp_path, monkeypatch):
    ws = SimpleNamespace(root=tmp_path, allow_app_swarm=True)
    run = 'c' * 24; p = tmp_path / 'app-checks' / run; p.mkdir(parents=True)
    saved = {'id': run, 'status': 'complete', 'mode': 'swarm', 'url': 'https://example.com/', 'target': 'custom', 'name': 'example.com',
             'started_at': '2026-10-13T00:00:00+00:00', 'finished_at': '2026-10-13T00:01:00+00:00', 'visitors': [], 'fixes': [], 'model_calls': 7,
             'job': {'text': 'Read one essay', 'source': 'you'}, 'cache_key': app_swarm.cache_key('https://example.com', 'Read one essay', 3)}
    (p / 'result.json').write_text(json.dumps(saved))
    def boom(*a, **k): raise AssertionError('a replay must not spend or start a browser')
    monkeypatch.setattr(hosted_cost, 'reserve', boom); monkeypatch.setattr(app_check.subprocess, 'Popen', boom)
    again = app_check.start(ws, {'url': 'https://example.com', 'mode': 'swarm', 'job': 'Read one essay', 'tries': 3})
    assert again['id'] == run and again['replayed'] is True and again['model_calls'] == 7
    assert app_check.read(ws, run)['status'] == 'complete'
    assert len(list((tmp_path / 'app-checks').iterdir())) == 1


def test_saved_screens_of_test_visitors_can_be_served_and_nothing_else():
    assert app_check.MEDIA.fullmatch('step-01.png') and app_check.MEDIA.fullmatch('v-buyer-03.png') and app_check.MEDIA.fullmatch('v-buyer-t3-51.png')
    for bad in ('result.json', '../v-a-01.png', 'v-a-1.png', 'v-A-01.png', 'worker.log', 'v-buyer-t9-01.png'):
        assert not app_check.MEDIA.fullmatch(bad)


def test_human_page_keeps_plain_words_and_links_the_deeper_report():
    html = (ROOT / 'workspace/app-test.html').read_text(); js = (ROOT / 'workspace/app-test.js').read_text()
    assert '/agent-report' in js
    shown = re.sub(r'<style.*?</style>', '', html, flags=re.S) + js
    assert '—' not in shown and '–' not in shown
    for word in ('reading path', 'reviewer hypotheses', 'Recorded visit', 'usage estimate', 'review depths', 'PRIVATE PREVIEW', 'swarm', 'persona', 'LLM', 'prompt'):
        assert word not in re.sub(r'''['"]swarm['"]''', '', shown), word
    assert 'NVIDIA' in shown


def test_agent_report_reads_the_visit_before_the_older_script_cleans_the_address():
    html = (ROOT / 'workspace/tools.html').read_text()
    assert 0 < html.index('/visit-trace.js') < html.index('/tools.js')


# ---- second round: the app's own job, confirmed evidence, three tries, own machine ----

def serve_control():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(app_swarm.ControlHandler))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_job_is_read_from_the_apps_own_pages_and_kept(tmp_path, account):
    pytest.importorskip('playwright')
    server = serve_control()
    try:
        url = f'http://127.0.0.1:{server.server_port}/control/'
        client = Scripted(['{"what":"Lumen Notes turns meeting notes into a list of who does what.","job":"Turn a meeting into a list of decisions"}'])
        found = app_swarm.discover_job(tmp_path, url, client=client)
        again = app_swarm.discover_job(tmp_path, url, client=client)
    finally:
        server.shutdown()
    assert found['text'] == 'Turn a meeting into a list of decisions' and found['source'] == 'model'
    assert found['what'].startswith('Lumen Notes turns')
    assert found['pages_read'][0].endswith('/control/') and len(found['pages_read']) >= 2
    assert all('/login' not in page for page in found['pages_read'])
    assert again == found and client.calls == 1          # asked once, then kept
    assert app_swarm.parse_job('no idea') is None and app_swarm.parse_job('{"what":"x","job":""}') is None


def test_every_visitor_goal_comes_from_the_job_and_one_sceptic_stays():
    people = app_swarm.personas_for('Post a run from your coding agent')
    sceptics = [p for p in people if p.get('sceptic')]
    assert len(people) == 5 and len(sceptics) == 1
    assert all('Post a run from your coding agent' in p['goal'] for p in people if not p.get('sceptic'))
    assert 'Post a run' not in sceptics[0]['goal']
    assert len({p['id'] for p in people}) == 5 and len({p['character'] for p in people}) == 5


def test_the_confirming_call_sees_only_the_screen_text_and_needs_a_clear_yes():
    person = app_swarm.personas_for('Read one essay')[0]
    messages = app_swarm.confirm_messages(person, 'See a real sample run. Sign in to save.')
    assert messages[-1]['content'] == 'See a real sample run. Sign in to save.'
    assert 'Read one essay' in messages[0]['content'] and 'link' in messages[0]['content']
    assert app_swarm.parse_confirm('{"done": true, "why": "The essay text is on the screen."}') == {'done': True, 'evidence': '', 'why': 'The essay text is on the screen.'}
    assert app_swarm.parse_confirm('{"done": "true"}')['done'] is False and app_swarm.parse_confirm('yes it is')['done'] is False


def row(pid, outcome, page='https://x/pricing', claimed=False, say='No price.', kind=None):
    steps = [{'order': 2, 'action': 'stuck', 'status': 'stuck', 'say': say, 'wish': 'Show the price.', 'url': page, 'screenshot': f'v-{pid}-t1-02.png', 'page_text': 'words'}] if outcome == 'stuck' else \
            [{'order': 1, 'action': 'done', 'status': 'got_there', 'url': page, 'screenshot': f'v-{pid}-t1-01.png', 'quote': 'q'}] if outcome == 'got_there' else []
    return {'id': pid, 'name': pid.title(), 'goal': 'g', 'outcome': outcome, 'claimed': claimed or outcome == 'got_there', 'confirmed': outcome == 'got_there', 'steps': steps}


def test_a_finding_is_shown_only_when_two_of_three_tries_hit_it():
    tries = [[row('buyer', 'stuck'), row('phone', 'stuck', 'https://x/a'), row('reader', 'got_there'), row('newcomer', 'claimed', claimed=True)],
             [row('buyer', 'stuck'), row('phone', 'got_there'), row('reader', 'got_there'), row('newcomer', 'claimed', claimed=True)],
             [row('buyer', 'got_there'), row('phone', 'got_there'), row('reader', 'got_there'), row('newcomer', 'got_there')]]
    out = app_swarm.summarize(tries)
    by = {v['id']: v for v in out['visitors']}
    assert by['buyer']['outcomes'] == ['stuck', 'stuck', 'got_there'] and by['buyer']['verdict'] == 'gets_stuck' and by['buyer']['agreement'] == 2
    assert by['phone']['verdict'] == 'gets_through' and by['reader']['agreement'] == 3
    assert (by['newcomer']['claimed'], by['newcomer']['confirmed'], by['newcomer']['verdict']) == (3, 1, 'unclear')
    assert [(f['page'], f['hits'], f['tries']) for f in out['findings']] == [('https://x/pricing', 2, 3)]
    assert out['findings'][0]['title'] == 'Show the price.' and len(out['findings'][0]['evidence']) == 2
    assert out['seen_once'] == 1                      # the phone visitor's single stuck try is counted, not shown
    assert out['counts'] == {'visitors': 4, 'gets_through': 2, 'gets_stuck': 1, 'unclear': 1, 'claimed': 9, 'screen_confirmed': 7, 'confirmed': 7, 'sessions': 12, 'same_every_try': 1}
    assert out['headline'] == '2 of 4 test visitors got the job done in at least 2 of 3 tries. 1 got stuck. 1 had no clear result.'
    assert app_swarm.summarize([[row('buyer', 'stuck')]])['findings'][0]['tries'] == 1     # one try: shown, and labelled as one try


def test_a_local_address_needs_the_own_machine_switch(tmp_path, monkeypatch):
    ws = SimpleNamespace(root=tmp_path, allow_app_swarm=True)
    with pytest.raises(ValueError, match='own machine'):
        app_check.start(ws, {'url': 'http://127.0.0.1:3470/', 'mode': 'swarm'})
    assert not list(tmp_path.glob('app-checks/*'))
    started = []
    monkeypatch.setattr(app_check.subprocess, 'Popen', lambda *a, **k: started.append(a[0]))
    r = app_check.start(ws, {'url': 'http://127.0.0.1:3470/', 'mode': 'swarm', 'own_machine': True, 'job': 'Find a project to try', 'tries': 3})
    assert r['own_machine'] is True and r['job'] == {'text': 'Find a project to try', 'source': 'you'} and r['tries_planned'] == 3 and started
    assert not app_swarm.is_plain_read('POST', 'http://127.0.0.1:3470/api/vote')        # writes stay blocked there too
    with pytest.raises(ValueError):
        app_check.start(ws, {'url': 'http://169.254.169.254/', 'mode': 'swarm', 'own_machine': True})


def test_claimed_and_confirmed_are_kept_apart_on_the_planted_app(tmp_path, account):
    pytest.importorskip('playwright')
    server = serve_control()
    try:
        url = f'http://127.0.0.1:{server.server_port}/control/'
        p = tmp_path / 'run'; p.mkdir()
        (p / 'result.json').write_text(json.dumps({'id': 'd' * 24, 'url': url, 'name': 'control', 'mode': 'swarm', 'status': 'queued', 'control': True,
                                                   'job': {'text': 'See what Lumen Notes costs', 'source': 'fixed'}, 'tries_planned': 1}))
        no = '{"found":false,"quote":""}'
        script = {'buyer': [no, '{"action":"click","target":"Pricing","say":"Where is the price?"}',
                            no, '{"action":"stuck","say":"The pricing page is missing.","wish":"Make the Pricing link open a real page."}'],
                  # says the job is done on the first screen; the confirming call, which sees only the screen, says no
                  'reader': ['{"found":true,"quote":"Made for small teams that talk more than they write."}', '{"done":false,"why":"No price is on this screen."}',
                             '{"action":"stuck","say":"I see no price.","wish":"Put the price on the first page."}'],
                  'developer': ['{"found":true,"quote":"Lumen Notes keeps your meeting notes in one place"}', '{"done":true,"evidence":"Lumen Notes keeps your meeting notes in one place","why":"It explains what it does."}']}
        people = [x for x in app_swarm.personas_for('See what Lumen Notes costs') if x['id'] in script]
        def client_for(person):
            class ByName(Scripted):
                def chat(self, messages, **kwargs):
                    wanted = json.loads(self.texts[0]).get('target')
                    if isinstance(wanted, str):
                        n = re.search(r'^(\d+)\. \[[^\]]*\] ' + re.escape(wanted), messages[-1]['content'], re.M).group(1)
                        self.texts[0] = self.texts[0].replace('"' + wanted + '"', n)
                    return super().chat(messages, **kwargs)
            return ByName(script[person['id']])
        out = app_swarm.run(p, personas=people, client_for=client_for)
    finally:
        server.shutdown()
    by = {v['id']: v for v in out['tries'][0]}
    assert by['buyer']['outcome'] == 'stuck' and by['buyer']['steps'][0]['http_status'] == 404
    assert (by['reader']['claimed'], by['reader']['confirmed'], by['reader']['outcome']) == (True, False, 'stuck')
    assert by['reader']['steps'][0]['claim'] == {'quote': 'Made for small teams that talk more than they write.', 'confirmed': False, 'why': 'No price is on this screen.'}
    assert (by['developer']['claimed'], by['developer']['confirmed'], by['developer']['outcome']) == (True, True, 'got_there')
    assert by['developer']['steps'][0]['screen'] == {'url': url, 'title': 'Lumen Notes · Lumen Notes'}
    assert (p / 'v-buyer-t1-51.png').exists() and (p / by['reader']['steps'][0]['screenshot']).stat().st_size > 1000
    assert out['counts']['claimed'] == 1 and out['counts']['screen_confirmed'] == 0 and out['counts']['confirmed'] == 0      # the sceptic is counted apart
    assert out['sceptic']['answered'] == 1 and out['headline'] == '0 of 2 test visitors got the job done in one try. 2 got stuck.'
    assert by['developer']['steps'][0]['claim_state'] == {'state': 'job_completed', 'missing': []}
    assert [f['title'] for f in out['findings']] == ['Make the Pricing link open a real page.', 'Put the price on the first page.']
    assert out['findings'][0]['page'].endswith('/control/pricing') and out['findings'][0]['evidence'][0]['screenshot'] == 'v-buyer-t1-51.png'
    assert out['control_result'] == {'must_fail': ['newcomer', 'phone', 'buyer', 'reader'], 'failed_as_planted': ['buyer', 'reader'], 'not_run': ['newcomer', 'phone'], 'held': True}
    assert out['model_calls'] == 9 and out['status'] == 'complete' and out['job']['text'] == 'See what Lumen Notes costs'
    assert out['raw']['blocked_write_requests'] == []


def test_a_saved_result_is_only_replayed_for_the_same_task_and_setup(tmp_path, monkeypatch):
    ws = SimpleNamespace(root=tmp_path, allow_app_swarm=True)
    started = []
    monkeypatch.setattr(app_check.subprocess, 'Popen', lambda *a, **k: started.append(a[0]))
    first = app_check.start(ws, {'url': 'https://striverun.app/', 'mode': 'swarm', 'job': 'Bring in and preview your work', 'tries': 3})
    assert len(started) == 1 and first['cache_key'] == app_swarm.cache_key('https://striverun.app', 'Bring in and preview your work', 3)
    done = dict(first, status='complete', finished_at='2026-10-13T00:01:00+00:00', headline='old result')
    (tmp_path / 'app-checks' / first['id'] / 'result.json').write_text(json.dumps(done))
    # the reviewer's scenario: a new task on the same address must not come back as the old result
    other = app_check.start(ws, {'url': 'https://striverun.app/', 'mode': 'swarm', 'job': 'Read privacy and return', 'tries': 3})
    assert other.get('replayed') is not True and other['id'] != first['id'] and len(started) == 2
    assert other['job']['text'] == 'Read privacy and return'
    (tmp_path / 'app-checks' / other['id'] / 'result.json').write_text(json.dumps(dict(other, status='complete', finished_at='2026-10-13T00:02:00+00:00')))
    same = app_check.start(ws, {'url': 'https://striverun.app', 'mode': 'swarm', 'job': 'Bring in and preview your work.', 'tries': 3})
    assert same['replayed'] is True and same['id'] == first['id'] and len(started) == 2
    fewer = app_check.start(ws, {'url': 'https://striverun.app/', 'mode': 'swarm', 'job': 'Bring in and preview your work', 'tries': 1})
    assert fewer.get('replayed') is not True and len(started) == 3
    # the key moves with the goals, the model and the step limits
    key = app_swarm.cache_key('https://striverun.app', 'Bring in and preview your work', 3)
    monkeypatch.setattr(hosted_cost, 'MODEL', 'nvidia/another-model'); assert app_swarm.cache_key('https://striverun.app', 'Bring in and preview your work', 3) != key
    monkeypatch.undo()
    monkeypatch.setitem(app_swarm.CAST[0], 'max_steps', 9); assert app_swarm.cache_key('https://striverun.app', 'Bring in and preview your work', 3) != key
    monkeypatch.undo()
    # asking for the task line never hands back a result; it names the saved ones and their tasks
    monkeypatch.setattr(app_swarm, 'discover_job', lambda root, url: {'text': 'Post a run', 'what': 'x', 'source': 'model', 'pages_read': [url]})
    asked = app_check.job(ws, {'url': 'https://striverun.app/'})
    assert 'replay' not in asked and asked['text'] == 'Post a run'
    assert sorted(s['job'] for s in asked['saved']) == ['Bring in and preview your work', 'Read privacy and return']


def test_a_new_machine_gets_a_zero_spend_file_and_an_existing_one_is_never_touched(tmp_path, monkeypatch):
    prior = tmp_path / 'fresh' / 'hosted-spend.json'; record = tmp_path / 'fresh' / 'nvidia-live-cost.json'
    monkeypatch.setattr(hosted_cost, 'PRIOR', prior); monkeypatch.setattr(hosted_cost, 'RECORD', record)
    budget = app_swarm.Budget('run-new', max_calls=1)
    budget.call(Scripted(['{"action":"scroll"}']), [{'role': 'user', 'content': 'x'}], 'p-01', seed=0)      # no FileNotFoundError
    made = json.loads(prior.read_text())
    assert made['runs'] == [] and made['cap_usd'] == float(hosted_cost.LIMIT) and hosted_cost.prior_total() == 0
    assert oct(prior.stat().st_mode & 0o777) == '0o600'
    assert list(json.loads(record.read_text())['runs']) == ['run-new/p-01']
    # an account that already exists, with a held reservation, stays byte for byte the same
    prior.write_text('{"runs": [{"committed_usd": 0.486506}],  "note": "hand kept"}\n')
    record.write_text(json.dumps({'runs': {'old': {'accounted_usd': 4.614912, 'status': 'unknown_usage_reservation_held', 'reserved_upper_usd': 4.614912}}}))
    before = prior.read_bytes(); held = json.loads(record.read_text())['runs']['old']
    app_swarm.ensure_account()
    app_swarm.Budget('run-old', max_calls=1).call(Scripted(['{"action":"scroll"}']), [{'role': 'user', 'content': 'x'}], 'p-01', seed=0)
    assert prior.read_bytes() == before
    assert json.loads(record.read_text())['runs']['old'] == held


def test_without_a_model_key_a_full_run_stops_with_one_clear_setup_line(tmp_path, monkeypatch):
    from sim.adapters import tokenfactory
    monkeypatch.delenv('TOKEN_FACTORY_API_KEY', raising=False); monkeypatch.delenv('NEBIUS_API_KEY', raising=False)
    monkeypatch.setattr(tokenfactory, 'KEY_PATH', tmp_path / 'no.key')
    ws = SimpleNamespace(root=tmp_path, allow_app_swarm=True)
    for call, body in ((app_check.start, {'url': 'https://example.com/', 'mode': 'swarm', 'job': 'Read one essay'}), (app_check.job, {'url': 'https://example.com/'})):
        with pytest.raises(ValueError, match='TOKEN_FACTORY_API_KEY') as stop: call(ws, body)
        assert 'Saved runs still open' in str(stop.value)
    assert not list(tmp_path.glob('app-checks/*'))


def test_a_job_with_several_parts_needs_the_steps_not_only_the_last_screen():
    job = 'Read a story and return to the collection'
    person = app_swarm.personas_for(job)[0]
    home, story = 'https://labs.example/', 'https://labs.example/the-wrong-object'
    direct = [{'url': home, 'action': 'open'}]                                        # opened the collection and stopped
    full = [{'url': home, 'action': 'open'}, {'url': home, 'action': 'click', 'target': 'the wrong object'},
            {'url': story, 'action': 'back'}, {'url': home, 'action': 'look'}]         # read a story, came back
    assert app_swarm.required_moves(job) == ['went_somewhere', 'came_back']
    assert app_swarm.required_moves('Find the price') == []
    assert app_swarm.moves_made(direct) == [] and app_swarm.moves_made(full) == ['went_somewhere', 'came_back']
    assert app_swarm.moves_made([{'url': home, 'action': 'open'}, {'url': home, 'action': 'click'}, {'url': story, 'action': 'look'}]) == ['went_somewhere']
    # the same screen, confirmed by the second call in both cases, gives two different states
    assert app_swarm.completion(job, True, direct) == {'state': 'screen_confirmed', 'missing': ['went_somewhere', 'came_back']}
    assert app_swarm.completion(job, True, full) == {'state': 'job_completed', 'missing': []}
    assert app_swarm.completion(job, False, full)['state'] == 'claimed'
    assert app_swarm.completion('Find the price', True, direct)['state'] == 'job_completed'
    # and the confirming call is told what the visitor did, in order
    a = app_swarm.confirm_messages(person, 'The collection', direct); b = app_swarm.confirm_messages(person, 'The collection', full)
    assert a != b and a[-1] == b[-1] == {'role': 'user', 'content': 'The collection'}
    assert '3. On https://labs.example/the-wrong-object: back' in b[1]['content'] and '1. On https://labs.example/: open' in a[1]['content']


def test_a_task_that_needs_posting_can_never_be_completed_by_visitors_that_only_read():
    job = 'post your agent runs'
    assert app_swarm.required_moves(job) == ['wrote'] and app_swarm.required_moves('Sign up and read a story') == ['wrote']
    assert app_swarm.required_moves(app_swarm.personas_for('Read a story and return to the collection')[0]['goal']) == ['went_somewhere', 'came_back']
    feed = [{'url': 'https://striverun.app/', 'action': 'open'}, {'url': 'https://striverun.app/?post', 'action': 'look'}]
    assert app_swarm.completion(job, True, feed) == {'state': 'screen_confirmed', 'missing': ['wrote']}
    assert app_swarm.needs_write(job) and not app_swarm.needs_write('Read one essay') and not app_swarm.needs_write('Find the post about heart rate')
    assert 'made by other people' in app_swarm.CONFIRM and 'made by other people' in app_swarm.CONFIRM_START


def test_findings_keep_pages_apart_by_their_full_address_and_report_a_visitor_stuck_in_different_places():
    tries = [[row('phone', 'stuck', 'https://x/?people')], [row('phone', 'stuck', 'https://x/?post')], [row('phone', 'stuck', 'https://x/?post')]]
    out = app_swarm.summarize(tries)
    assert [(f['page'], f['hits']) for f in out['findings']] == [('https://x/?post', 2)] and out['seen_once'] == 1
    apart = app_swarm.summarize([[row('phone', 'stuck', 'https://x/a')], [row('phone', 'stuck', 'https://x/b')], [row('phone', 'got_there')]])
    assert len(apart['findings']) == 1 and apart['findings'][0]['kind'] == 'different_places' and apart['findings'][0]['hits'] == 2
    assert [e['try'] for e in apart['findings'][0]['evidence']] == [1, 2] and apart['seen_once'] == 0
    assert app_swarm.is_plain_read('POST', 'https://db.example/rest/v1/rpc/strava_profile_by_handle')


# ---- third round: say the limit on the verdict ----

def test_a_task_that_needs_a_write_is_never_reported_as_done_and_the_sceptic_is_counted_apart():
    def r(pid, outcome, page='https://x/pricing', claimed=False, **kw): return {**row(pid, outcome, page, claimed), 'screen_confirmed': outcome in ('got_there', 'reached_start'), **kw}
    tries = [[r('newcomer', 'reached_start'), r('phone', 'reached_start'), r('buyer', 'stuck'), r('reader', 'reached_start'), r('developer', 'got_there', sceptic=True)],
             [r('newcomer', 'reached_start'), r('phone', 'stuck', 'https://x/a'), r('buyer', 'stuck'), r('reader', 'claimed', claimed=True), r('developer', 'got_there', sceptic=True)],
             [r('newcomer', 'reached_start'), r('phone', 'reached_start'), r('buyer', 'reached_start'), r('reader', 'reached_start'), r('developer', 'stuck', 'https://x/docs', sceptic=True)]]
    out = app_swarm.summarize(tries, needs_write=True)
    assert 'got the job done' not in out['headline']
    assert out['headline'] == ('The task itself was not tested: it needs sign-in or saves something, and this tool only reads. '
                               '3 of 4 test visitors reached the screen where it starts in at least 2 of 3 tries. 1 got stuck.')
    assert out['counts']['visitors'] == 4 and out['counts']['sessions'] == 12 and out['counts']['confirmed'] == 0 and out['counts']['reaches_start'] == 3
    assert out['counts']['screen_confirmed'] == 8
    assert out['sceptic'] == {'name': 'Developer', 'goal': 'g', 'outcomes': ['got_there', 'got_there', 'stuck'], 'answered': 2, 'tries': 3}
    assert [v['verdict'] for v in out['visitors']] == ['reaches_start', 'reaches_start', 'gets_stuck', 'reaches_start', 'sceptic']
    plain = app_swarm.summarize([[r('newcomer', 'got_there'), r('developer', 'got_there', sceptic=True)]])
    assert plain['headline'] == '1 of 1 test visitors got the job done in one try.' and plain['sceptic']['answered'] == 1
    people = app_swarm.personas_for('post your agent runs')
    assert all(p.get('start_only') for p in people if not p.get('sceptic')) and 'where it starts' in people[0]['goal']
    assert not any(p.get('start_only') for p in app_swarm.personas_for('Read one essay'))
    assert 'post your agent runs' in app_swarm.confirm_messages(people[0], 'screen')[0]['content'] and 'begins' in app_swarm.confirm_messages(people[0], 'screen')[0]['content']


def test_a_confirmation_must_point_at_words_on_the_screen_that_show_the_act():
    yes = app_swarm.parse_confirm('{"done": true, "evidence": "Free for one person. Teams pay 4 USD a month.", "why": "The price is shown."}')
    assert yes == {'done': True, 'evidence': 'Free for one person. Teams pay 4 USD a month.', 'why': 'The price is shown.'}
    screen = 'Lumen Notes\nFree for one person. Teams pay 4 USD a month.'
    assert app_swarm.confirmed(yes, screen) is True
    assert app_swarm.confirmed(yes, 'Pricing\nSee our plans') is False                      # evidence is not on this screen
    assert app_swarm.confirmed(app_swarm.parse_confirm('{"done": true, "why": "Looks done."}'), screen) is False      # no evidence given
    assert app_swarm.confirmed(app_swarm.parse_confirm('{"done": false, "evidence": "Free for one person. Teams pay"}'), screen) is False
    assert 'not words that describe' in app_swarm.CONFIRM


def test_the_apps_own_read_calls_pass_only_writes_are_refused_and_a_refused_call_taints_the_finding():
    ok = app_swarm.is_plain_read
    assert ok('POST', 'https://db.example/rest/v1/rpc/strava_profile_by_handle') and ok('POST', 'https://db.example/rest/v1/rpc/day_card') and ok('GET', 'https://x/api/anything')
    for name in ('save_run', 'delete_account', 'insert_comment', 'update_profile', 'create_run', 'follow_builder', 'vote_up', 'send_feedback', 'set_visibility', 'track_event'):
        assert not ok('POST', 'https://db.example/rest/v1/rpc/' + name), name
    assert not ok('POST', 'https://db.example/rest/v1/runs') and not ok('PATCH', 'https://db.example/rest/v1/rpc/day_card')
    clean = row('buyer', 'stuck'); tainted = {**row('phone', 'stuck', 'https://x/profile'), 'blocked': [{'step': 1, 'method': 'POST', 'url': 'https://db.example/rest/v1/rpc/save_view'}]}
    out = app_swarm.summarize([[clean, tainted]])
    assert [f['page'] for f in out['findings']] == ['https://x/pricing']
    assert [(f['page'], f['rig_suspect']) for f in out['set_aside']] == [('https://x/profile', True)]
    assert 'possibly caused by the test rig' in out['set_aside'][0]['what_happened']


# ---- fourth round: the guessed task must be something a visitor does ----

LABS_TEXT = ('Oscar Labs\nEssays and drafts about building with coding agents.\nI graded six weeks of my own prompts.\n'
             'I put my Garmin heart rate and sleep over every coding agent session I have on record.\nI ran eleven experiments on my own work.\n'
             'I wrote the results down. 11 published.')


def test_a_task_line_must_be_something_a_visitor_does_on_the_site():
    bad = app_swarm.visitor_task_problem
    assert 'author' in bad('run experiments on personal coding agent sessions', LABS_TEXT)
    assert 'author' in bad('grade six weeks of prompts', LABS_TEXT)
    assert bad('Read one experiment and return to the list', LABS_TEXT) is None
    assert bad('Find the essay about heart rate', LABS_TEXT) is None
    shop = 'Lumen Notes keeps your meeting notes in one place. Record a meeting. Get the decisions as a list.'
    assert bad('Turn a meeting into a list of decisions', shop) is None and bad('post your agent runs', 'STRIVE is a place to post the runs your coding agents do.') is None
    assert 'past' in bad('launch the product', 'We launched the product in May. It launched to 400 people.')


def test_a_wrong_guess_is_asked_again_once_then_falls_back_with_a_visible_note(tmp_path, account, monkeypatch):
    monkeypatch.setattr(app_swarm, 'read_pages', lambda url: [(url, 'Oscar Labs', LABS_TEXT)])
    wrong = '{"what":"A research hub.","job":"run experiments on personal coding agent sessions"}'
    twice = Scripted([wrong, '{"what":"A research hub.","job":"Read one experiment about coding agents"}'])
    fixed = app_swarm.discover_job(tmp_path / 'a', 'https://labs.example/', client=twice)
    assert twice.calls == 2 and fixed['text'] == 'Read one experiment about coding agents' and fixed['source'] == 'model' and fixed['asked'] == 2
    stubborn = Scripted([wrong, wrong, wrong])
    fell = app_swarm.discover_job(tmp_path / 'b', 'https://labs.example/', client=stubborn)
    assert stubborn.calls == 2                                      # asked again once, not more
    assert fell['text'] == 'Read one item and return to the list' and fell['source'] == 'fallback'
    assert fell['note'] == 'We could not tell what visitors come to do. Edit this line.'
    assert fell['rejected'] == ['run experiments on personal coding agent sessions'] * 2


def test_a_run_on_an_unedited_guess_says_so_and_a_superseded_run_shows_no_counts(tmp_path):
    assert app_swarm.job_label('model') == 'Task guessed by the model, not checked by you'
    assert app_swarm.job_label('you') == 'Task line set by you' and 'edit this line' in app_swarm.job_label('fallback')
    js = (ROOT / 'workspace/app-test.js').read_text()
    assert 'Task guessed by the model, not checked by you' in js and 'superseded' in js
    ws = SimpleNamespace(root=tmp_path); run = 'e' * 24; p = tmp_path / 'app-checks' / run; p.mkdir(parents=True)
    (p / 'result.json').write_text(json.dumps({'id': run, 'status': 'complete', 'mode': 'swarm', 'url': 'https://labs.example/', 'name': 'Labs', 'started_at': 'x', 'finished_at': 'y',
                                               'headline': '3 of 4 test visitors got the job done in at least 2 of 3 tries.', 'counts': {'confirmed': 10}, 'visitors': [{'confirmed': 3}],
                                               'tries': [[{'id': 'newcomer', 'outcome': 'got_there'}]], 'job': {'text': 'run experiments', 'source': 'model'}}))
    (p / 'superseded.json').write_text(json.dumps({'by': 'f' * 24, 'why': 'The task line described what the author does.'}))
    seen = app_check.read(ws, run)
    assert seen['superseded']['by'] == 'f' * 24 and seen['headline'] == 'Superseded. Its completion counts are withdrawn.'
    assert 'counts' not in seen and 'visitors' not in seen and 'tries' not in seen and 'findings' not in seen
    assert app_check.listing(ws)['runs'][0]['superseded']


def test_the_phone_first_view_says_the_visitors_are_software_before_the_start_button():
    sync = pytest.importorskip('playwright.sync_api')
    line = 'These visitors are software, not people. They only read. Sign-in and saving are not tested.'
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch()
        phone = browser.new_page(viewport={'width': 390, 'height': 844}); phone.set_content((ROOT / 'workspace/app-test.html').read_text())
        note = phone.get_by_text(line, exact=True)
        assert note.count() == 1 and note.is_visible()
        assert note.bounding_box()['y'] < phone.locator('#try').bounding_box()['y']
        assert phone.evaluate('document.documentElement.scrollWidth') == 390
        desk = browser.new_page(viewport={'width': 1440, 'height': 900}); desk.set_content((ROOT / 'workspace/app-test.html').read_text())
        assert not desk.get_by_text(line, exact=True).is_visible()
        assert desk.get_by_text('They are not people.', exact=False).first.is_visible()     # the desktop text stays as it is
        phone.close(); desk.close()
