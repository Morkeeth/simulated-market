"""Source-bound local GitHub MCP session trials. Deliberately separate from CLI agent contracts."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from sim import ROOT, tool_trial as trial
from sim.scenario import git, revision, safe_member
from sim.standins.docker_sandbox import _docker

BASE='3778a41476e31a072430cfee7c5d31c5f72def60'
HEAD='f0e971388433ea6f197e325f05ffffdb67f70577'
CODE=('sim/tool_mcp.py','sim/tool_mcp_worker.py')


def hashes():return {p:trial.sha256_bytes((ROOT/p).read_bytes()) for p in CODE}


def module_sum(directory,prefix):
    # Go's vendored x/mod/sumdb/dirhash.Hash1: sorted content hash + two spaces + prefixed name.
    summary=hashlib.sha256()
    for path in sorted(directory.rglob('*'),key=lambda p:p.relative_to(directory).as_posix()):
        if path.is_dir():continue
        name=prefix+'/'+path.relative_to(directory).as_posix()
        if path.is_symlink() or '\n' in name:raise ValueError('Unsafe module cache member.')
        summary.update((trial.sha256_bytes(path.read_bytes())+'  '+name+'\n').encode())
    return 'h1:'+base64.b64encode(summary.digest()).decode()


def verify_linked_modules(metadata,cache,go_sum):
    declared=set(go_sum.splitlines());rows=[]
    for line in metadata.splitlines():
        parts=line.split()
        if parts and parts[0]=='=>':raise ValueError('Replaced build dependencies are unsupported.')
        if not parts or parts[0]!='dep':continue
        _,name,version,checksum=parts
        if name+' '+version+' '+checksum not in declared:raise ValueError('Linked dependency not bound to frozen go.sum.')
        escaped=''.join('!'+c.lower() if c.isupper() else c for c in name+'@'+version)
        directory=cache/escaped
        if not directory.is_dir() or module_sum(directory,name+'@'+version)!=checksum:raise ValueError('Linked module cache bytes mismatch: '+name)
        rows.append({'module':name,'version':version,'verified_h1':checksum})
    return rows


def prepare(spec,out):
    required={'repo','base','head','image','go','module_cache','build_cache','fixture','calls','conditions','timeout_seconds'}
    if set(spec)!=required or (spec['base'],spec['head'])!=(BASE,HEAD):raise ValueError('Use the pinned GitHub Markdown-response profile and explicit fields.')
    if type(spec['timeout_seconds']) is not int or not 1<=spec['timeout_seconds']<=60:raise ValueError('Timeout must be 1 to 60 seconds.')
    calls=spec['calls']
    if not isinstance(calls,list) or not 1<=len(calls)<=50:raise ValueError('Declare 1 to 50 sequential calls.')
    for call in calls:
        if not isinstance(call,dict) or set(call)!={'name','arguments'} or not isinstance(call['name'],str) or not isinstance(call['arguments'],dict):raise ValueError('Each call needs tool name and arguments.')
    if len(json.dumps(calls))>100000:raise ValueError('Calls exceed bounded plan size.')
    conditions=spec['conditions']
    if not isinstance(conditions,dict) or not 1<=len(conditions)<=8:raise ValueError('Declare per-condition flags.')
    for label,c in conditions.items():
        if not label.replace('-','').isalnum() or set(c)!={'arm','features'} or c['arm'] not in ('base','head') or c['features'] not in ([],['markdown_output']):raise ValueError('Invalid condition.')
        if c['arm']=='base' and c['features']:raise ValueError('The baseline has no Markdown feature flag.')
    repo=Path(spec['repo']).expanduser().resolve();image=_docker('image','inspect',spec['image'],'--format','{{.Id}}').stdout.decode().strip()
    if not image.startswith('sha256:'):raise ValueError('Use a cached immutable image.')
    fixture=spec['fixture']
    if not isinstance(fixture,dict) or set(fixture)!={'repo','ref','path'}:raise ValueError('Freeze fixture repo, ref and path independently.')
    f_repo=Path(fixture['repo']).expanduser().resolve();f_ref=revision(f_repo,fixture['ref']);raw_fixture=trial.blob(f_repo,f_ref,fixture['path'])
    go=Path(spec['go']).resolve();version=subprocess.check_output([str(go),'version']).decode().strip()
    out=Path(out).expanduser().resolve()
    if out.is_relative_to(ROOT):raise ValueError('Keep private receipts outside the checkout.')
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    trial.dump(out/'preparation.json',{'status':'building','spec':spec,'model_calls':0})
    started=time.monotonic()
    frozen={'schema':'local-mcp-session/1','profile':'github-markdown-response','labels':['LOCAL','SYNTHETIC','SCRIPTED_PROTOCOL_CONTROLS'],
        'image':image,'fixture':{'commit':f_ref,'path':fixture['path'],'sha256':trial.sha256_bytes(raw_fixture)},'calls':calls,'conditions':conditions,
        'timeout_seconds':spec['timeout_seconds'],'code':hashes(),'arms':{},'build':{'go_version':version,'go_sha256':trial.sha256_bytes(go.read_bytes()),'network':'GOPROXY=off; GOSUMDB=off; GOTOOLCHAIN=local','flags':['-mod=readonly','-trimpath','-buildvcs=false'],'target':'linux/arm64; CGO_ENABLED=0'},'model_calls':0}
    try:
        (out/'fixture.py').write_bytes(raw_fixture);(out/'worker.py').write_bytes((ROOT/'sim/tool_mcp_worker.py').read_bytes())
        for arm in ('base','head'):
            commit=revision(repo,spec[arm]);raw=git(repo,'archive','--format=tar',commit);(out/(arm+'.tar')).write_bytes(raw)
            source=out/(arm+'-source');source.mkdir()
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                for member in archive:
                    if not safe_member(member.name) or not (member.isfile() or member.isdir()):raise ValueError('Unsafe source archive member.')
                    dest=source/member.name
                    if member.isdir():dest.mkdir(parents=True,exist_ok=True)
                    else:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(archive.extractfile(member).read())
            env={'PATH':str(go.parent)+':/usr/bin:/bin','HOME':str(out),'GOENV':'off','GOTOOLCHAIN':'local','GOWORK':'off','GOPROXY':'off','GOSUMDB':'off','CGO_ENABLED':'0','GOOS':'linux','GOARCH':'arm64','GOMODCACHE':str(Path(spec['module_cache']).expanduser().resolve()),'GOCACHE':str(Path(spec['build_cache']).expanduser().resolve())}
            argv=[str(go),'build',*frozen['build']['flags'],'-o',str(out/(arm+'.bin')),'./cmd/github-mcp-server']
            result=subprocess.run(argv,cwd=source,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
            (out/(arm+'-build.log')).write_bytes(result.stdout)
            if result.returncode:raise ValueError('Offline '+arm+' build failed; retained build log.')
            binary=out/(arm+'.bin');binary.chmod(0o555)
            metadata=subprocess.check_output([str(go),'version','-m',str(binary)]).decode()
            frozen['arms'][arm]={'commit':commit,'source_sha256':trial.sha256_bytes(raw),'binary_sha256':trial.sha256_bytes(binary.read_bytes()),'build_argv':argv,'go_mod_sha256':trial.sha256_bytes((source/'go.mod').read_bytes()),'go_sum_sha256':trial.sha256_bytes((source/'go.sum').read_bytes()),'binary_metadata':metadata,'linked_module_verification':verify_linked_modules(metadata,Path(env['GOMODCACHE']),(source/'go.sum').read_text())}
            shutil.rmtree(source)
        frozen['integrity']={name:trial.sha256_bytes((out/name).read_bytes()) for name in ['fixture.py','worker.py','base.tar','head.tar','base.bin','head.bin']}
        frozen['sha256']=trial.digest(frozen);trial.dump(out/'contract.json',frozen)
        trial.dump(out/'preparation.json',{'status':'prepared','contract':frozen['sha256'],'elapsed_seconds':time.monotonic()-started,'model_calls':0})
        return frozen
    except Exception as error:
        trial.dump(out/'preparation.json',{'status':'failed','error':str(error),'elapsed_seconds':time.monotonic()-started,'model_calls':0});raise


def verify(path,expected):
    c=trial.read(path/'contract.json');copy=dict(c);signature=copy.pop('sha256')
    if signature!=expected or trial.digest(copy)!=expected:raise ValueError('MCP contract changed.')
    if c['code']!=hashes():raise ValueError('MCP controller changed. Prepare a new session trial.')
    for name,sha in c['integrity'].items():
        if not safe_member(name) or trial.sha256_bytes((path/name).read_bytes())!=sha:raise ValueError('Frozen MCP bytes changed: '+name)
    return c


def container_args(path,folder,arm,image,name,interactive=False):
    receipt=folder/'receipt'
    return ['run',*(['-i'] if interactive else []),'--pull','never','--name',name,'--network','none','--read-only','--memory','512m','--cpus','1','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:size=32m',
              '-v',str(path/'fixture.py')+':/frozen/fixture.py:ro','-v',str(path/'worker.py')+':/frozen/worker.py:ro','-v',str(path/(arm+'.bin'))+':/frozen/server:ro','-v',str(folder/'plan.json')+':/frozen/plan.json:ro','-v',str(receipt)+':/receipt',image,'python3','-I','/frozen/worker.py']


def run(path,expected):
    path=Path(path).resolve();c=verify(path,expected)
    fd=os.open(path/'started.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'contract':expected,'at':time.time()},f)
    result={'contract':expected,'status':'running','conditions':{},'model_calls':0,'provider_calls':0,'limits':'Scripted protocol controls, not agent task success or owner acceptance.'}
    trial.dump(path/'result.json',result)
    for label,condition in c['conditions'].items():
        folder=path/label;folder.mkdir(mode=0o700);receipt=folder/'receipt';receipt.mkdir(mode=0o700)
        argv=['stdio','--gh-host','http://127.0.0.1','--toolsets','pull_requests','--read-only']
        if condition['features']:argv+=['--features',','.join(condition['features'])]
        trial.dump(folder/'plan.json',{'argv':argv,'calls':c['calls'],'timeout_seconds':c['timeout_seconds']})
        name='simmcp-'+os.urandom(8).hex()
        args=container_args(path,folder,condition['arm'],c['image'],name)
        row={'status':'running','arm':condition['arm'],'features':condition['features'],'docker_argv':args};result['conditions'][label]=row;trial.dump(path/'result.json',result)
        try:
            p=_docker(*args,check=False,timeout=(len(c['calls'])+2)*c['timeout_seconds']+30)
            (folder/'docker.stdout').write_bytes(p.stdout);(folder/'docker.stderr').write_bytes(p.stderr);row['returncode']=p.returncode
            state=trial.read(receipt/'session.json') if (receipt/'session.json').exists() else {}
            row.update(status='complete' if p.returncode==0 and state.get('status')=='complete' and len(state.get('calls',[]))==len(c['calls']) else 'failed',session=state)
        except Exception as error:row.update(status='failed',error=str(error))
        finally:
            _docker('rm','-f',name,check=False)
            if 'session' not in row and (receipt/'session.json').exists():
                try:row['session']=trial.read(receipt/'session.json')
                except (ValueError,OSError):pass
            row['receipt_hashes']={str(f.relative_to(folder)):trial.sha256_bytes(f.read_bytes()) for f in folder.rglob('*') if f.is_file()}
            trial.dump(path/'result.json',result)
    result['status']='complete' if all(r['status']=='complete' for r in result['conditions'].values()) else 'failed'
    trial.dump(path/'result.json',result);return result


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('--path',required=True);p.add_argument('--spec');p.add_argument('--expected');a=p.parse_args()
    result=prepare(trial.read(Path(a.spec)),a.path) if a.action=='prepare' else run(a.path,a.expected)
    print(json.dumps(result))

if __name__=='__main__':main()
