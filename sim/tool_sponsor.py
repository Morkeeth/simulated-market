"""Explicit hosted model route for frozen private-workspace shell tool trials."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlparse
from sim import ROOT, tool_trial as trial, tool_shell, hosted_cost
from sim.adapters import tokenfactory
from sim.adapters.coding_agent import require_harness
from sim.tokenfactory_local import require_supported_image, prerequisites
from sim.agent_protocol import SYSTEM, OBSERVATION, SUBMIT
from sim.tool_shell_agent import INSTANCE, MAX_TOKENS
from sim.standins.docker_sandbox import _docker

POLICY = 'tokenfactory-shell-agent'
CODE = ('sim/tool_sponsor.py', 'sim/tool_shell.py', 'sim/tool_shell_agent.py', 'sim/tool_gateway.py',
        'sim/tool_trial.py', 'sim/agent_protocol.py', 'sim/image_review.py',
        'sim/adapters/openai_compat.py', 'sim/adapters/tokenfactory.py', 'sim/hosted_cost.py')


def code_hashes():
    return {name: trial.sha256_bytes((ROOT/name).read_bytes()) for name in CODE}


def controls(path, expected):
    from sim.tool_preflight import require_passed
    if path.parent.name != 'tools': raise ValueError('Select a frozen trial from the private tool workspace.')
    return require_passed(SimpleNamespace(root=path.parent.parent), path.name, expected, POLICY)


def eligible(path, expected):
    if any((path/name).exists() for name in ('import.json', 'forecast-reference.json', 'started.json')):
        raise ValueError('Select an unstarted builder trial; imported outcomes and forecast registrations are read-only.')
    frozen = trial.verify(path, expected, execution=True)
    if trial.read(path/'state.json')['status'] != 'prepared': raise ValueError('Prepare a fresh tool trial before hosted execution.')
    return frozen


def image_gate(frozen, review):
    contract = {'image_id': frozen['image']}
    if review is not None: contract['image_review'] = review
    result = require_supported_image(contract)
    if review is not None:
        for name, row in review['proposal']['paths'].items():
            if row.get('after') is not None and any(name == p or name.startswith(p+'/') for p in ('/work','/agent','/control','/run/tool.sock','/usr/local/bin/tool')):
                raise ValueError('Reviewed image overlaps controller/task paths. Use a dependency-only base image.')
    # Preserve the credential ENV gate for this distinct tool runtime too.
    import re
    config = json.loads(_docker('image','inspect',frozen['image'],'--format','{{json .Config.Env}}').stdout)
    if any(value and re.search(r'TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|CREDENTIAL', name, re.I)
           for entry in config or [] for name, _, value in [entry.partition('=')]):
        raise ValueError('Image contains credential-like environment values. Use a clean dependency image.')
    return result


def prepare(path, expected, image_review=None):
    path = Path(path).resolve(); frozen = eligible(path, expected)
    model = os.environ.get(tokenfactory.MODEL_ENV, '').strip()
    if not model: raise ValueError('Set TOKEN_FACTORY_MODEL before preparing a hosted trial preview.')
    if not tokenfactory.model_requirement(model)['nvidia_nemotron_candidate']:
        raise ValueError('Choose the exact NVIDIA Nemotron account model before preparing this route.')
    cost_plan = (hosted_cost.projected(2*len(frozen['seeds'])*frozen['budget'], model)
                 if model == hosted_cost.MODEL else {'status':'No USD reservation for this model; live execution is blocked.'})
    identity = image_gate(frozen, image_review)
    proof = controls(path, expected)
    proposal = {'schema':'tool-sponsor-preview/1', 'contract':expected, 'policy':POLICY,
                'model':model, 'endpoint':tokenfactory.BASE_URL, 'image':frozen['image'],
                'image_review':image_review, 'image_identity':identity, 'code':code_hashes(),
                'evaluator_preflight':{'plan':proof['plan_sha256'],'result':proof['state']['sha256']},
                'denominator':{'arms':['base','head'],'seeds':frozen['seeds'],'episodes':2*len(frozen['seeds'])},
                'budget':{'max_model_calls':2*len(frozen['seeds'])*frozen['budget'],
                          'calls_per_episode':frozen['budget'],'max_output_tokens_per_call':MAX_TOKENS,
                          'max_prompt_utf8_bytes_per_call':60000,
                          'provider_charge_usd':None,'cost_status':'Provider invoice unknown; controller reservation is enforced before execution.',
                          'controller_cost_plan':cost_plan},
                'exposure':'Hosted model receives the task, supplied docs when read, and shell command output. '
                  'The agent can read selected source, fixtures and the reviewed image filesystem/environment. '
                  'Setup effects can reach the model. The separate checker is not inserted into prompts. '
                  'The provider key remains on the host and is never placed in the container.',
                'readiness_status':'preview_only', 'hosted_inference_attempted':False}
    proposal['sha256'] = trial.digest(proposal)
    trial.dump(path/'sponsor-preview.json', proposal)
    return {'preview':proposal, 'preflight':preflight(path, expected, proposal['sha256'])}


def validate(path, expected, preview_digest):
    path = Path(path).resolve(); frozen = eligible(path, expected)
    preview = trial.read(path/'sponsor-preview.json')
    value = {k:v for k,v in preview.items() if k != 'sha256'}
    if preview.get('sha256') != preview_digest or trial.digest(value) != preview_digest:
        raise ValueError('Hosted preview changed. Review and consent to its exact digest.')
    if preview['contract'] != expected or preview['code'] != code_hashes():
        raise ValueError('Trial or hosted runtime changed. Prepare a fresh hosted preview.')
    if preview['model'] != os.environ.get(tokenfactory.MODEL_ENV,'').strip() or preview['endpoint'] != tokenfactory.BASE_URL:
        raise ValueError('Provider model or endpoint changed. Prepare a fresh hosted preview.')
    proof = controls(path, expected)
    if preview['evaluator_preflight'] != {'plan':proof['plan_sha256'],'result':proof['state']['sha256']}:
        raise ValueError('Evaluator preflight changed. Prepare a fresh hosted preview.')
    image_gate(frozen, preview['image_review'])
    return frozen, preview


def preflight(path, expected, preview_digest):
    issues = []
    try:
        validate(path, expected, preview_digest)
        issues.extend(prerequisites(agents=1)['missing'])
        preview = trial.read(Path(path)/'sponsor-preview.json')
        if urlparse(preview['endpoint']).hostname not in ('127.0.0.1','localhost','::1') and preview['model'] != hosted_cost.MODEL:
            issues.append('USD stop is not priced for this model. Select the registered Nemotron Nano model.')
    except (ValueError, OSError, RuntimeError) as error: issues.append(str(error))
    return {'status':'blocked' if issues else 'ready_to_call', 'issues':issues,
            'provider_access':'unverified; no metadata or inference request made',
            'hosted_inference_attempted':False, 'execution_requires':'workspace provider permission plus exact preview consent'}


def act(client, name, task, seed, budget, record):
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.exceptions import Submitted
    from minisweagent.models.utils.actions_text import parse_regex_actions, format_observation_messages
    steps = []; requests = []
    class Model:
        def get_template_vars(self): return {}
        def serialize(self): return {}
        def format_message(self, **kwargs): return kwargs
        def query(self, messages):
            if len(requests) >= budget: raise RuntimeError('Frozen model-call ceiling reached.')
            sent = [{'role':m['role'],'content':m['content']} for m in messages]
            if len(json.dumps(sent).encode()) > 60000: raise RuntimeError('Frozen prompt-byte ceiling reached.')
            row = {'attempt':len(requests)+1}; requests.append(row)
            try:
                reply = client.chat(sent, seed=seed, temperature=0., max_tokens=MAX_TOKENS)
                row['usage'] = reply.usage
            except Exception as error:
                row['error_type'] = type(error).__name__; raise
            actions = parse_regex_actions(reply.text, action_regex=r'```mswea_bash_command\s*\n(.*?)\n```',
                                           format_error_template='Provide exactly one bash action; found {{actions|length}}.')
            return {'role':'assistant','content':reply.text,'extra':{'actions':actions}}
        def format_observation_messages(self, message, outputs, template_vars=None):
            return format_observation_messages(outputs, observation_template=OBSERVATION, template_vars=template_vars)
    class Environment:
        def get_template_vars(self): return {}
        def serialize(self): return {}
        def execute(self, action):
            command = action['command']
            import subprocess
            try:
                result = _docker('exec','--user','1000:1000','-w','/agent',name,'bash','-c',command,check=False,timeout=45)
                code, output = result.returncode, (result.stdout+result.stderr).decode(errors='replace')[:20000]
            except subprocess.TimeoutExpired: code, output = 124, 'Shell command timed out.'
            row = {'command':command,'returncode':code,'output':output}; steps.append(row)
            record({'exit_status':'running','steps':steps,'model_calls':len(requests)})
            if output.strip().splitlines() and output.strip().splitlines()[0] == SUBMIT and code == 0:
                raise Submitted({'role':'exit','content':'','extra':{'exit_status':'Submitted','submission':''}})
            return {'returncode':code,'output':output,'exception_info':''}
    agent = DefaultAgent(Model(),Environment(),system_template=SYSTEM,instance_template=INSTANCE,
                         step_limit=budget,cost_limit=0.,max_consecutive_format_errors=3)
    result = {'exit_status':'operational_error','steps':steps,'requests':requests}
    try: result['exit_status'] = agent.run(task).get('exit_status','unknown')
    except Exception as error: result['error_type'] = type(error).__name__
    result['model_calls'] = len(requests); result['usage'] = {}
    for row in requests:
        for key,value in row.get('usage',{}).items():
            if isinstance(value,(int,float)): result['usage'][key] = result['usage'].get(key,0)+value
    record(result)
    return result


def run(path, expected, preview_digest, consent, *, allow_provider=False):
    path = Path(path).resolve()
    if not allow_provider: raise ValueError('Hosted execution is disabled. Enable workspace provider permission explicitly.')
    if consent != preview_digest: raise ValueError('Confirm source transfer and paid inference for this exact hosted preview.')
    frozen, preview = validate(path, expected, preview_digest)
    readiness = preflight(path, expected, preview_digest)
    if readiness['issues']: raise ValueError('; '.join(readiness['issues']))
    require_harness()
    local_double = urlparse(preview['endpoint']).hostname in ('127.0.0.1','localhost','::1')
    reservation = None if local_double else hosted_cost.reserve(str(path), preview['budget']['max_model_calls'], preview['model'])
    # No client or provider metadata request is constructed until every local gate passes.
    fd = os.open(path/'started.json', os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    with os.fdopen(fd,'w') as stream: json.dump({'contract':expected,'policy':POLICY,'preview':preview_digest,'registration':preview},stream)
    state = {'status':'running','contract':expected,'policy':POLICY,'labels':['SIMULATED','LOCAL'],
             'model':{'id':preview['model'],'runtime':'LOCAL_HTTP_TEST_DOUBLE' if local_double else 'token-factory'},
             'provider_runtime_verified':False,'denominator':preview['denominator'],'budget':preview['budget'],
             'cost':{'provider_charge_usd':None,'source':'Unknown, not zero; provider usage receipts are retained.',
                     'controller_reservation':reservation},
             'episodes':[{'arm':arm,'seed':seed,'status':'not_started','completed':False,'model_calls':0,'usage':{},'events':[], 'discovered':None, 'setup_ok':False,
                          'invoked':False,'valid_invocation':False,'ever_completed':False,
                          'recovered':False,'recovery_attempted':False}
                         for arm in ('base','head') for seed in frozen['seeds']]}
    trial.dump(path/'state.json',state)
    def receipt(row):
        with (path/'services.jsonl').open('a') as stream: stream.write(json.dumps(row,sort_keys=True)+'\n')
    stage='provider_metadata'
    try:
        from sim.adapters.readiness import check_access
        access = check_access(include_sandbox=False)['token_factory']
        if not (access.get('metadata_access') is True and access.get('selected_model_available') is True):
            raise ValueError('Provider metadata did not confirm access to the frozen model.')
        client = tokenfactory.client(); client.record = receipt
        checker = (path/'check.py').read_bytes()
        with tempfile.TemporaryDirectory(prefix='sim-tool-sponsor-') as directory:
            names = {'MSWEA_GLOBAL_CONFIG_DIR':directory,'MSWEA_SILENT_STARTUP':'1'}
            before = {k:os.environ.get(k) for k in names}; os.environ.update(names)
            try:
                for ep in state['episodes']:
                    episode_started = time.monotonic()
                    ep['started_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
                    name = 'simtool-hosted-'+secrets.token_hex(8); ep['status'] = 'running'
                    try:
                        stage='container_setup'
                        rows = tool_shell.setup(frozen,path,ep['arm'],name)
                        ep['setup_ok'] = all(row['returncode']==0 for row in rows)
                        ep['events'].append({'action':'controller_setup','commands':rows})
                        if not ep['setup_ok']: ep['status']='setup_failed'; continue
                        snapshot=trial.execute(name,['python3','-c',"import pathlib,hashlib,json;print(json.dumps({str(p.relative_to('/work')):hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('/work').rglob('*') if p.is_file()},sort_keys=True))"])
                        if snapshot['returncode']: raise RuntimeError('Could not freeze task filesystem identity.')
                        snapshot_path=path/(ep['arm']+'-'+str(ep['seed'])+'-task-files.json')
                        trial.dump(snapshot_path,json.loads(snapshot['output']))
                        ep['task_files_sha256']=trial.sha256_bytes(snapshot_path.read_bytes())
                        stage='model_request'
                        result = act(client,name,frozen['task'],ep['seed'],frozen['budget'],
                                     lambda value: trial.dump(path/(ep['arm']+'-'+str(ep['seed'])+'-agent.json'),value))
                        ep.update(status=result['exit_status'],shell_trace=result['steps'],model_calls=result['model_calls'],usage=result['usage'])
                        if result.get('error_type'): ep['error_type']=result['error_type']
                        if result.get('error_type'):
                            state['failure_stage']='model_request'
                            raise RuntimeError('Hosted participant stopped on an operational error.')
                    finally:
                        try:
                            stage='independent_checker'
                            failed=False
                            for observation in tool_shell.records(name):
                                check = trial.judge(frozen['image'],checker,observation)
                                ep['invoked']=True; ep['valid_invocation'] |= observation['returncode']==0
                                ep['tool_check_passed'] = check['passed']
                                if 'artifact' not in frozen:
                                    ep['completed'] = check['passed']; ep['ever_completed'] |= check['passed']
                                if failed: ep['recovery_attempted']=True
                                if failed and check['passed']: ep['recovered']=True
                                if observation['returncode'] or not check['passed']: failed=True
                                ep['events'].append({'action':'invoke','observation':observation,'check':check,'source':'controller gateway'})
                            if 'artifact' in frozen:
                                artifact=frozen['artifact']
                                observed=_docker('exec',name,'cat',artifact,check=False)
                                output=observed.stdout[:100001]
                                artifact_record={'args':['--artifact',artifact],
                                                 'returncode':observed.returncode if len(output)<=100000 else 1,
                                                 'output':output[:100000].decode(errors='replace')}
                                artifact_check=trial.judge(frozen['image'],checker,artifact_record)
                                ep['artifact_check']=artifact_check
                                ep['completed']=artifact_check['passed']
                                ep['ever_completed'] |= artifact_check['passed']
                                ep['events'].append({'action':'final_artifact','observation':artifact_record,
                                                     'check':artifact_check,'source':'controller read from agent output path'})
                        finally:
                            _docker('rm','-f',name,check=False)
                            ep['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
                            ep['wall_seconds'] = round(time.monotonic()-episode_started, 3)
                            prompt = ep['usage'].get('prompt_tokens')
                            output = ep['usage'].get('completion_tokens')
                            ep['controller_estimated_usd'] = (
                                float((hosted_cost.money(prompt)*hosted_cost.INPUT_RATE +
                                       hosted_cost.money(output)*hosted_cost.OUTPUT_RATE)/1_000_000)
                                if type(prompt) is int and type(output) is int else None)
                            ep['cost_source'] = hosted_cost.PRICE_SOURCE
                            ep['end_to_end_cost_usd'] = None  # Local hardware and setup are unmeasured.
                            trial.dump(path/'state.json',state)
            finally:
                for key,value in before.items():
                    if value is None: os.environ.pop(key,None)
                    else: os.environ[key]=value
        state['status']='complete'
    except Exception as error:
        state.update(status='failed',error_type=type(error).__name__)
        state.setdefault('failure_stage',stage)
        state['error']='Hosted trial stopped at '+state['failure_stage']+'. Inspect the retained sanitized request and controller receipts.'
        for ep in state['episodes']:
            if ep['status']=='running': ep['status']='operational_error'
            elif ep['status']=='not_started': ep['status']='not_started_after_failure'
    rows = [json.loads(line) for line in (path/'services.jsonl').read_text().splitlines()] if (path/'services.jsonl').exists() else []
    state['model_requests_attempted'] = sum(r.get('service')=='chat_request' and r.get('event')=='attempted' for r in rows)
    state['model_requests_failed'] = sum(r.get('service')=='chat_request' and r.get('event')=='failed' for r in rows)
    state['hosted_inference_attempted'] = not local_double and state['model_requests_attempted'] > 0
    state['usage_totals'] = {}
    for row in rows:
        if row.get('service') == 'chat':
            for key,value in row.get('usage',{}).items():
                if isinstance(value,(int,float)): state['usage_totals'][key] = state['usage_totals'].get(key,0)+value
    state['provider_runtime_verified'] = not local_double and any(r.get('service')=='chat' and r.get('identity_status')=='matched' for r in rows)
    if reservation:
        accounted = hosted_cost.settle(str(path), state['usage_totals'],
                                       state['status']=='complete' and state['model_requests_attempted']==len([r for r in rows if r.get('service')=='chat']))
        state['cost']['controller_account'] = accounted
    state['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat(); trial.dump(path/'state.json',state)
    return state


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for flag in ('trial','expected','preview','consent'): parser.add_argument('--'+flag,required=True)
    parser.add_argument('--allow-provider',action='store_true'); args=parser.parse_args()
    print(json.dumps(run(args.trial,args.expected,args.preview,args.consent,allow_provider=args.allow_provider)))
