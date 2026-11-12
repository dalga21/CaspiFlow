import json
import secrets
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from backend import main,weather,admin
from backend.settings import Settings,economics,recommend

@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'operations.sqlite')
    monkeypatch.setenv('CUSTOMS_API_KEY','test-private-key')
    password=secrets.token_urlsafe(24)
    monkeypatch.setenv('CASPIFLOW_ADMIN_PASSWORD_HASH',admin.hash_password(password))
    with TestClient(main.app) as c:
        c.test_password=password
        yield c

HEADERS={'X-API-Key':'test-private-key'}
def login(c):
    response=c.post('/admin/login',headers=HEADERS,json={'password':c.test_password})
    assert response.status_code==200
    return response


def provider_fixture(kind,missing=False,wind=10,wave=1):
    start=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    points=weather.POINTS if kind=='wind' else weather.POINTS[:6]
    return {p['id']:{int(start.timestamp())+i*3600:(None if missing and kind=='wave' and p['id']=='direct-south' else wind if kind=='wind' else wave) for i in range(72)} for p in points}


def test_forecast_real_inputs_missing_data_alerts_and_economics(client,monkeypatch):
    monkeypatch.setattr(weather,'fetch_provider',lambda kind:provider_fixture(kind,missing=True,wind=23,wave=4))
    seen=[];original=main.model.predict
    def spy(x):seen.extend(x);return original(x)
    monkeypatch.setattr(main.model,'predict',spy)
    r=client.get('/forecast');assert r.status_code==200
    data=r.json();assert len(data['weather']['points'][0]['hourly'])==72
    assert data['weather']['source']=='Open-Meteo'
    direct,east,west=(next(r for r in data['shipments'][0]['alternatives'] if r['id']==id) for id in ('direct','east','west'))
    assert direct['delay_hours'] is None and direct['eta_at'] is None
    assert direct['economics']['total_cost_usd'] is None
    assert direct['economics']['transport_usd']>0
    assert east['prediction']['inputs']['wind_m_s']==23
    assert east['prediction']['inputs']['wave_m']==4
    assert west['prediction']['inputs']['wave_m']==0
    assert len(seen)==8  # two complete routes x four existing shipments
    assert east['economics']['delay_cost_usd']==round(east['delay_hours']*150,2)
    assert data['shipments'][0]['recommendation']['conditional']
    assert any(a['severity']=='data_gap' and a['point_id']=='direct-south' for a in data['alerts'])
    assert any(a['severity']=='danger' for a in data['alerts'])
    assert all(h['risk_index'] is None for h in next(p for p in data['weather']['points'] if p['id']=='direct-south')['hourly'])
    assert all(s['economics']['potential_savings_usd'] is None for s in data['shipments'][0]['alternatives'])


def test_no_provider_fallback_and_short_failure_cache(client,monkeypatch):
    def fail(kind):raise weather.httpx.ConnectError('external failure')
    monkeypatch.setattr(weather,'fetch_provider',fail)
    data=client.get('/forecast').json()
    assert len(data['weather']['errors'])==2
    assert all(r['prediction']['source']=='unavailable' for r in data['shipments'][0]['alternatives'])
    assert data['shipments'][0]['recommendation']['route_id'] is None
    assert any(a['severity']=='data_gap' for a in data['alerts'])


def test_weather_cache_and_passage_excludes_later_unrelated_storm(client,monkeypatch):
    calls=[]
    def fetch(kind):calls.append(kind);return provider_fixture(kind)
    monkeypatch.setattr(weather,'fetch_provider',fetch)
    first=client.get('/forecast').json();second=client.get('/forecast').json()
    assert sorted(calls)==['wave','wind']
    assert first['weather']['fetched_at']==second['weather']['fetched_at']
    raw=weather.WeatherService().snapshot();enriched=weather.enrich_snapshot(raw,Settings())
    # Southern direct point is passed well before +65h: later storm must not affect voyage features.
    for p in enriched['points']:
        for i,h in enumerate(p['hourly']):
            if i>=65:h.update(wind=50,wave=10,severity='danger')
    trip=weather.passage(main.ROUTES[0],enriched,Settings())
    assert trip['complete'] and trip['wind']==10 and trip['wave']==1
    assert not trip['alerts']


def test_risk_index_is_not_probability_and_missing_is_not_zero():
    settings=Settings()
    assert weather.risk(10,1,settings)['risk_index']==50
    r=weather.risk(25,None,settings)
    assert r['severity']=='danger' and r['risk_index'] is None and not r['complete']
    assert weather.risk(None,None,settings)['severity']=='unknown'


def test_admin_authentication_expiry_logout_and_no_secret_echo(client):
    assert client.get('/admin/data').status_code==401
    assert client.get('/admin/data',headers=HEADERS).status_code==401
    bad=client.post('/admin/login',headers=HEADERS,json={'password':'wrong'})
    assert bad.status_code==401 and 'wrong' not in bad.text
    response=login(client)
    assert 'httponly' in response.headers['set-cookie'].lower() and 'samesite=strict' in response.headers['set-cookie'].lower()
    assert client.get('/admin/data',headers=HEADERS).status_code==200
    assert client.get('/admin/data').status_code==401
    with main.db() as c:
        token=c.execute('SELECT token_hash FROM admin_sessions').fetchone()[0]
        assert token!=client.cookies.get(admin.COOKIE)
        c.execute('UPDATE admin_sessions SET expires_at=0')
    assert client.get('/admin/data',headers=HEADERS).status_code==401
    login(client)
    assert client.post('/admin/logout',headers=HEADERS).status_code==200
    assert client.get('/admin/data',headers=HEADERS).status_code==401
    response=client.post('/admin/login',headers=HEADERS,json={'password':'z'*1000})
    assert response.status_code==422 and 'z'*20 not in response.text


def test_admin_rate_limit(client):
    for _ in range(5):assert client.post('/admin/login',headers=HEADERS,json={'password':'bad'}).status_code==401
    assert client.post('/admin/login',headers=HEADERS,json={'password':client.test_password}).status_code==429
    with main.db() as c:c.execute('UPDATE admin_attempts SET created_at=0')
    login(client)


def test_admin_cargo_settings_audit_and_existing_customs(client):
    login(client)
    cargo={'id':'CF-2026-9991','name':'Новый груз','owner':'Тест оператора','weight':5,'route_id':'east','status':'planned','progress':0,'container':'TEST'}
    assert client.post('/admin/shipments',headers=HEADERS,json=cargo).status_code==200
    assert client.post('/admin/shipments',headers=HEADERS,json=cargo).status_code==409
    updated={**cargo,'status':'delayed','progress':.5,'weight':10}
    assert client.put('/admin/shipments/'+cargo['id'],headers=HEADERS,json=updated).status_code==200
    assert client.get('/shipments/'+cargo['id']).json()['status']=='delayed'
    invalid={**updated,'status':'delivered'}
    assert client.put('/admin/shipments/'+cargo['id'],headers=HEADERS,json=invalid).status_code==422
    settings=Settings().model_dump();settings['delay_usd_per_hour']=400
    assert client.put('/admin/settings',headers=HEADERS,json=settings).status_code==200
    result=client.get('/shipments/'+cargo['id']).json()
    assert result['route']['economics']['delay_cost_usd']==round(result['route']['delay_hours']*400,2)
    assert client.put('/admin/settings',headers=HEADERS,json={**settings,'wind_warning':30}).status_code==422
    assert client.put('/admin/settings',headers=HEADERS,json={**settings,'eta_weight':0}).status_code==422
    data=client.get('/admin/data',headers=HEADERS).json()
    assert {'shipment_created','shipment_updated','settings_updated'}.issubset({r['action'] for r in data['audit']})
    assert 'password' not in json.dumps(data['audit'])


def test_economics_and_recommendation_known_arithmetic():
    settings=Settings();route=main.ROUTES[0]
    value=economics(route,24.8,10,settings)
    assert value['transport_usd']==round(24.8*(280*.035+1060*.02+45*.08)+2*75,2)
    assert value['delay_cost_usd']==1500
    assert value['total_cost_usd']==round(value['transport_usd']+1500,2)
    routes=[{'id':id,'delay_hours':delay,'total_hours':total,'co2_kg':co2,'economics':{'transport_usd':transport,'total_cost_usd':cost}} for id,delay,total,co2,transport,cost in [('a',2,10,100,200,500),('b',1,9,90,220,400)]]
    decision=recommend(routes,'a',settings)
    assert decision['route_id']=='b' and not decision['conditional']
    assert routes[1]['economics']['potential_savings_usd']==100
    assert routes[1]['economics']['additional_transport_usd']==20


def test_weather_units_and_out_of_horizon_are_not_silently_accepted(client,monkeypatch):
    class WrongUnits:
        status_code=200
        def raise_for_status(self):pass
        def json(self):
            return [{'hourly_units':{'wind_speed_10m':'km/h'},'hourly':{'time':[],'wind_speed_10m':[]}} for _ in weather.POINTS]
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:WrongUnits())
    with pytest.raises(ValueError,match='units'):weather.fetch_provider('wind')
    monkeypatch.setattr(weather,'fetch_provider',lambda kind:provider_fixture(kind))
    raw=weather.WeatherService().snapshot();enriched=weather.enrich_snapshot(raw,Settings())
    route={**main.ROUTES[2],'hours':160}
    trip=weather.passage(route,enriched,Settings())
    assert not trip['complete'] and any(a['severity']=='data_gap' for a in trip['alerts'])


def test_recommendation_respects_configured_co2_priority():
    settings=Settings(eta_weight=0,cost_weight=0,co2_weight=1)
    routes=[{'id':id,'delay_hours':1,'total_hours':duration,'co2_kg':co2,'economics':{'transport_usd':cost,'total_cost_usd':cost}} for id,duration,co2,cost in [('fast',10,200,20),('green',20,100,30)]]
    assert recommend(routes,'fast',settings)['route_id']=='green'
