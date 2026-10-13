"""Private read-only copies of MCP protocol/participant receipts. Never executes code."""
import datetime as dt
import json
from pathlib import Path
import secrets
import shutil
from sim import tool_trial as t

FIXTURE='5884d4eba7624c5ac9b2f0c8019db04bbe3ccc5734a49f76715d124f05c6610a'
CONDITIONS={'base':{'arm':'base','features':[]},'candidate-off':{'arm':'head','features':[]},'candidate-on':{'arm':'head','features':['markdown_output']}}
LIMITS={'files':2000,'copy_bytes':256*1024*1024,'json_bytes':8*1024*1024,'calls_per_condition':50,'display_characters_per_value':6000}
FLAW='Synthetic fixture limitation: advertised base/state filters and search q are ignored. Normal filtered queries can receive unfiltered rows. Do not attribute completion, latency or token differences to Markdown format.'

FIXTURE_V2='9c203f308066085c952545d874c75c209c6dbd1f78263541d1e4be3dbf69f5a3'
PROFILES={
    FIXTURE:{'id':'fixture-v1-three-condition','conditions':CONDITIONS,'registration_schema':'github-mcp-markdown-agent-registration/1','notice':FLAW,'scope':'Synthetic restricted MCP participant; no shell, human or owner acceptance.'},
    FIXTURE_V2:{'id':'fixture-v2-adaptive-pair','conditions':{k:CONDITIONS[k] for k in ('candidate-off','candidate-on')},'registration_schema':'github-mcp-markdown-agent-registration/2','notice':'Adaptive synthetic follow-up after the failed fixture-v1 batch. Corrected fixture-v2 applies supported filters. This off/on pair is exploratory; it is not an independent confirmation or evidence of a format benefit.','scope':'Same candidate executable, Markdown off/on; one synthetic task and one seed. Restricted local tool-use agent; no human or owner acceptance.'}
}


def profile(c):
    selected=PROFILES.get(c.get('fixture',{}).get('sha256'))
    if not selected or c.get('conditions')!=selected['conditions']:raise ValueError('MCP fixture/condition profile mismatch.')
    return selected


def checker_reason(ep):
    check=ep.get('checker') or {}
    try:return json.loads(check.get('output','')).get('reason')
    except (ValueError,AttributeError):return None


def read(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>LIMITS['json_bytes']:raise ValueError('Expected a bounded regular MCP receipt: '+path.name)
    return t.read(path)


def sealed(path):
    value=read(path);unsigned=dict(value);sha=unsigned.pop('sha256',None)
    if t.digest(unsigned)!=sha:raise ValueError('MCP receipt seal changed: '+path.name)
    return value


def frozen_session(path):
    c=sealed(path/'contract.json')
    if c.get('schema')!='local-mcp-session/1' or c.get('profile')!='github-markdown-response':raise ValueError('Import a supported frozen GitHub MCP profile.')
    profile(c)
    for name,sha in c['integrity'].items():
        if not t.safe_member(name) or t.sha256_bytes((path/name).read_bytes())!=sha:raise ValueError('Frozen MCP bytes changed: '+name)
    for arm in ('base','head'):
        if c['arms'][arm]['source_sha256']!=c['integrity'][arm+'.tar'] or c['arms'][arm]['binary_sha256']!=c['integrity'][arm+'.bin']:raise ValueError('MCP build identity mismatch.')
    if c['fixture']['sha256']!=c['integrity']['fixture.py']:raise ValueError('MCP fixture identity mismatch.')
    return c


def validate(root,mode):
    session=root/'session';c=frozen_session(session);selected=profile(c);conditions=selected['conditions']
    if mode=='protocol':
        if selected['id']!='fixture-v1-three-condition':raise ValueError('This corrected-fixture view requires its registered participant result.')
        result=read(session/'result.json')
        if result.get('contract')!=c['sha256'] or result.get('status') not in ('complete','failed') or set(result['conditions'])!=set(conditions):raise ValueError('Incomplete MCP protocol denominator or identity.')
        for label,row in result['conditions'].items():
            if row['arm']!=conditions[label]['arm'] or row['features']!=conditions[label]['features']:raise ValueError('MCP source/flag condition changed.')
            folder=session/label
            for name,sha in row['receipt_hashes'].items():
                if not t.safe_member(name) or t.sha256_bytes((folder/name).read_bytes())!=sha:raise ValueError('MCP protocol trace changed.')
            if 'session' in row and row['session']!=read(folder/'receipt/session.json'):raise ValueError('MCP session outcome changed.')
        return c,result,None,None
    participant=root/'participant';a=sealed(participant/'agent.json');r=sealed(root/'registration.json');result=read(participant/'result.json')
    if a.get('schema')!='local-mcp-participant/1' or a['session_contract']!=c['sha256'] or a['conditions']!=conditions or a['fixture_sha256']!=c['fixture']['sha256']:raise ValueError('Participant source/fixture identity changed.')
    if r.get('schema')!=selected['registration_schema'] or r['plan']['condition_definition']!=conditions:raise ValueError('Unsupported participant registration.')
    if r['agent_preparation_sha256']!=t.sha256_bytes((participant/'agent.json').read_bytes()) or r['session_contract_sha256']!=c['sha256'] or r['seed']!=a['seed']:raise ValueError('Participant registration identity changed.')
    if result.get('contract')!=a['sha256'] or result.get('registration')!=r['sha256'] or result.get('status') not in ('complete','failed'):raise ValueError('Only finalized registered MCP participants can be imported.')
    slots=[{'condition':label,'seed':a['seed']} for label in conditions]
    if sorted(r['slots'],key=lambda x:x['condition'])!=slots:raise ValueError('Registered MCP slots changed.')
    episodes=result['episodes']
    if len(episodes)!=len(conditions) or sorted(({'condition':e['condition'],'seed':e['seed']} for e in episodes),key=lambda x:x['condition'])!=slots:raise ValueError('Partial or duplicate participant denominator.')
    started=read(participant/'started.json')
    if started['contract']!=a['sha256'] or started['registration']!=r['sha256']:raise ValueError('Participant start identity changed.')
    for name,key in [('task.txt','task'),('check.py','checker')]:
        if t.sha256_bytes((participant/name).read_bytes())!=a[key]['sha256']:raise ValueError('Participant task/checker changed.')
    for ep in episodes:
        label=ep['condition'];folder=participant/'episodes'/label
        if ep['status'] in ('running','not_started'):raise ValueError('Participant slot is unfinished.')
        if ep['status']=='not_started_after_failure':
            if ep.get('completed') or ep.get('model_calls'):raise ValueError('Unstarted slot claims an outcome.')
            continue
        if ep!=read(participant/'episodes'/(label+'-episode.json')):raise ValueError('Participant episode trace changed.')
        if ep.get('submission')!=read(folder/'submission.json') or ep.get('checker')!=read(folder/'check.json'):raise ValueError('Final submission/checker receipt changed.')
        if ep['completed']!=(ep['status']=='submitted' and ep['checker']['complete']):raise ValueError('Task verdict differs from controller check.')
        session_state=read(folder/'receipt/session.json')
        if len(session_state['calls'])!=ep['mcp_calls']:raise ValueError('MCP call denominator changed.')
    return c,result,a,r


def bounded(value):
    raw=json.dumps(value,ensure_ascii=False,indent=2)
    return {'text':raw[:LIMITS['display_characters_per_value']],'omitted_characters':max(0,len(raw)-LIMITS['display_characters_per_value'])}


def view(root,id):
    receipt=read(root/'mcp-import.json')
    unsigned=dict(receipt);sha=unsigned.pop('sha256')
    if t.digest(unsigned)!=sha:raise ValueError('MCP import manifest changed.')
    for name,expected in receipt['files'].items():
        if not t.safe_member(name) or t.sha256_bytes((root/name).read_bytes())!=expected:raise ValueError('Copied MCP receipt changed: '+name)
    c,result,a,r=validate(root,receipt['mode']);selected=profile(c);conditions=selected['conditions'];rows=[]
    for label,condition in conditions.items():
        ep=next(e for e in result['episodes'] if e['condition']==label) if a else result['conditions'][label]
        folder=root/'participant/episodes'/label if a else root/'session'/label
        state=read(folder/'receipt/session.json') if (folder/'receipt/session.json').exists() else {}
        calls=state.get('calls',[])
        rows.append({'condition':label,'arm':condition['arm'],'features':condition['features'],'commit':c['arms'][condition['arm']]['commit'],
                     'status':ep['status'],'completed':ep.get('completed') if a else None,'model_calls':ep.get('model_calls',0),'mcp_calls':len(calls),
                     'submission':bounded(ep.get('submission')) if a else None,'checker':bounded(ep.get('checker')) if a else None,
                     'checker_reason':checker_reason(ep) if a else None,'finish_reasons':[e.get('finish_reason') for e in ep.get('events',[]) if e.get('status')=='returned'],'error':ep.get('error') or state.get('error'),'usage':ep.get('usage'),'elapsed_seconds':ep.get('elapsed_seconds'),
                     'initialized':bool(state.get('initialize')),'advertised_tools':len(state.get('tools',{}).get('tools',[])),
                     'calls':[{'request':bounded(x.get('request')),'result':bounded(x.get('result')),'status':x.get('status'),'server_pid':x.get('server_pid')} for x in calls[:LIMITS['calls_per_condition']]],
                     'omitted_calls':max(0,len(calls)-LIMITS['calls_per_condition'])})
    identity={'session':c['sha256'],'participant':a['sha256'] if a else None,'registration':r['sha256'] if r else None,'fixture':c['fixture'],
              'source':{arm:{key:row[key] for key in ('commit','source_sha256','binary_sha256')} for arm,row in c['arms'].items()},'image':c['image'],
              'task':a['task'] if a else None,'checker':a['checker'] if a else None,'seed':a['seed'] if a else None,'model':a['model'] if a else None}
    return {'kind':'mcp-recorded','id':id,'contract':{'sha256':a['sha256'] if a else c['sha256'],'name':receipt['label'],'created_at':receipt['at']},
            'state':{'status':result['status']},'import':{'label':receipt['label'],'at':receipt['at'],'scope':'Private display copy; no additional execution.'},
            'mcp':{'mode':receipt['mode'],'profile':selected['id'],'denominator':len(conditions),'accepted':sum(e['completed'] for e in result['episodes']) if a else None,'rows':rows,
                   'task':bounded((root/'participant/task.txt').read_text()) if a else None,'identity':identity,'limits':LIMITS,'flaw':selected['notice'],'scope':selected['scope'] if a else 'Scripted protocol controls only; no model ran.','decision_or_forecast':False}}


def import_record(ws,body):
    from sim.tool_workspace import directory
    if not isinstance(body.get('label'),str):raise ValueError('Use a text label.')
    label=body['label'].strip();mode=body.get('mode')
    if not label or len(label)>160 or mode not in ('participant','protocol'):raise ValueError('Choose MCP evidence type and a short label.')
    def selected(key):
        value=body.get(key)
        if not isinstance(value,str) or not value.strip():raise ValueError('Select '+key)
        return Path(value).expanduser().resolve()
    source=selected('path');session=selected('sessionPath') if mode=='participant' else source
    registration=selected('registrationPath') if mode=='participant' else None
    with ws.lock:
        id=secrets.token_hex(12);target=directory(ws,id);target.parent.mkdir(exist_ok=True,mode=0o700)
        pending=ws.root/('mcp-import-'+id);pending.mkdir(mode=0o700)
        try:
            total=0;count=0
            for folder,dest in [(session,pending/'session')]+([(source,pending/'participant')] if mode=='participant' else []):
                if not folder.is_dir() or folder.is_relative_to(ws.root):raise ValueError('Choose source receipts outside this workspace.')
                for file in folder.rglob('*'):
                    if file.is_symlink():raise ValueError('Do not import symlinked MCP receipts.')
                    if file.is_file():
                        count+=1;total+=file.stat().st_size
                        if count>LIMITS['files'] or total>LIMITS['copy_bytes']:raise ValueError('MCP receipt copy exceeds file/byte limit.')
                shutil.copytree(folder,dest)
            if registration:
                if registration.is_symlink() or registration.stat().st_size>LIMITS['json_bytes']:raise ValueError('Use a bounded regular registration file.')
                shutil.copy2(registration,pending/'registration.json')
            c,result,a,r=validate(pending,mode)
            key=t.digest({'mode':mode,'contract':a['sha256'] if a else c['sha256'],'result':t.sha256_bytes(((pending/'participant' if a else pending/'session')/'result.json').read_bytes())})
            for existing in target.parent.iterdir():
                if (existing/'mcp-import.json').exists() and read(existing/'mcp-import.json').get('key')==key:return view(existing,existing.name)
            files={str(f.relative_to(pending)):t.sha256_bytes(f.read_bytes()) for f in pending.rglob('*') if f.is_file()}
            receipt={'mode':mode,'label':label,'key':key,'at':dt.datetime.now(dt.timezone.utc).isoformat(),'files':files}
            receipt['sha256']=t.digest(receipt);t.dump(pending/'mcp-import.json',receipt)
            pending.rename(target);return view(target,id)
        finally:
            if pending.exists():shutil.rmtree(pending)
