"""Sequential private decision declarations. Local integrity, not trusted blinding."""
import datetime as dt
import json
import os
from sim import tool_trial as trial

STAGES=('initial','eval_only','reveal','forecast_informed')


def path(ws, id):
    from sim.workspace import identifier
    return ws.root/'tool-decision-protocols'/(identifier(id)+'.jsonl')


def forecast_identity(view):
    if view.get('status') not in ('sealed-unscored','scored'):raise ValueError('A verified sealed forecast is required.')
    return trial.digest({k:view[k] for k in ('contract','seal','probabilities','mode','forecast_source')})


def append(target, row):
    row['sha256']=trial.digest(row);target.parent.mkdir(exist_ok=True,mode=0o700)
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600),'a') as stream:
        stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())


def initialize(ws,id,contract,state,view,*,started=True):
    target=path(ws,id)
    if target.exists():raise ValueError('Decision protocol already exists.')
    origin='prospective_registration' if not started and state['status']=='prepared' and not state['episodes'] else 'existing_evidence_demo'
    append(target,{'schema':'tool-decision-protocol/1','revision':1,'stage':'initial','previous':None,
                   'contract':contract['sha256'],'forecast_identity':forecast_identity(view),'state_sha256':None,
                   'initial_choice':contract['initial_choice'],'choice':contract['initial_choice'],
                   'reason':'Initial choice copied from the frozen pre-run contract; this enrollment does not create an earlier choice.',
                   'origin':origin,'at':dt.datetime.now(dt.timezone.utc).isoformat()})


def read(ws,id,contract,state_sha,view):
    target=path(ws,id)
    if not target.exists():return None
    rows=[json.loads(line) for line in target.read_text().splitlines()]
    if not rows or len(rows)>4:raise ValueError('Decision protocol history is incomplete or invalid.')
    identity=forecast_identity(view);previous=None;timestamp=None
    for index,row in enumerate(rows):
        if (row.get('sha256')!=trial.digest({k:v for k,v in row.items() if k!='sha256'}) or row.get('revision')!=index+1
            or row.get('stage')!=STAGES[index] or row.get('previous')!=previous or row.get('contract')!=contract['sha256']
            or row.get('forecast_identity')!=identity or row.get('initial_choice')!=contract['initial_choice']
            or (index and row.get('state_sha256')!=state_sha) or row.get('origin')!=rows[0].get('origin')):
            raise ValueError('Decision protocol or bound evidence changed.')
        if (row.get('origin') not in ('prospective_registration','existing_evidence_demo')
            or (index==0 and row.get('choice')!=contract['initial_choice'])
            or (row['stage']=='reveal' and (row.get('choice') is not None or row.get('reason') is not None))
            or (row['stage']!='reveal' and row.get('choice') not in ('base','head','defer'))):
            raise ValueError('Decision protocol stage contents changed.')
        time=dt.datetime.fromisoformat(row['at'])
        if timestamp and time<timestamp:raise ValueError('Decision protocol time moved backwards.')
        timestamp=time;previous=row['sha256']
    return {'schema':'tool-decision-protocol/1','rows':rows,'next_stage':STAGES[len(rows)] if len(rows)<4 else None,
            'forecast_revealed':len(rows)>=3,'decision_changed':rows[1]['choice']!=rows[3]['choice'] if len(rows)==4 else None,
            'origin':rows[0]['origin'],'scope':'Sequential declaration only, not causal impact or improvement. Local filesystem access can unblind; this is not trusted blinding.'}


def redact(view,protocol):
    if protocol and not protocol['forecast_revealed']:
        return {'status':'sealed-hidden','contract':view['contract'],'mode':view['mode'],
                'forecast_identity':protocol['rows'][0]['forecast_identity'],
                'reason':'Record the eval-only choice, then explicitly reveal the already-sealed forecast.'}
    return view


def save(ws,body):
    from sim.tool_workspace import result,directory
    from sim.tool_forecast_view import review
    with ws.lock:
        if set(body)-{'id','expected','state_sha256','revision','stage','choice','reason'}:
            raise ValueError('Protocol timestamps and identity fields are controller-owned.')
        data=result(ws,body.get('id'));protocol=data.get('decision_protocol')
        if not protocol:raise ValueError('Open a new sealed comparison with the sequential decision protocol enabled.')
        rows=protocol['rows'];stage=body.get('stage')
        if stage!=protocol['next_stage'] or body.get('revision')!=len(rows):raise ValueError('Follow the decision stages in order; reopen the latest record.')
        if body.get('expected')!=data['contract']['sha256'] or body.get('state_sha256')!=data['state_sha256']:
            raise ValueError('Trial identity or outcome changed.')
        state=data['state'];expected={(a,s) for a in ('base','head') for s in data['contract']['seeds']}
        actual=[(e['arm'],e['seed']) for e in state['episodes']]
        if (state['status']!='complete' or len(actual)!=len(expected) or set(actual)!=expected
                or any(e.get('status') in ('running','not_started','not_started_after_failure') or not e.get('model_calls') for e in state['episodes'])
                or state.get('policy') not in ('local-shell-agent','local-model','tokenfactory-shell-agent')
                or state.get('model',{}).get('runtime')=='LOCAL_HTTP_TEST_DOUBLE'):
            raise ValueError('Complete the full registered direct-agent evaluation before recording this stage.')
        choice,reason=body.get('choice'),body.get('reason')
        if stage=='reveal':
            if choice is not None or reason is not None:raise ValueError('Reveal records exposure, not a release choice.')
        elif choice not in ('base','head','defer') or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000:
            raise ValueError('Choose baseline, candidate or defer and give a reason.')
        reference=trial.read(directory(ws,data['id'])/'forecast-reference.json');view=review(reference)
        now=dt.datetime.now(dt.timezone.utc)
        if now<dt.datetime.fromisoformat(rows[-1]['at']):raise ValueError('Controller clock moved backwards; no stage was appended.')
        row={'schema':'tool-decision-protocol/1','revision':len(rows)+1,'stage':stage,'previous':rows[-1]['sha256'],
             'contract':data['contract']['sha256'],'forecast_identity':forecast_identity(view),'state_sha256':data['state_sha256'],
             'initial_choice':data['contract']['initial_choice'],'choice':choice,'reason':reason.strip() if reason else None,
             'origin':protocol['origin'],'at':now.isoformat()}
        append(path(ws,data['id']),row)
        return result(ws,data['id'])
