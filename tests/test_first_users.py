import time
import pytest
from sim.check_queue import Queue
from sim import first_users_payment
from sim.favour_handoff import project_draft

def test_fenced_lease_rejects_late_writer_and_reclaims(tmp_path):
    q=Queue(tmp_path/'q.sqlite',lease_seconds=.01)
    key=q.enqueue('alice','one',{'task':'read'})
    old=q.lease();time.sleep(.03);new=q.lease()
    assert old['fence']!=new['fence']
    assert not q.settle(key,old['fence'],{'wrong':True})
    assert q.settle(key,new['fence'],{'right':True})
    assert not q.settle(key,new['fence'],{'duplicate':True})
    assert q.get('alice',key)['result']=={'right':True}
    assert q.get('bob',key) is None

def test_paid_jobs_do_not_silently_retry_after_expiry(tmp_path):
    q=Queue(tmp_path/'q.sqlite',lease_seconds=.01,max_attempts=1)
    key=q.enqueue('alice','paid',{});q.lease();time.sleep(.03)
    assert q.lease() is None and q.get('alice',key)['state']=='failed'

def test_durable_quota_total_and_duplicate_identity(tmp_path):
    q=Queue(tmp_path/'q.sqlite',quota=1,max_total=2)
    key=q.enqueue('alice','one',{'task':'read'})
    assert q.enqueue('alice','one',{'task':'read'})==key
    with pytest.raises(ValueError):q.enqueue('alice','two',{})
    with pytest.raises(ValueError):q.enqueue('alice','one',{'task':'different'})
    q.enqueue('bob','one',{})
    with pytest.raises(ValueError):q.enqueue('carol','one',{})
    assert Queue(q.path).get('alice',key) is not None

def test_over_cap_result_is_not_completed_and_share_is_scoped(tmp_path):
    q=Queue(tmp_path/'q.sqlite');key=q.enqueue('alice','over',{},cap_microusd=1);job=q.lease()
    assert q.settle(key,job['fence'],{'done':True},cost_microusd=2)
    assert q.get('alice',key)['state']=='failed'
    with pytest.raises(ValueError):q.share('alice',key)
    key=q.enqueue('alice','good',{});job=q.lease();q.settle(key,job['fence'],{'screens':[]})
    with pytest.raises(ValueError):q.share('bob',key)
    old=q.share('alice',key);new=q.share('alice',key)
    assert q.shared(old) is None and q.shared(new)['id']==key

def test_no_live_key_or_client_paid_flag(monkeypatch):
    monkeypatch.setenv('STRIPE_TEST_SECRET_KEY','sk_live_invalid_example')
    with pytest.raises(ValueError):first_users_payment.test_key()
    assert not first_users_payment.verified('client-says-paid','job')

def test_human_handoff_does_not_claim_publication_or_funding():
    d=project_draft('http://127.0.0.1:8080/samples/working','Read the guide and return')
    assert d['status']=='DRAFT_NOT_POSTED' and d['public_url_needed']
    assert d['reward_plan']['funding_status']=='UNFUNDED'
    assert d['reward_plan']['requires_builder_signature']
    assert len(d['test_deck'])==5 and d['test_deck'][3]['required']
    assert d['project']['task']['required_moves']==['went_somewhere','came_back']
    with pytest.raises(ValueError):project_draft('https://user:password@example.invalid/','Read')
