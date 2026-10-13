"""Genuine shell-agent trials on frozen tools with unforgeable local invocation records."""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from sim import ROOT
from sim import tool_trial as trial
from sim.standins.docker_sandbox import _docker

WRAPPER='''#!/usr/local/bin/python3
import json,socket,sys
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect('/run/tool.sock')
s.sendall((json.dumps(sys.argv[1:])+'\\n').encode());data=b''
while not data.endswith(b'\\n'):
 b=s.recv(65536)
 if not b:break
 data+=b
r=json.loads(data);print(r['output'],end='');sys.exit(r['returncode'])
'''


def setup(frozen,out,arm,name):
    _docker('run','--pull','never','-d','--network','none','--memory','512m','--cpus','1',
            '--pids-limit','128','--cap-drop','ALL','--cap-add','SETUID','--cap-add','SETGID',
            '--security-opt','no-new-privileges','--name',name,frozen['image'],'sleep','infinity')
    _docker('exec',name,'mkdir','-p','/work','/agent','/control')
    _docker('exec',name,'chmod','700','/control')
    _docker('exec',name,'chmod','777','/agent')
    _docker('cp','-',name+':/work',input=(out/(arm+'.tar')).read_bytes())
    rows=[]
    for command in frozen['setup']:
        result=trial.execute(name,['bash','-c',command]);rows.append({'command':command,**result})
        if result['returncode']:return rows
    # Freeze generated task data as well as tool source before the participant starts.
    _docker('cp','-',name+':/work',input=trial.archive({'DISCOVERY.md':(out/(arm+'.md')).read_bytes()}))
    _docker('exec',name,'chmod','-R','a-w','/work')
    config={'command':frozen['command'],'max_invocations':frozen['budget']}
    _docker('cp','-',name+':/control',input=trial.archive({'gateway.py':(ROOT/'sim/tool_gateway.py').read_bytes(),'gateway.json':json.dumps(config).encode()}))
    _docker('cp','-',name+':/usr/local/bin',input=trial.archive({'tool':WRAPPER.encode()}))
    _docker('exec','-d',name,'python3','/control/gateway.py')
    for _ in range(30):
        if _docker('exec',name,'test','-S','/run/tool.sock',check=False).returncode==0:break
        time.sleep(.1)
    else:raise RuntimeError('Local tool gateway did not start.')
    return rows


def records(name):
    p=_docker('exec',name,'cat','/control/invocations.jsonl',check=False)
    return [json.loads(line) for line in p.stdout.decode().splitlines()] if p.returncode==0 else []


def run(out,expected):
    from sim.standins.local_model import LocalModel,MODEL
    from sim.tool_shell_agent import MAX_TOKENS
    out=Path(out).resolve();frozen=trial.verify(out,expected,execution=True)
    python=ROOT/'.venv-agent/bin/python'
    if not python.exists():raise ValueError('Cached mini-swe-agent runtime missing. Run make agent first.')
    runtime=subprocess.run([str(python),'-c','import importlib.metadata; print(importlib.metadata.version("mini-swe-agent"))'],capture_output=True,text=True,check=True).stdout.strip()
    if runtime!='2.4.6':raise ValueError('This shell route requires mini-swe-agent 2.4.6.')
    registration={'contract':expected,'policy':'local-shell-agent','model':MODEL,'harness':'mini-swe-agent','harness_version':runtime,
                  'temperature':0,'max_tokens':MAX_TOKENS,'at':dt.datetime.now(dt.timezone.utc).isoformat(),
                  'code':{str(p.relative_to(ROOT)):trial.sha256_bytes(p.read_bytes()) for p in [ROOT/'sim/tool_shell.py',ROOT/'sim/tool_shell_agent.py',ROOT/'sim/tool_gateway.py',ROOT/'sim/agent_protocol.py']}}
    fd=os.open(out/'started.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(registration,stream,sort_keys=True)
    # Preserve exact runner sources beside the runtime registration for later replay/audit.
    for file in registration['code']:
        (out/(Path(file).name+'.frozen')).write_bytes((ROOT/file).read_bytes())
    state={'status':'running','contract':expected,'policy':'local-shell-agent','labels':['SIMULATED','LOCAL'],'episodes':[],
           'model':{k:registration[k] for k in ('model','harness','harness_version','temperature','max_tokens')},
           'cost':{'provider_charge_usd':0,'source':'Cached local model; hardware, electricity and setup costs unmeasured'},
           'limits':'Shell-capable coding agent. Fixed task and supplied tool, not adoption, organic discovery or voluntary reuse. Final registered invocation is checked; source calls bypassing gateway get no credit.'}
    trial.dump(out/'state.json',state);start=time.monotonic();server=LocalModel()
    try:
        checker=(out/'check.py').read_bytes()
        state['checker_negative_control']=trial.judge(frozen['image'],checker,{'args':[],'returncode':1,'output':''})
        if state['checker_negative_control']['passed']:raise ValueError('Checker accepted an empty failed invocation.')
        server.start()
        for arm in ('base','head'):
            for seed in frozen['seeds']:
                name='simtool-shell-'+secrets.token_hex(8)
                ep={'arm':arm,'seed':seed,'events':[],'status':'running','discovered':None,'setup_ok':False,'invoked':False,'valid_invocation':False,
                    'completed':False,'ever_completed':False,'recovered':False,'recovery_attempted':False,'model_calls':None,'usage':{},'shell_trace':[]}
                state['episodes'].append(ep);trial.dump(out/'state.json',state)
                episode_dir=out/(arm+'-'+str(seed));episode_dir.mkdir()
                try:
                    rows=setup(frozen,out,arm,name);ep['setup_ok']=all(r['returncode']==0 for r in rows)
                    ep['events'].append({'action':'controller_setup','commands':rows})
                    if not ep['setup_ok']:ep['status']='setup_failed';continue
                    snapshot=trial.execute(name,['python3','-c',"import pathlib,hashlib,json;print(json.dumps({str(p.relative_to('/work')):hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('/work').rglob('*') if p.is_file()},sort_keys=True))"])
                    if snapshot['returncode']:raise RuntimeError('Could not freeze task filesystem identity.')
                    trial.dump(episode_dir/'task-files.json',json.loads(snapshot['output']))
                    ep['task_files_sha256']=trial.sha256_bytes((episode_dir/'task-files.json').read_bytes())
                    task=episode_dir/'task.txt';task.write_text(frozen['task'])
                    env={k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')}
                    env.update(MSWEA_SILENT_STARTUP='1',MSWEA_GLOBAL_CONFIG_DIR=str(episode_dir/'mswea'),MSWEA_COST_TRACKING='ignore_errors',LITELLM_LOCAL_MODEL_COST_MAP='True',PYTHONHASHSEED='0')
                    command=[str(python),'-m','sim.tool_shell_agent','--fork',name,'--base-url',server.base_url,'--model',MODEL,'--seed',str(seed),'--budget',str(frozen['budget']),'--task-file',str(task),'--out',str(episode_dir/'agent.json')]
                    with (episode_dir/'agent.log').open('wb') as log:
                        process=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=log,timeout=1800)
                    if process.returncode or not (episode_dir/'agent.json').exists():raise RuntimeError('Agent process failed. Inspect retained agent.log.')
                    agent=trial.read(episode_dir/'agent.json');ep['shell_trace']=agent['steps'];ep['status']=agent['exit_status'];ep['model_calls']=agent['model_calls'];ep['usage']=agent['usage']
                    if agent.get('error'):ep['error']=agent['error']
                except Exception as e:
                    ep['status']='operational_error';ep['error']=type(e).__name__+': '+str(e)[:400]
                finally:
                    try:
                        failed=False
                        for result in records(name):
                            proof=trial.judge(frozen['image'],checker,result)
                            ep['invoked']=True;ep['valid_invocation'] |= result['returncode']==0
                            ep['completed']=proof['passed'];ep['ever_completed'] |= proof['passed']
                            if failed:ep['recovery_attempted']=True
                            if failed and proof['passed']:ep['recovered']=True
                            if result['returncode'] or not proof['passed']:failed=True
                            ep['events'].append({'action':'invoke','observation':result,'check':proof,'source':'root-owned gateway record; agent uid cannot edit'})
                    except Exception as e:
                        ep['evidence_error']=type(e).__name__+': '+str(e)[:400]
                    if not ep['shell_trace'] and (episode_dir/'agent.trace.jsonl').exists():
                        ep['shell_trace']=[json.loads(line) for line in (episode_dir/'agent.trace.jsonl').read_text().splitlines()]
                    _docker('rm','-f',name,check=False);trial.dump(out/'state.json',state)
        state['status']='complete'
    except Exception as e:state['status']='failed';state['error']=type(e).__name__+': '+str(e)[:400]
    finally:
        server.stop();state['elapsed_seconds']=time.monotonic()-start;trial.dump(out/'state.json',state)
    return state
