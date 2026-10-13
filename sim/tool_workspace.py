"""Private workspace routes for versioned agent-facing tools."""
import os
import json
from pathlib import Path
import secrets
import subprocess
import sys
from sim import ROOT
from sim import tool_trial


def directory(ws, value):
    from sim.workspace import identifier
    return ws.root/'tools'/identifier(value)


def prepare(ws, body):
    with ws.lock:
        id=secrets.token_hex(12)
        tool_trial.prepare(body.get('contract'),directory(ws,id))
        return result(ws,id)


def start(ws, body):
    with ws.lock:
        path=directory(ws,body.get('id')); expected=body.get('expected')
        if (path/'forecast-reference.json').exists():
            from sim.tool_forecast_workspace import start as start_forecast
            return start_forecast(ws, body)
        tool_trial.verify(path,expected,execution=True)
        policy=body.get('policy','local-shell-agent')
        if policy=='tokenfactory-shell-agent':
            return start_sponsor(ws,body,path,expected)
        if not ws.allow_agents: raise ValueError('Start this private workspace with --allow-agents to enable local model trials.')
        if policy not in ('local-model','local-shell-agent'):raise ValueError('Choose a supported agent policy.')
        from sim.tool_preflight import require_passed
        require_passed(ws,body['id'],expected,policy)
        from sim.standins.local_model import SERVER_BIN
        if not SERVER_BIN.exists():raise ValueError('Cached local model runtime missing. Run make model before starting.')
        if policy=='local-shell-agent' and not (ROOT/'.venv-agent/bin/python').exists():raise ValueError('Cached mini-swe-agent runtime missing. Run make agent before starting.')
        # Reserve this workspace launch before spawning. CLI has its own atomic execution claim.
        fd=os.open(path/'workspace-launch',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        os.close(fd)
        log=(path/'worker.log').open('ab')
        try:
            process=subprocess.Popen([sys.executable,'-m','sim.tool_trial','run','--output',str(path),'--expected',expected,'--policy',policy],
                                     cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        finally: log.close()
        tool_trial.dump(path/'worker.json',{'pid':process.pid})
        return {'id':body['id'],'status':'starting'}


def result(ws, id):
    from sim.tool_decision import history
    from sim.tool_preflight import latest
    path=directory(ws,id); forecast=None; reference=None
    if (path/'mcp-import.json').exists():
        from sim.tool_mcp_view import view
        return view(path,id)
    if (path/'forecast-reference.json').exists():
        from sim.tool_forecast_view import review
        from sim.tool_forecast_workspace import owned
        reference=tool_trial.read(path/'forecast-reference.json')
        relation=owned(ws,id)
        forecast_owned=relation is not None
        forecast_error=tool_trial.read(relation[0]/'workspace-error.json')['error'] if relation and (relation[0]/'workspace-error.json').exists() else None
        forecast_launching=bool(relation and (relation[0]/'workspace-launch').exists() and not forecast_error and not (relation[0]/'trial'/'started.json').exists() and not (relation[0]/'score.json').exists())
        path=Path(reference['path'])/'trial'
        tool_trial.verify(path,reference['contract'])
        try: forecast=review(reference)
        except (ValueError,OSError,KeyError,TypeError) as error:
            forecast={'status':'invalid','error':str(error)}
    frozen=tool_trial.read(path/'contract.json')
    tool_trial.verify(path,frozen['sha256'])
    receipt=tool_trial.read(path/'import.json') if (path/'import.json').exists() else None
    state_raw=(path/'state.json').read_bytes(); state_sha=tool_trial.sha256_bytes(state_raw)
    if receipt and (receipt['contract']!=frozen['sha256'] or receipt['state_sha256']!=state_sha):
        raise ValueError('Imported outcome bytes changed; this display copy is invalid.')
    from sim.tool_decision_protocol import read as protocol_read, redact
    protocol=protocol_read(ws,id,frozen,state_sha,forecast)
    forecast=redact(forecast,protocol)
    public_url=tool_trial.read(path/'public-url.json') if (path/'public-url.json').exists() else None
    live_commands=[]
    if public_url:
        for arm in ('base','head'):
            for seed in frozen['seeds']:
                trace=path/(arm+'-'+str(seed)+'-agent.json')
                if trace.exists():
                    live_commands.append({'arm':arm,'seed':seed,
                                          'steps':tool_trial.read(trace).get('steps',[])})
    provider_receipt=None
    state=json.loads(state_raw)
    if state.get('policy')=='tokenfactory-shell-agent' and state.get('model',{}).get('runtime')=='token-factory' and (path/'services.jsonl').exists():
        rows=[json.loads(line) for line in (path/'services.jsonl').read_text().splitlines()]
        matched=[row for row in rows if row.get('service')=='chat' and row.get('identity_status')=='matched']
        provider_receipt={'model':state['model']['id'],
                          'matched_replies':len(matched),
                          'request_ids':[row['request_id'] for row in matched if row.get('request_id')],
                          'usage_totals':state.get('usage_totals',{}),
                          'controller_cost':state.get('cost',{}).get('controller_account')}
    return {'decision_protocol':protocol,'id':id,'contract':frozen,'state':state,'providerReceipt':provider_receipt,'allowAgents':ws.allow_agents and (reference is None or forecast_owned),'forecastOwned':bool(reference and forecast_owned),'forecastError':forecast_error if reference else None,'forecastLaunching':forecast_launching if reference else False,'import':receipt,
            'state_sha256':state_sha,'decisions':history(ws,id,frozen,state_sha),'forecast':forecast,'forecast_reference':reference,'preflight':latest(ws,id),'allowSponsor':bool(getattr(ws,'allow_sponsor',False) and reference is None and receipt is None),
            'sponsor':tool_trial.read(path/'sponsor-workspace-preview.json') if (path/'sponsor-workspace-preview.json').exists() else None,
            'publicPr':public_url,'liveCommands':live_commands}


def listing(ws):
    path=ws.root/'tools'
    trials=[result(ws,p.name) for p in path.iterdir() if p.is_dir()] if path.exists() else []
    return {'allowSponsor':bool(ws.allow_sponsor),
            'trials':sorted(trials,key=lambda row:(row['contract'].get('created_at',''),row['id']))}


def import_trial(ws, body):
    """Copy a completed CLI trial into the private viewer; never alter its evidence."""
    import datetime as dt
    import shutil
    from sim.doc import sha256_bytes
    with ws.lock:
        raw_path=body.get('path')
        label=body.get('label','');note=body.get('note','')
        if not isinstance(label,str) or not isinstance(note,str):raise ValueError('Label and review note must be text.')
        label=label.strip();note=note.strip()
        if not isinstance(raw_path,str) or not raw_path.strip():raise ValueError('Choose a completed local trial directory.')
        if not label or len(label)>160 or len(note)>2000:raise ValueError('Give the imported condition a short label; review notes are limited to 2000 characters.')
        source=Path(raw_path).expanduser().resolve()
        if not source.is_dir() or any(p.is_symlink() for p in source.rglob('*')):raise ValueError('Import a regular trial directory without symlinks.')
        contract=tool_trial.read(source/'contract.json');tool_trial.verify(source,contract['sha256'])
        state=tool_trial.read(source/'state.json')
        if state.get('status') not in ('complete','failed') or state.get('contract')!=contract['sha256']:raise ValueError('Only completed or failed trials with matching frozen identity can be imported.')
        state_sha=sha256_bytes((source/'state.json').read_bytes())
        root=ws.root/'tools';root.mkdir(exist_ok=True,mode=0o700)
        for existing in root.iterdir():
            if (existing/'import.json').exists():
                receipt=tool_trial.read(existing/'import.json')
                if receipt['contract']==contract['sha256'] and receipt['state_sha256']==state_sha:
                    return result(ws,existing.name)
        id=secrets.token_hex(12);target=directory(ws,id)
        shutil.copytree(source,target);target.chmod(0o700)
        tool_trial.dump(target/'import.json',{'label':label,'note':note,'source':str(source),
                        'at':dt.datetime.now(dt.timezone.utc).isoformat(),'contract':contract['sha256'],'state_sha256':state_sha,
                        'scope':'Display copy of one existing trial, not additional execution. Label and note are operator annotations.'})
        return result(ws,id)


def sponsor_preview(ws, body):
    from sim import tool_sponsor
    with ws.lock:
        path=directory(ws,body.get('id'))
        review=None
        if body.get('imageReviewPath'):
            review=json.loads(Path(body['imageReviewPath']).expanduser().read_text())
        preview=tool_sponsor.prepare(path,body.get('expected'),image_review=review)
        tool_trial.dump(path/'sponsor-workspace-preview.json',preview)
        return result(ws,body['id'])


def start_sponsor(ws, body, path, expected):
    """Validate locally before spawning; worker repeats exact consent checks."""
    if not ws.allow_sponsor: raise ValueError('Hosted execution is disabled. Start this private workspace with --allow-sponsor to enable it.')
    from sim import tool_sponsor
    digest=body.get('sponsorPreview')
    if not digest or body.get('sponsorConsent')!=digest:
        raise ValueError('Explicit consent must match the exact hosted preview.')
    gate=tool_sponsor.preflight(path,expected,digest)
    if gate['status']!='ready_to_call': raise ValueError('Hosted runtime is blocked: '+ '; '.join(gate['issues']))
    fd=os.open(path/'workspace-launch',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    log=(path/'worker.log').open('ab')
    try:
        process=subprocess.Popen([sys.executable,'-m','sim.tool_sponsor','--trial',str(path),'--expected',expected,
                                  '--preview',digest,'--consent',body['sponsorConsent'],'--allow-provider'],
                                 cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
    finally: log.close()
    tool_trial.dump(path/'worker.json',{'pid':process.pid})
    return {'id':body['id'],'status':'starting'}


def source_diff(ws, body):
    from sim.tool_diff import preview
    path=directory(ws,body.get('id'));expected=body.get('expected')
    if (path/'forecast-reference.json').exists():
        reference=tool_trial.read(path/'forecast-reference.json')
        if reference['contract']!=expected:raise ValueError('Selected trial identity changed.')
        path=Path(reference['path'])/'trial'
    return preview(path,expected)
