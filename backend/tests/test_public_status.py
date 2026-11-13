import json
import httpx
import pytest
from scripts import public_demo

@pytest.mark.parametrize('response,available',[
    (httpx.Response(200,json={'status':'ok'}),True),
    (httpx.Response(530,text='Tunnel error'),False),
    (httpx.Response(200,text='not a health endpoint'),False),
    (httpx.ConnectError('DNS lookup failed'),False),
])
def test_status_checks_external_health_instead_of_process_only(tmp_path,monkeypatch,capsys,response,available):
    monkeypatch.setattr(public_demo,'STATE',tmp_path)
    monkeypatch.setattr(public_demo,'alive',lambda pid:True)
    (tmp_path/'supervisor.pid').write_text('123')
    (tmp_path/'deployment.json').write_text(json.dumps({'url':'https://demo.example','admin_url':'https://demo.example/admin'}))
    def get(url,**kwargs):
        assert url=='https://demo.example/api/health'
        if isinstance(response,Exception):raise response
        return response
    monkeypatch.setattr(public_demo.httpx,'get',get)
    public_demo.status();output=capsys.readouterr().out
    assert 'Supervisor: running' in output
    assert ('Public HTTPS: available' in output)==available
    assert ('Public HTTPS: unavailable' in output)==(not available)
