import io
import json
from datetime import datetime
import pytest
from pypdf import PdfReader
from backend import main,weather
from backend.settings import Settings
from backend.tests.test_operations import client,provider_fixture,HEADERS


def test_route_arithmetic_eta_savings_and_recommendation_use_same_scenario(client):
    for storm,load in [(0,None),(100,None),(100,30),(100,99)]:
        params={'storm':storm,**({'port_load':load} if load else {})}
        d=client.get('/dashboard',params=params).json();settings=d['settings']
        for shipment in d['shipments']:
            routes=shipment['alternatives'];current=next(r for r in routes if r['id']==shipment['route_id'])
            for r in routes:
                assert r['total_hours']==round(r['hours']+r['delay_hours'],1)
                elapsed=(datetime.fromisoformat(r['eta_at'])-datetime.fromisoformat(shipment['departed_at'])).total_seconds()/3600
                assert elapsed==pytest.approx(r['total_hours'])
                transport=round(sum(s['km']*shipment['weight']*settings[s['mode']+'_usd_per_tkm'] for s in r['segments'])+r['transfers']*settings['transfer_usd'],2)
                assert r['economics']['transport_usd']==transport
                assert r['economics']['total_cost_usd']==round(transport+r['delay_hours']*settings['delay_usd_per_hour'],2)
                assert r['economics']['potential_savings_usd']==round(current['economics']['total_cost_usd']-r['economics']['total_cost_usd'],2)
                assert r['co2_kg']==round(sum(s['km']*shipment['weight']*main.FACTORS[s['mode']] for s in r['segments']))
            fields=[('eta_weight',lambda r:r['total_hours']),('cost_weight',lambda r:r['economics']['total_cost_usd']),('co2_weight',lambda r:r['co2_kg'])]
            def score(r):
                total=0
                for weight,value in fields:
                    lo=min(value(x) for x in routes);hi=max(value(x) for x in routes)
                    total+=settings[weight]*(0 if hi==lo else (value(r)-lo)/(hi-lo))
                return round(total,6)
            assert shipment['recommendation']['route_id']==min(routes,key=lambda r:(score(r),r['id']))['id']
    calm=client.get('/dashboard?storm=0').json()['shipments'][0]
    storm=client.get('/dashboard?storm=100').json()['shipments'][0]
    assert calm['recommendation']['route_id']=='direct' and storm['recommendation']['route_id']=='west'
    assert storm['route']['delay_hours']>calm['route']['delay_hours']
    assert storm['recommendation']['conditional']  # explicit land validation limitation


def test_dashboard_reads_settings_once_for_consistent_route_comparison(client,monkeypatch):
    calls=[]
    def settings(db):
        calls.append(1)
        return Settings(delay_usd_per_hour=150 if len(calls)==1 else 999)
    monkeypatch.setattr(main,'load_settings',settings)
    d=client.get('/dashboard').json()
    assert len(calls)==1
    assert all(r['economics']['delay_cost_usd']==round(r['delay_hours']*150,2) for s in d['shipments'] for r in s['alternatives'])


def export(c,shipment,**params):
    return c.get('/reports/'+shipment['id'],headers=HEADERS,params={'expected_snapshot':shipment['report_snapshot'],**params})


def test_pdf_is_valid_cyrillic_and_uses_the_displayed_manual_snapshot(client):
    shipment=client.get('/dashboard?storm=100&port_load=99').json()['shipments'][0]
    r=export(client,shipment,mode='manual',storm=100,port_load=99)
    assert r.status_code==200 and r.headers['content-type']=='application/pdf'
    assert r.headers['content-disposition'].endswith('-manual.pdf"')
    assert r.headers['cache-control']=='no-store' and r.content.startswith(b'%PDF-')
    pdf=PdfReader(io.BytesIO(r.content));text='\n'.join(page.extract_text() for page in pdf.pages)
    assert len(pdf.pages)>=2
    for expected in ['CF-2026-0841','Промышленное оборудование','ручная симуляция','Шторм: 100%','99%',
                     'Сухопутный прогноз отдельно не валидирован',shipment['report_snapshot'],'ДЕМОНСТРАЦИОННЫЙ ОТЧЁТ','Источники']:
        assert expected in text
    for r in shipment['alternatives']:
        assert r['name'] in text
        assert f"{r['total_hours']:.1f}".replace('.',',') in text
    assert 'test-private-key' not in text and 'scrypt$' not in text


def test_pdf_rejects_stale_parameters_or_tariffs_instead_of_exporting_different_values(client):
    shipment=client.get('/dashboard?storm=0').json()['shipments'][0]
    assert export(client,shipment,storm=100).status_code==409
    with main.db() as c:c.execute("UPDATE settings SET value=? WHERE key='operator'",(Settings(delay_usd_per_hour=151).model_dump_json(),))
    assert export(client,shipment,storm=0).status_code==409
    fresh=client.get('/dashboard?storm=0').json()['shipments'][0]
    assert export(client,fresh,storm=0).status_code==200


def test_auto_pdf_preserves_missing_weather_and_declares_sources(client,monkeypatch):
    monkeypatch.setattr(weather,'fetch_provider',lambda kind:provider_fixture(kind,missing=True))
    main.weather_service=weather.WeatherService()
    data=client.get('/forecast').json();shipment=data['shipments'][0]
    anchor=datetime.fromisoformat(data['weather']['starts_at'])
    for route in shipment['alternatives']:
        if route['delay_hours'] is None:
            assert route['total_hours'] is None and route['eta_at'] is None
            assert route['economics']['total_cost_usd'] is None
        else:
            assert route['total_hours']==round(route['hours']+route['delay_hours'],1)
            assert (datetime.fromisoformat(route['eta_at'])-anchor).total_seconds()/3600==pytest.approx(route['total_hours'])
    assert shipment['alternatives'][0]['delay_hours'] is None
    response=export(client,shipment,mode='auto')
    assert response.status_code==200
    text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
    assert 'Недостаточно данных' in text and 'Open-Meteo' in text
    assert 'None' not in text and 'NaN' not in text
    assert export(client,shipment,mode='auto',storm=100).status_code==422


def test_pdf_requires_service_key_valid_snapshot_and_existing_cargo(client):
    shipment=client.get('/dashboard').json()['shipments'][0]
    assert client.get('/reports/'+shipment['id'],params={'expected_snapshot':shipment['report_snapshot']}).status_code==401
    assert client.get('/reports/'+shipment['id'],headers=HEADERS,params={'expected_snapshot':'invalid'}).status_code==422
    assert client.get('/reports/CF-2026-9999',headers=HEADERS,params={'expected_snapshot':shipment['report_snapshot']}).status_code==404
