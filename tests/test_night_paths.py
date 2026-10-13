import pytest
from sim import docs_rescue, payment_stub
from sim.adapters.tavily import Candidate
from sim import task_contract

def test_runtime_task_cannot_be_shortened():
    import json
    from types import SimpleNamespace
    job='Read the tutorial on how to post a run, then return to the collection'
    class LocalClientDouble:
        def __init__(self, text):self.text=text
        def chat(self,*a,**k):
            return SimpleNamespace(text=json.dumps({'task':self.text,'intent':'read','required_moves':['went_somewhere','came_back']}),finish_reason='stop')
    # Retained real failure replay, labelled LOCAL; no provider runs in tests.
    with pytest.raises(ValueError,match='changed the task'):
        task_contract.compile_runtime(job,LocalClientDouble('post a run'))
    assert task_contract.compile_runtime(job,LocalClientDouble(job))[0].task==job
    assert 'uniqueItems' not in task_contract.structured_request(job)['response_format']['json_schema']['schema']['properties']['required_moves']
    with pytest.raises(ValueError):task_contract.validate({'task':job,'intent':'read','required_moves':['went_somewhere','went_somewhere']})

def test_rescue_filters_unofficial_without_claiming_completion(monkeypatch):
    monkeypatch.setattr(docs_rescue.tavily,'search',lambda *a,**k:[Candidate('https://docs.example.com/help','Help','public'),Candidate('https://evil.example/help','Bad','bad'),Candidate('http://docs.example.com/help','HTTP','bad')])
    r=docs_rescue.rescue('Install the browser',['docs.example.com'])
    assert len(r['sources'])==1 and len(r['rejected_urls'])==2 and r['task_completion']=='not assessed'

def test_rescue_requires_domain_before_network(monkeypatch):
    monkeypatch.setattr(docs_rescue.tavily,'search',lambda *a,**k:pytest.fail('must not call'))
    with pytest.raises(ValueError):docs_rescue.rescue('Read help',[])

def test_local_payment_never_creates_checkout():
    r=payment_stub.checkout_request('starter','builder1')
    assert r['payment_created'] is False and r['redirect_url'] is None

def test_payment_duplicate_and_unpaid_controls(tmp_path):
    store=tmp_path/'credits.json';e={'label':'LOCAL-STUB','type':'checkout.session.completed','livemode':False,'payment_status':'paid','plan':'starter','id':'local1','customer_ref':'builder1','period':'2026-10'}
    assert payment_stub.fulfill_test_event(store,e)['test_credits']==100
    assert payment_stub.fulfill_test_event(store,{**e,'id':'local2'})['applied'] is False
    for change in ({'livemode':True},{'payment_status':'unpaid'},{'label':'Stripe'},{'type':'invoice.failed'}):
        with pytest.raises(ValueError):payment_stub.fulfill_test_event(store,{**e,**change})
