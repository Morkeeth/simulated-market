"""LOCAL payment design stub. Never contacts Stripe or grants real entitlements."""
import json
from pathlib import Path
PLANS={'starter':{'usd_month':19,'checks':100},'team':{'usd_month':99,'checks':1000}}

def checkout_request(plan, customer_ref):
    if plan not in PLANS or not isinstance(customer_ref,str) or not customer_ref.strip():
        raise ValueError('Choose a plan and an internal customer reference.')
    return {'label':'LOCAL-STUB','provider':'Stripe Checkout','mode':'subscription',
            'plan':plan,'customer_ref':customer_ref,'price_id':'configure Stripe test Price ID',
            'payment_created':False,'redirect_url':None}

def fulfill_test_event(store, event):
    """Exercise duplicate/out-of-order event handling, not a Stripe signature verifier.

    Real endpoint must verify Stripe-Signature over untouched raw bytes before
    constructing this internal event; this stub accepts only LOCAL test events.
    """
    if event.get('label')!='LOCAL-STUB' or event.get('type')!='checkout.session.completed' or event.get('livemode') is not False:
        raise ValueError('Only explicitly labelled local test events are accepted.')
    if event.get('payment_status')!='paid' or event.get('plan') not in PLANS:
        raise ValueError('An unpaid or unknown plan cannot grant test credits.')
    if not all(isinstance(event.get(k),str) and event[k] for k in ('id','customer_ref','period')):
        raise ValueError('Event, customer and billing period identities are required.')
    p=Path(store);data=json.loads(p.read_text()) if p.exists() else {'label':'LOCAL-STUB','events':[],'grants':{}}
    grant=event['customer_ref']+'/'+event['period']
    if event['id'] in data['events'] or grant in data['grants']: return {'applied':False,'reason':'already credited','label':'LOCAL-STUB'}
    data['events'].append(event['id']);data['grants'][grant]=PLANS[event['plan']]['checks']
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2))
    return {'applied':True,'test_credits':data['grants'][grant],'label':'LOCAL-STUB','real_entitlement':False}
