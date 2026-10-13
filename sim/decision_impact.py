"""Offline paired release-choice evaluation. Local integrity, not causal attribution.

Register before choices; seal both choices before starting reserved later outcomes.
Synthetic fixtures exercise mechanics only. No outcome files are read at registration.
"""
import json
import math
from pathlib import Path
import secrets
import datetime
from sim.tool_forecast import digest

POLICIES = ('eval_only', 'forecast_informed')
COSTS = ('model_calls', 'tokens', 'setup_seconds', 'inference_seconds',
         'review_seconds', 'provider_usd', 'hardware_usd')

def read(p):
    return json.loads(Path(p).read_text())

def write(p, value):
    with Path(p).open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write('\n')

def sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('SHA256 required')

def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('finite nonnegative number required')

def costs(value, *, unknown):
    if set(value) != set(COSTS):
        raise ValueError('complete cost dimensions required; unknown must be explicit null')
    for key, amount in value.items():
        if amount is None and unknown:
            continue
        number(amount)
        if key in ('model_calls', 'tokens') and type(amount) is not int:
            raise ValueError('integer counts required')

def total_costs(spec, policy, spent):
    """Charge declared incremental forecasting training to its policy, never free."""
    if policy=='eval_only':return dict(spent)
    allocated=spec['training']['costs'];denominator=spec['training_amortization_units']
    return {k:None if spent[k] is None or allocated[k] is None else spent[k]+allocated[k]/denominator for k in COSTS}

def register(path, spec):
    """Spec contains no observed target outcomes. Caller retains returned digest externally."""
    if spec['mode'] not in ('synthetic-fixture', 'internal-rehearsal', 'prospective'):
        raise ValueError('explicit evidence mode required')
    if spec['unit_of_analysis'] != 'release-decision-opportunity':
        raise ValueError('freeze one release opportunity as unit, not individual agent episodes')
    if spec['aggregation'] != 'equal-source-family':
        raise ValueError('equal source family aggregation required')
    if spec['comparison'] != 'sequential-same-operator-descriptive':
        raise ValueError('this evaluator does not implement randomized causal inference')
    if spec['unknown_cost_policy'] != 'withhold-cost-adjusted-benefit':
        raise ValueError('unknown costs cannot become zero')
    training = spec['training']
    costs(training['costs'],unknown=True)
    if type(spec['training_amortization_units']) is not int or spec['training_amortization_units']<1:
        raise ValueError('freeze positive training-cost amortization denominator')
    if len(set(training['trace_sha256'])) != len(training['trace_sha256']):
        raise ValueError('duplicate training traces')
    for trace in training['trace_sha256']:
        sha(trace)
    costs(spec['evidence_budget'], unknown=False)
    if set(spec['cost_loss_weights'])!=set(COSTS):raise ValueError('freeze every cost weight')
    for weight in spec['cost_loss_weights'].values():number(weight)
    utility = spec['utility']
    if set(utility) != {'success_reward', 'failure_penalty', 'head_switch_penalty', 'defer_utility'}:
        raise ValueError('freeze success, failure, switching and abstention utility')
    for key in ('success_reward', 'failure_penalty', 'head_switch_penalty'):
        number(utility[key])
    if type(utility['defer_utility']) not in (int, float) or not math.isfinite(utility['defer_utility']):
        raise ValueError('finite defer utility required')
    units = spec['units']
    if not units or len({u['id'] for u in units}) != len(units):
        raise ValueError('distinct complete planned units required')
    all_evidence=set(training['trace_sha256']); validation_ids=set()
    for u in units:
        if not u['id'].isalnum() or not u['source_family'] or u['source_family'] in training['source_families']:
            raise ValueError('source family split or safe unit ID violated')
        for key in ('contract','forecast_identity','eval_state_sha256','validation_identity'):
            sha(u[key])
        if u['validation_identity'] in validation_ids:
            raise ValueError('duplicate validation contract')
        validation_ids.add(u['validation_identity'])
        if not u['seeds'] or len(set(u['seeds'])) != len(u['seeds']) or any(type(s) is not int or s < 0 for s in u['seeds']):
            raise ValueError('reserve distinct later seeds for both arms')
        if set(u['seeds']) & set(u['exposed_seeds']):
            raise ValueError('later seeds overlap prior exposure')
        if set(u['evidence_traces']) != set(POLICIES):
            raise ValueError('both policy exposures required')
        for traces in u['evidence_traces'].values():
            if not traces or len(set(traces)) != len(traces):
                raise ValueError('explicit distinct policy evidence traces required')
            for trace in traces:sha(trace)
            all_evidence.update(traces)
    root=Path(path); root.mkdir(parents=True,exist_ok=False)
    registration={'schema':'decision-impact/1','nonce':secrets.token_hex(32),'spec':spec,
                  'excluded_trace_sha256':sorted(all_evidence)}
    write(root/'registration.json',registration)
    return digest(registration)

def bound(path, expected):
    r=read(Path(path)/'registration.json')
    if digest(r)!=expected:raise ValueError('registration changed')
    return r

def record_choice(path, expected, unit_id, policy, choice, spent, *, reason, protocol):
    root=Path(path); r=bound(root,expected)
    if (root/'seal.json').exists():raise ValueError('decisions already sealed')
    if policy not in POLICIES or choice not in ('base','head','defer') or not reason.strip():
        raise ValueError('explicit policy, release choice or abstention, and reason required')
    u=next((u for u in r['spec']['units'] if u['id']==unit_id),None)
    if u is None:raise ValueError('unregistered decision unit')
    if policy=='forecast_informed' and not (root/f'{unit_id}-eval_only.json').exists():
        raise ValueError('record eval-only choice before forecast-informed choice')
    costs(spent,unknown=True)
    for key,value in total_costs(r['spec'],policy,spent).items():
        if value is not None and value>r['spec']['evidence_budget'][key]:
            raise ValueError('policy exceeds common evidence budget: '+key)
    # Align with product protocol joins. Full history must be verified by its owner adapter.
    if protocol['stage']!=policy or protocol['contract']!=u['contract'] or protocol['state_sha256']!=u['eval_state_sha256'] or protocol['forecast_identity']!=u['forecast_identity']:
        raise ValueError('decision protocol does not bind this exact evidence')
    sha(protocol['row_sha256'])
    if protocol['scope'] not in ('synthetic-fixture','prospective','existing_evidence_demo'):
        raise ValueError('explicit decision provenance required')
    if r['spec']['mode']=='prospective' and protocol['scope']!='prospective':
        raise ValueError('existing evidence or synthetic decision is not prospective')
    row={'registration':expected,'unit':unit_id,'policy':policy,'choice':choice,
         'reason':reason,'costs':spent,'protocol':protocol}
    write(root/f'{unit_id}-{policy}.json',row)
    return digest(row)

def import_protocol(path, expected, unit_id, rows, policy_costs):
    """Verify all four product protocol rows before recording either decision.

    Enrollment before evaluation is not proof of human blindness or actor identity.
    Target validation must still start later through this evaluator's start receipt.
    """
    from sim.tool_trial import digest as product_digest
    root=Path(path); registration=bound(root,expected)
    unit=next((u for u in registration['spec']['units'] if u['id']==unit_id),None)
    if unit is None or len(rows)!=4:raise ValueError('complete registered four-stage protocol required')
    stages=('initial','eval_only','reveal','forecast_informed'); previous=None; at=None
    origin=rows[0].get('origin')
    if origin not in ('prospective_registration','existing_evidence_demo'):
        raise ValueError('unknown protocol origin')
    if rows[0].get('state_sha256') is not None or rows[2].get('choice') is not None:
        raise ValueError('invalid initial/reveal stage')
    for i,row in enumerate(rows):
        timestamp=datetime.datetime.fromisoformat(row['at'])
        if timestamp.tzinfo is None or (at and timestamp<at):raise ValueError('invalid protocol chronology')
        if (row.get('schema')!='tool-decision-protocol/1' or row.get('revision')!=i+1
            or row.get('stage')!=stages[i] or row.get('previous')!=previous
            or row.get('sha256')!=product_digest({k:v for k,v in row.items() if k!='sha256'})
            or row.get('contract')!=unit['contract'] or row.get('forecast_identity')!=unit['forecast_identity']
            or row.get('origin')!=origin or row.get('initial_choice')!=rows[0].get('initial_choice')
            or (i and row.get('state_sha256')!=unit['eval_state_sha256'])):
            raise ValueError('protocol chain or evidence identity changed')
        previous=row['sha256'];at=timestamp
    scope='prospective' if origin=='prospective_registration' else 'existing_evidence_demo'
    # Validate provenance and budgets before the first append to avoid a partial import.
    if registration['spec']['mode']=='prospective' and scope!='prospective':
        raise ValueError('historical demonstration is not prospective decision data')
    for policy in POLICIES:
        costs(policy_costs[policy],unknown=True)
        if any(v is not None and v>registration['spec']['evidence_budget'][k] for k,v in total_costs(registration['spec'],policy,policy_costs[policy]).items()):
            raise ValueError('policy exceeds shared evidence budget')
    if any((root/f'{unit_id}-{p}.json').exists() for p in POLICIES):
        raise ValueError('decision unit already recorded')
    for row in (rows[1],rows[3]):
        if row['choice'] not in ('base','head','defer') or not isinstance(row['reason'],str) or not row['reason'].strip():
            raise ValueError('choice and reason required')
    for row in (rows[1],rows[3]):
        protocol={k:row[k] for k in ('stage','contract','state_sha256','forecast_identity')}
        protocol.update(row_sha256=row['sha256'],scope=scope)
        record_choice(root,expected,unit_id,row['stage'],row['choice'],policy_costs[row['stage']],reason=row['reason'],protocol=protocol)

def seal(path, expected):
    root=Path(path); r=bound(root,expected)
    rows={f"{u['id']}-{p}":digest(read(root/f"{u['id']}-{p}.json")) for u in r['spec']['units'] for p in POLICIES}
    value={'registration':expected,'choices':rows}
    write(root/'seal.json',value)
    return digest(value)

def start(path, expected_seal):
    root=Path(path); s=read(root/'seal.json')
    if digest(s)!=expected_seal:raise ValueError('choice seal changed')
    bound(root,s['registration'])
    for name,h in s['choices'].items():
        if digest(read(root/(name+'.json')))!=h:raise ValueError('sealed choice changed')
    value={'seal':expected_seal,'nonce':secrets.token_hex(32)}
    write(root/'start.json',value)
    return digest(value)

def evaluate(path, expected_seal, expected_start, outcomes):
    root=Path(path); seal=read(root/'seal.json'); started=read(root/'start.json')
    if digest(seal)!=expected_seal or digest(started)!=expected_start or started['seal']!=expected_seal:
        raise ValueError('later execution is not bound to sealed decisions')
    r=bound(root,seal['registration']);spec=r['spec']
    choices={}
    for name,h in seal['choices'].items():
        choices[name]=read(root/(name+'.json'))
        if digest(choices[name])!=h:raise ValueError('sealed choice changed')
    units={u['id']:u for u in spec['units']}
    slots={(u['id'],arm,seed) for u in units.values() for arm in ('base','head') for seed in u['seeds']}
    observed=set();traces=set();success={uid:{a:[] for a in ('base','head')} for uid in units}
    for row in outcomes:
        if type(row['seed']) is not int:raise ValueError('integer reserved seed required')
        slot=(row['unit'],row['arm'],row['seed'])
        if slot not in slots or slot in observed:raise ValueError('extra, duplicate or unreserved outcome')
        u=units[row['unit']]
        if row['start']!=expected_start or row['validation_identity']!=u['validation_identity']:
            raise ValueError('outcome execution identity changed')
        if type(row['completed']) is not bool or row['status'] not in ('completed','failed','timeout','operational_error'):
            raise ValueError('terminal controller outcome required')
        if row['status']!='completed' and row['completed']:
            raise ValueError('failed outcome cannot claim success')
        sha(row['trace_sha256'])
        if row['trace_sha256'] in traces or row['trace_sha256'] in r['excluded_trace_sha256']:
            raise ValueError('training, decision evidence or target trace overlap')
        costs(row['measurement_costs'],unknown=True)
        observed.add(slot);traces.add(row['trace_sha256']);success[row['unit']][row['arm']].append(int(row['completed']))
    if observed!=slots:raise ValueError('missing denominator: every planned unit/arm/seed must be terminal')
    u=spec['utility'];results=[]
    for uid,unit in units.items():
        rates={arm:sum(ys)/len(ys) for arm,ys in success[uid].items()}
        values={arm:rate*u['success_reward']-(1-rate)*u['failure_penalty']-(u['head_switch_penalty'] if arm=='head' else 0) for arm,rate in rates.items()}
        values['defer']=u['defer_utility']
        result={'unit':uid,'source_family':unit['source_family'],'rates':rates,'policies':{}}
        for policy in POLICIES:
            decision=choices[f'{uid}-{policy}'];spent=total_costs(spec,policy,decision['costs'])
            unknown=sorted(k for k,v in spent.items() if v is None)
            loss=None if unknown else sum(spent[k]*spec['cost_loss_weights'][k] for k in COSTS)
            raw=values[decision['choice']]
            result['policies'][policy]={'choice':decision['choice'],'abstained':decision['choice']=='defer',
                'task_utility':raw,'empirical_regret':max(values.values())-raw,
                'cost_adjusted_utility':None if loss is None else raw-loss,
                'unknown_costs':unknown,'costs':spent,'direct_costs':decision['costs']}
        left,right=(result['policies'][p] for p in POLICIES)
        result['task_utility_delta']=right['task_utility']-left['task_utility']
        result['cost_adjusted_delta']=None if left['cost_adjusted_utility'] is None or right['cost_adjusted_utility'] is None else right['cost_adjusted_utility']-left['cost_adjusted_utility']
        result['all_costs_measured']=not (left['unknown_costs'] or right['unknown_costs'])
        results.append(result)
    families={f:[r for r in results if r['source_family']==f] for f in sorted({r['source_family'] for r in results})}
    mean=lambda xs:sum(xs)/len(xs)
    adjusted=None if any(r['cost_adjusted_delta'] is None for r in results) else mean([mean([r['cost_adjusted_delta'] for r in rs]) for rs in families.values()])
    return {'mode':spec['mode'],'unit_of_analysis':spec['unit_of_analysis'],'n_units':len(units),
        'n_source_families':len(families),'n_outcomes':len(outcomes),'n_reserved':len(slots),
        'units':results,'equal_family_task_utility_delta':mean([mean([r['task_utility_delta'] for r in rs]) for rs in families.values()]),
        'equal_family_cost_adjusted_delta':adjusted,'common_evidence_cap':spec['evidence_budget'],
        'measurement_costs':[r['measurement_costs'] for r in outcomes],
        'claim':{'synthetic-fixture':'SYNTHETIC fixture arithmetic only',
                 'internal-rehearsal':'Internal agent-operated workflow rehearsal on synthetic task; no buyer impact or generalization',
                 'prospective':'Descriptive sequential declared-choice comparison on reserved local controller outcomes'}[spec['mode']],
        'limits':'Common budget ceilings, not equal spend. Unknown costs withhold adjusted benefit. Setup, inference and review exposure are policy-specific; later validation costs are separate shared research overhead. No causal human decision benefit, trusted chronology or independently authenticated trace provenance.'}
