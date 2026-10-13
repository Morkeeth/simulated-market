"""Owner-authored evaluator controls on exact frozen tools; never an agent trial."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from sim import ROOT, tool_trial as trial
from sim.standins.docker_sandbox import _docker

CODE=('sim/tool_preflight.py','sim/tool_trial.py','sim/tool_shell.py','sim/tool_gateway.py')


def code_hashes():
    return {name:trial.sha256_bytes((ROOT/name).read_bytes()) for name in CODE}


def validate_cases(cases):
    if not isinstance(cases,list) or not 2 <= len(cases) <= 6:
        raise ValueError('Declare two to six cases, including a known-valid task invocation and a meaningful wrong variant.')
    kinds=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'kind','label','reason','args','expected'}:
            raise ValueError('Each case needs kind, label, task-based reason, argv and expected outcomes for both versions.')
        if case['kind'] not in ('valid','wrong'):raise ValueError('Case kind must be valid or wrong.')
        kinds.add(case['kind'])
        for key in ('label','reason'):
            if not isinstance(case[key],str) or not 1 <= len(case[key].strip()) <= 2000:raise ValueError('Name each case and explain its expectation from the task requirements.')
        if not trial.strings(case['args'],empty=True) or len(case['args'])>80 or sum(map(len,case['args']))>8000:raise ValueError('Supply bounded literal tool arguments for each case.')
        expected=case['expected']
        if not isinstance(expected,dict) or set(expected)!={'base','head'} or any(type(v) is not bool for v in expected.values()):raise ValueError('Explicitly choose accept or reject for both versions.')
        if case['kind']=='valid' and not any(expected.values()):raise ValueError('A known-valid task case must be expected to pass on at least one version.')
        if case['kind']=='wrong' and any(expected.values()):raise ValueError('A wrong-task variant must be expected to fail on both versions.')
    if kinds!={'valid','wrong'}:raise ValueError('Include a known-valid task invocation and at least one wrong-task variant.')


def root(ws,id):
    from sim.workspace import identifier
    return ws.root/'tool-preflights'/identifier(id)


def latest(ws,id):
    folder=root(ws,id)
    if not (folder/'latest.json').exists():return None
    link=trial.read(folder/'latest.json');out=folder/link['id']
    plan=trial.read(out/'plan.json')
    if trial.digest(plan)!=link['plan']:raise ValueError('Evaluator preflight declaration changed.')
    state=trial.read(out/'state.json')
    if state.get('plan')!=link['plan']:raise ValueError('Preflight result belongs to another declaration.')
    if state['status'] in ('complete','failed'):
        value={k:v for k,v in state.items() if k!='sha256'}
        if trial.digest(value)!=state.get('sha256'):raise ValueError('Evaluator preflight result changed.')
    return {'id':link['id'],'plan':plan,'plan_sha256':link['plan'],'state':state}


def require_passed(ws,id,contract,policy):
    data=latest(ws,id)
    if not data or data['plan']['contract']!=contract or data['plan']['policy']!=policy:
        raise ValueError('Run evaluator preflight for this exact trial and selected scaffold before starting an agent.')
    if data['plan']['code']!=code_hashes():raise ValueError('Preflight controller changed. Run new controls before starting.')
    state=data['state'];expected={(a,i) for a in ('base','head') for i in range(len(data['plan']['cases']))}
    rows=state['rows']
    if state['status']!='complete' or len(rows)!=len(expected) or {(r['arm'],r['case']) for r in rows}!=expected or not all(r['matched'] for r in rows):
        raise ValueError('Evaluator preflight did not match all declared expectations. Inspect the mismatches before an agent run.')
    return data


def prepare(ws,body):
    from sim.tool_workspace import directory,result
    with ws.lock:
        id=body.get('id');path=directory(ws,id)
        if (path/'forecast-reference.json').exists():
            from sim.tool_forecast_workspace import owned
            relation=owned(ws,id)
            if relation is None:raise ValueError('Imported forecast batches are read-only here.')
            path=relation[0]/'trial'
        current=result(ws,id)
        if current['state']['status']!='prepared' or (path/'started.json').exists() or (path/'workspace-launch').exists() or (path.parent/'workspace-launch').exists():raise ValueError('Preflight belongs before execution. Preserve this run and prepare a new trial.')
        if body.get('expected')!=current['contract']['sha256']:raise ValueError('Reopen the exact frozen trial before preflight.')
        trial.verify(path,body['expected'],execution=True)
        policy=body.get('policy')
        if policy not in ('local-shell-agent','local-model','tokenfactory-shell-agent'):raise ValueError('Select the exact scaffold to preflight.')
        if current.get('forecastOwned') and policy!='local-shell-agent':raise ValueError('This sealed comparison uses the frozen local shell-agent scaffold.')
        cases=body.get('cases');validate_cases(cases)
        prior=latest(ws,id)
        if prior and prior['state']['status'] in ('queued','running'):raise ValueError('Evaluator preflight is already running.')
        folder=root(ws,id);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        runid=secrets.token_hex(12);out=folder/runid;out.mkdir(mode=0o700)
        plan={'schema':'tool-preflight/1','contract':body['expected'],'policy':policy,'cases':cases,'code':code_hashes(),
              'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'Owner-authored evaluator controls. No model, agent behavior or independent validation is measured.'}
        signature=trial.digest(plan);trial.dump(out/'plan.json',plan)
        trial.dump(out/'state.json',{'status':'queued','plan':signature,'rows':[]})
        trial.dump(folder/'latest.json',{'id':runid,'plan':signature})
        try:
            with (out/'worker.log').open('wb') as log:
                subprocess.Popen([sys.executable,'-m','sim.tool_preflight','--trial',str(path),'--output',str(out),'--expected',signature],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        except OSError as error:
            failed={'status':'failed','plan':signature,'rows':[],'passed':False,'error':'Controller could not start: '+str(error)}
            failed['sha256']=trial.digest(failed);trial.dump(out/'state.json',failed)
        return result(ws,id)


def run(path,out,expected):
    from sim import tool_shell
    path=Path(path);out=Path(out);plan=trial.read(out/'plan.json')
    if trial.digest(plan)!=expected or plan['code']!=code_hashes():raise ValueError('Frozen preflight declaration or controller changed.')
    frozen=trial.verify(path,plan['contract'],execution=True)
    fd=os.open(out/'started',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    state={'status':'running','plan':expected,'rows':[],'labels':['LOCAL','SCRIPTED-CONTROLS'],'model_calls':0}
    trial.dump(out/'state.json',state)
    try:
        checker=(path/'check.py').read_bytes()
        for arm in ('base','head'):
            for index,case in enumerate(plan['cases']):
                name='simpreflight-'+secrets.token_hex(8)
                row={'arm':arm,'case':index,'expected':case['expected'][arm],'matched':False}
                try:
                    if plan['policy'] in ('local-shell-agent','tokenfactory-shell-agent'):
                        setup=tool_shell.setup(frozen,path,arm,name)
                    else:
                        trial.container(frozen['image'],name);_docker('exec',name,'mkdir','-p','/work')
                        _docker('cp','-',name+':/work',input=(path/(arm+'.tar')).read_bytes())
                        setup=[]
                        for command in frozen['setup']:
                            value=trial.execute(name,['bash','-c',command]);setup.append({'command':command,**value})
                            if value['returncode']:break
                    row['setup']=setup
                    if any(r['returncode'] for r in setup):raise ValueError('Setup failed; this is not a successful evaluator rejection.')
                    if plan['policy'] in ('local-shell-agent','tokenfactory-shell-agent'):
                        _docker('exec','--user','1000:1000','-w','/agent',name,'tool',*case['args'],check=False,timeout=40)
                        records=tool_shell.records(name)
                        if len(records)!=1:raise ValueError('Expected one actual controller-owned invocation record.')
                        observation=records[0]
                    else:
                        observation={'args':case['args'],**trial.execute(name,frozen['command']+case['args'])}
                    check=trial.judge(frozen['image'],checker,observation)
                    row.update(observation=observation,check=check,matched=check['passed']==row['expected'])
                except Exception as error:row['error']=type(error).__name__+': '+str(error)[:500]
                finally:
                    _docker('rm','-f',name,check=False);state['rows'].append(row);trial.dump(out/'state.json',state)
        trial.verify(path,plan['contract'],execution=True)
        if plan['code']!=code_hashes():raise ValueError('Preflight controller changed during execution.')
        state['status']='complete';state['passed']=all(r['matched'] for r in state['rows'])
    except Exception as error:state.update(status='failed',error=type(error).__name__+': '+str(error)[:500],passed=False)
    state['sha256']=trial.digest(state);trial.dump(out/'state.json',state)
    return state


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for flag in ('trial','output','expected'):parser.add_argument('--'+flag,required=True)
    args=parser.parse_args();print(json.dumps(run(args.trial,args.output,args.expected)))
