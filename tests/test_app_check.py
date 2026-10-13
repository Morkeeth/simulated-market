import json
from types import SimpleNamespace
import pytest
from sim import app_check, hosted_cost


def test_invalid_app_links_refuse_before_starting_a_visit(tmp_path):
    ws=SimpleNamespace(root=tmp_path)
    for link in (None,'https://example.com/?secret=private','http://public.example/','https://user:password@example.com/'):
        with pytest.raises(ValueError):app_check.start(ws,{'url':link})
    assert not (tmp_path/'app-checks').exists()


def test_paid_report_stop_accounts_for_a_still_held_failure(tmp_path, monkeypatch):
    ws=SimpleNamespace(root=tmp_path/'store',allow_app_report=True)
    run='a'*24;folder=ws.root/'app-checks'/run;folder.mkdir(parents=True)
    (folder/'result.json').write_text(json.dumps({'id':run,'status':'complete'}))
    prior=tmp_path/'prior.json';prior.write_text(json.dumps({'runs':[{'committed_usd':0.486506}]}))
    account=tmp_path/'cost.json';account.write_text(json.dumps({'runs':{'known':{'accounted_usd':2.9},'uncertain':{'accounted_usd':4.614912,'status':'unknown_usage_reservation_held'}}}))
    monkeypatch.setattr(hosted_cost,'PRIOR',prior);monkeypatch.setattr(hosted_cost,'RECORD',account)
    before=account.read_bytes()
    with pytest.raises(ValueError,match='reporting stop'):app_check.report(ws,{'id':run})
    assert account.read_bytes()==before
    assert not (folder/'agent-report.json').exists()


def test_report_reopen_does_not_reserve_or_need_execution_permission(tmp_path):
    ws=SimpleNamespace(root=tmp_path,allow_app_report=False)
    run='b'*24;p=tmp_path/'app-checks'/run;p.mkdir(parents=True)
    (p/'result.json').write_text(json.dumps({'id':run,'status':'complete'}))
    saved={'status':'complete','text':'A retained review.','model_calls':1}
    (p/'agent-report.json').write_text(json.dumps(saved))
    assert app_check.report(ws,{'id':run})==saved
