"""Stripe TEST checkout only when an explicitly named test secret is present.

No live mode, account creation, webhook or real entitlement. Otherwise a clearly
labelled practice step. A return query alone never establishes payment.
"""
from pathlib import Path
import json,os,urllib.request,urllib.parse

KEY_PLACE='~/.config/keys/stripe-test.key'

def test_key():
    value=os.environ.get('STRIPE_TEST_SECRET_KEY') or os.environ.get('STRIPE_SECRET_KEY')
    p=Path.home()/'.config/keys/stripe-test.key'
    if not value and p.is_file():value=p.read_text().strip()
    if not value:return None
    if not value.startswith('sk_test_'):raise ValueError('Only a Stripe test secret is accepted; live payment is disabled.')
    return value

def request(path,fields=None):
    key=test_key()
    if not key:raise ValueError('No Stripe test key. Use the labelled practice step.')
    data=urllib.parse.urlencode(fields).encode() if fields is not None else None
    req=urllib.request.Request('https://api.stripe.com/v1/'+path,data=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)

def begin(job,base):
    if not test_key():return {'mode':'PRACTICE_NO_CHARGE','key_place':KEY_PLACE,'amount_eur':19,'paid':False}
    r=request('checkout/sessions',{'mode':'payment','line_items[0][price_data][currency]':'eur',
        'line_items[0][price_data][unit_amount]':'1900','line_items[0][price_data][product_data][name]':'First Users — one app check',
        'line_items[0][quantity]':'1','metadata[first_users_job]':job,
        'success_url':base+'/?draft='+job+'&checkout={CHECKOUT_SESSION_ID}','cancel_url':base+'/?cancelled=1'})
    if r.get('livemode') is not False:raise ValueError('Non-test session rejected.')
    return {'mode':'STRIPE_TEST','url':r['url'],'session':r['id'],'paid':False}

def verified(session,job):
    if not session.startswith('cs_test_'):return False
    r=request('checkout/sessions/'+urllib.parse.quote(session,safe=''))
    return r.get('livemode') is False and r.get('payment_status')=='paid' and r.get('amount_total')==1900 and r.get('currency')=='eur' and r.get('metadata',{}).get('first_users_job')==job
