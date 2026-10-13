"""Private, versioned CLI trials. Agent chooses actions; controller owns evidence/checks."""
from __future__ import annotations
import argparse
import datetime as dt
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import time

from sim import ROOT
from sim.doc import sha256_bytes
from sim.scenario import git, revision, safe_member
from sim.standins.docker_sandbox import _docker

PROMPT = '''You are trying an agent-facing command-line tool for a downstream user task.
Return exactly one JSON object, no markdown. Available actions:
{"action":"discover"} reads its supplied documentation.
{"action":"setup"} runs the declared installation/configuration once.
{"action":"invoke","args":["argument", "another argument"]} calls the tool with these argv strings.
{"action":"stop"} ends this attempt. You cannot use a shell or alter the checker.
You choose whether and how to use the tool. On errors you can try different arguments.
The controller checks actual output. Do not claim success from a printed success message.
'''


def dump(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temp.chmod(0o600)
    os.replace(temp, path)


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def strings(value, empty=False):
    return isinstance(value, list) and (empty or bool(value)) and all(isinstance(x, str) and x and '\0' not in x for x in value)


def blob(repo, commit, name, *, allow_absent=False):
    if not isinstance(name, str) or not safe_member(name):
        raise ValueError('Use committed regular files with safe relative paths.')
    row = git(repo, 'ls-tree', commit, '--', name).split(b' ', 1)[0]
    if not row and allow_absent:
        return None
    if row not in (b'100644', b'100755'):
        raise ValueError('Not a committed regular file: ' + name)
    return git(repo, 'show', commit + ':' + name)


def archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tf:
        for name, raw in sorted(files.items()):
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o755
            tf.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def prepare(contract, out):
    required = {'version','name','repo','base','head','files','discovery','image','setup','command','task','check','budget','seeds','initial_choice'}
    if not isinstance(contract, dict) or not required <= set(contract) or set(contract)-required-{'fixtures','artifact'} or contract['version'] != 1:
        raise ValueError('Use the version 1 tool-trial contract; see docs/agent-tool-trials.md.')
    for key in ('name','repo','base','head','discovery','image','task'):
        if not isinstance(contract[key], str) or not contract[key].strip(): raise ValueError('Missing ' + key)
    if not strings(contract['files']) or len(set(contract['files'])) != len(contract['files']): raise ValueError('Select unique committed files.')
    if not strings(contract['command']) or not strings(contract['setup'], empty=True): raise ValueError('Command is argv; setup is an explicit command list.')
    if 'artifact' in contract and (not isinstance(contract['artifact'],str) or not contract['artifact'].startswith('/agent/') or not safe_member(contract['artifact'].removeprefix('/agent/'))):
        raise ValueError('A final task artifact must be a safe file under /agent/.')
    if type(contract['budget']) is not int or not 1 <= contract['budget'] <= 30: raise ValueError('Action budget must be 1 to 30.')
    seeds = contract['seeds']
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 20 or any(type(s) is not int for s in seeds) or len(set(seeds)) != len(seeds): raise ValueError('Choose 1 to 20 distinct integer seeds.')
    if contract['initial_choice'] not in ('base','head','defer'): raise ValueError('Freeze an initial release choice.')
    check = contract['check']
    if not isinstance(check, dict) or set(check) != {'repo','ref','path'}: raise ValueError('check requires its own repo, ref and path.')
    repo = Path(contract['repo']).expanduser().resolve()
    checker_repo = Path(check['repo']).expanduser().resolve()
    checker_ref = revision(checker_repo, check['ref'])
    checker = blob(checker_repo, checker_ref, check['path'])
    fixtures = {}
    fixture_identity = None
    if 'fixtures' in contract:
        f = contract['fixtures']
        if not isinstance(f, dict) or set(f) != {'repo','ref','files'} or not strings(f['files']): raise ValueError('fixtures needs repo, ref and explicit files.')
        fixture_repo = Path(f['repo']).expanduser().resolve(); fixture_ref = revision(fixture_repo, f['ref'])
        fixtures = {name:blob(fixture_repo, fixture_ref, name) for name in f['files']}
        if set(fixtures) & set(contract['files']): raise ValueError('Fixture paths must not replace target source.')
        fixture_identity = {'commit':fixture_ref, 'files':{k:sha256_bytes(v) for k,v in fixtures.items()}}
    if contract['discovery'] not in set(contract['files']) | set(fixtures): raise ValueError('Include discovery document in target or fixture files.')
    source_arms = {}
    for arm in ('base', 'head'):
        commit = revision(repo, contract[arm])
        selected = {name: blob(repo, commit, name, allow_absent=True) for name in contract['files']}
        files = {name: raw for name, raw in selected.items() if raw is not None}
        files.update(fixtures)
        if contract['discovery'] not in files:
            raise ValueError('Discovery document must exist in both versions or in fixtures.')
        source_arms[arm] = (commit, files)
    for name in contract['files']:
        if all(name not in source_arms[arm][1] for arm in source_arms):
            raise ValueError('Selected file is absent from both versions: ' + name)
    image = _docker('image','inspect',contract['image'],'--format','{{.Id}}').stdout.decode().strip()
    if not image.startswith('sha256:'): raise ValueError('Image must resolve to a cached immutable Docker image.')
    out = Path(out).resolve()
    if out.is_relative_to(ROOT.resolve()): raise ValueError('Trial data must stay outside the tool checkout.')
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    frozen = {k:contract[k] for k in ('version','name','setup','command','task','budget','seeds','initial_choice')}
    if 'artifact' in contract: frozen['artifact']=contract['artifact']
    frozen['fixtures'] = fixture_identity
    frozen['discovery'] = {'path':contract['discovery'], 'source':'fixture' if contract['discovery'] in fixtures else 'target'}
    frozen.update(kind='agent-tool-trial', image=image, labels=['SIMULATED','LOCAL'], arms={},
                  check={'commit':checker_ref,'path':check['path']},
                  created_at=dt.datetime.now(dt.timezone.utc).isoformat(), protocol_sha256=sha256_bytes(PROMPT.encode()), runner_sha256=sha256_bytes(Path(__file__).read_bytes()))
    (out/'check.py').write_bytes(checker)
    for arm in ('base','head'):
        commit, files = source_arms[arm]
        (out/(arm+'.tar')).write_bytes(archive(files))
        (out/(arm+'.md')).write_bytes(files[contract['discovery']])
        frozen['arms'][arm]={'commit':commit,'files':{k:sha256_bytes(v) for k,v in files.items()}}
    frozen['integrity']={p.name:sha256_bytes(p.read_bytes()) for p in out.iterdir() if p.is_file()}
    frozen['sha256']=digest(frozen)
    dump(out/'contract.json',frozen)
    dump(out/'state.json',{'status':'prepared','contract':frozen['sha256'],'episodes':[]})
    return frozen


def verify(out, expected, execution=False):
    frozen=read(out/'contract.json'); signature=frozen.pop('sha256')
    if signature != expected or digest(frozen) != signature: raise ValueError('Frozen contract changed. Prepare a new trial.')
    frozen['sha256']=signature
    if execution and frozen['runner_sha256'] != sha256_bytes(Path(__file__).read_bytes()): raise ValueError('Trial runner changed. Prepare a new trial.')
    if execution and frozen['protocol_sha256'] != sha256_bytes(PROMPT.encode()): raise ValueError('Agent protocol changed. Prepare a new trial.')
    for name, value in frozen['integrity'].items():
        if not safe_member(name) or sha256_bytes((out/name).read_bytes()) != value: raise ValueError('Frozen bytes changed: '+name)
    return frozen


def container(image, name):
    _docker('run','--pull','never','-d','--network','none','--memory','512m','--cpus','1',
            '--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--name',name,image,'sleep','infinity')


def execute(name, argv, cwd='/work', timeout=30):
    try:
        p=_docker('exec','-w',cwd,name,*argv,check=False,timeout=timeout)
        return {'returncode':p.returncode,'output':(p.stdout+p.stderr).decode(errors='replace')[:20000]}
    except subprocess.TimeoutExpired:
        return {'returncode':124,'output':'Command timed out.'}


def judge(image, checker, result):
    name='simtool-check-'+secrets.token_hex(8)
    container(image,name)
    try:
        _docker('exec',name,'mkdir','-p','/check')
        raw=archive({'check.py':checker,'result.json':json.dumps(result).encode()})
        _docker('cp','-',name+':/check',input=raw)
        verdict=execute(name,['python3','-I','check.py'],cwd='/check')
        return {'passed':verdict['returncode']==0,'returncode':verdict['returncode'],
                'output':verdict['output'],'source':'controller check in separate networkless container'}
    finally:
        _docker('rm','-f',name,check=False)


def parse_action(raw):
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('action') not in ('discover','setup','invoke','stop'): raise ValueError('Unknown action.')
    expected={'action','args'} if value['action']=='invoke' else {'action'}
    if set(value)!=expected: raise ValueError('Unexpected action fields.')
    if value['action']=='invoke' and (not strings(value['args'],empty=True) or len(value['args'])>80 or sum(map(len,value['args']))>8000): raise ValueError('args must be a bounded list of strings.')
    return value


def run(out, expected, policy='local-model', rehearsal=None):
    out=Path(out).resolve(); frozen=verify(out,expected,execution=True)
    if policy not in ('local-model','scripted-rehearsal'): raise ValueError('Unknown policy.')
    if policy=='scripted-rehearsal' and not isinstance(rehearsal,list): raise ValueError('Rehearsal needs an explicit action script.')
    # Atomic claim survives crashes. No retry or reservation reset.
    fd=os.open(out/'started.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    from sim.standins.local_model import MODEL
    with os.fdopen(fd,'w') as stream: json.dump({'contract':expected,'policy':policy,'model':MODEL if policy=='local-model' else None,'temperature':0,'max_tokens':512,'at':dt.datetime.now(dt.timezone.utc).isoformat(),'rehearsal':rehearsal},stream)
    state={'status':'running','contract':expected,'policy':policy,'labels':['SIMULATED','LOCAL'], 'episodes':[], 'cost':{'provider_charge_usd':0,'source':'Local model only; hardware, electricity and setup costs unmeasured'},
           'limits':'No adoption, voluntary reuse, human behavior, causal uplift or forecast validation is measured.'}
    dump(out/'state.json',state)
    server=None; start=time.monotonic()
    try:
        checker=(out/'check.py').read_bytes()
        negative=judge(frozen['image'],checker,{'args':[],'returncode':1,'output':''})
        state['checker_negative_control']=negative
        if negative['passed']: raise ValueError('Controller check accepts an empty failed invocation. Fix the check and prepare a new trial.')
        if policy=='local-model':
            from sim.standins.local_model import LocalModel, MODEL
            server=LocalModel(); server.start(); client=server.client()
            state['model']={'id':MODEL,'runtime':'mlx_lm.server','temperature':0,'max_tokens':512}
        else:
            state['model']=None
        for arm in ('base','head'):
            for seed in frozen['seeds']:
                ep={'arm':arm,'seed':seed,'events':[],'status':'running','discovered':False,'setup_ok':False,
                    'invoked':False,'valid_invocation':False,'completed':False,'ever_completed':False,'recovered':False,'recovery_attempted':False,'model_calls':0,'usage':{}}
                state['episodes'].append(ep); dump(out/'state.json',state)
                name='simtool-'+secrets.token_hex(8); container(frozen['image'],name)
                try:
                    _docker('exec',name,'mkdir','-p','/work')
                    _docker('cp','-',name+':/work',input=(out/(arm+'.tar')).read_bytes())
                    messages=[{'role':'system','content':PROMPT},{'role':'user','content':frozen['task']}]
                    attempted_setup=False; failed=False
                    for index in range(frozen['budget']):
                        if policy=='local-model':
                            reply=client.chat(messages,seed=seed,max_tokens=512)
                            raw=reply.text; ep['model_calls']+=1
                            for key,value in reply.usage.items():
                                if isinstance(value,(int,float)): ep['usage'][key]=ep['usage'].get(key,0)+value
                        else:
                            raw=json.dumps(rehearsal[index] if index<len(rehearsal) else {'action':'stop'})
                        try: action=parse_action(raw)
                        except (ValueError,TypeError) as e:
                            action={'action':'invalid'}; observation={'error':str(e)}
                        else:
                            kind=action['action']
                            if kind=='stop':
                                ep['status']='stopped'; ep['events'].append({'action':'stop'}); break
                            if kind=='discover':
                                ep['discovered']=True; observation={'documentation':(out/(arm+'.md')).read_text()[:24000]}
                            elif kind=='setup':
                                if attempted_setup: observation={'error':'Setup has already been attempted.'}
                                else:
                                    attempted_setup=True
                                    rows=[]
                                    for command in frozen['setup']:
                                        result=execute(name,['bash','-c',command]); rows.append(result)
                                        if result['returncode']: break
                                    ep['setup_ok']=all(r['returncode']==0 for r in rows)
                                    observation={'setup_ok':ep['setup_ok'],'commands':rows}
                                    if not ep['setup_ok']: failed=True
                            else:
                                ep['invoked']=True
                                if failed: ep['recovery_attempted']=True
                                result=execute(name,frozen['command']+action['args'])
                                proof=judge(frozen['image'],checker,{'args':action['args'],**result})
                                valid=result['returncode']==0
                                ep['valid_invocation'] |= valid
                                ep['completed']=proof['passed']
                                ep['ever_completed'] |= proof['passed']
                                if proof['passed'] and failed: ep['recovered']=True
                                if not valid or not proof['passed']: failed=True
                                observation={**result,'task_check_passed':proof['passed']}
                                action={**action,'check':proof}
                        ep['events'].append({**action,'observation':observation,'model_reply':raw})
                        messages.extend([{'role':'assistant','content':raw},{'role':'user','content':json.dumps(observation)}])
                        dump(out/'state.json',state)
                    else: ep['status']='budget_exhausted'
                except Exception as e:
                    ep['status']='operational_error'; ep['error']=type(e).__name__+': '+str(e)[:400]
                finally:
                    _docker('rm','-f',name,check=False)
                    dump(out/'state.json',state)
        state['status']='complete'
    except Exception as e:
        state['status']='failed'; state['error']=type(e).__name__+': '+str(e)[:400]
    finally:
        if server: server.stop()
        state['elapsed_seconds']=time.monotonic()-start
        dump(out/'state.json',state)
    return state


def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare'); p.add_argument('--contract',required=True); p.add_argument('--output',required=True)
    p=sub.add_parser('run'); p.add_argument('--output',required=True); p.add_argument('--expected',required=True)
    p.add_argument('--policy',choices=['local-model','local-shell-agent','scripted-rehearsal'],default='local-model'); p.add_argument('--script')
    args=ap.parse_args()
    try:
        if args.action=='prepare': result=prepare(read(Path(args.contract)),Path(args.output))
        elif args.policy=='local-shell-agent':
            from sim.tool_shell import run as shell_run
            result=shell_run(Path(args.output),args.expected)
        else: result=run(Path(args.output),args.expected,args.policy,read(Path(args.script)) if args.script else None)
        print(json.dumps(result,indent=2)); return 2 if result.get('status')=='failed' else 0
    except (ValueError,OSError,RuntimeError) as e:
        print(str(e),file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
