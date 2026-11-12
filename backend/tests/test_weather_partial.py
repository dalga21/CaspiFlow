"""Regression cases using real response shapes; fixtures are not application fallback data."""
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from backend import weather
from backend.settings import Settings


def payload(kind,start=None):
    start=start or weather.utcnow().replace(minute=0,second=0,microsecond=0)
    points=weather.POINTS if kind=='wind' else weather.POINTS[:6]
    field='wind_speed_10m' if kind=='wind' else 'wave_height';unit='m/s' if kind=='wind' else 'm'
    return [{'location_id':i,'latitude':p['lat'],'longitude':p['lon'],'hourly_units':{'time':'unixtime',field:unit},
             'hourly':{'time':[int((start+timedelta(hours=h)).timestamp()) for h in range(72)],field:[10 if kind=='wind' else 1]*72}}
            for i,p in enumerate(points)]


def response(data):return httpx.Response(200,json=data,request=httpx.Request('GET','https://api.open-meteo.com/v1/forecast'))


def test_one_broken_location_does_not_erase_whole_source(monkeypatch):
    data=payload('wind');data[2]['hourly_units']['wind_speed_10m']='km/h'
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    parsed=weather.fetch_provider('wind')
    assert len(parsed['direct-north'])==72
    assert len(parsed['east-mid'])==72
    assert parsed['direct-south']=={}
    assert parsed.diagnostics['direct-south']['status']=='invalid_response'
    assert parsed.diagnostics['direct-south']['http_status']==200
    assert 'units' in parsed.diagnostics['direct-south']['reason']


def test_partial_fields_and_iso_times_preserve_good_hours(monkeypatch):
    data=payload('wind')
    first=data[0]['hourly'];first['wind_speed_10m']=first['wind_speed_10m'][:70]
    first['time']=[datetime.fromtimestamp(t,timezone.utc).isoformat() for t in first['time']]
    first['time'][4]='invalid-time'
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    parsed=weather.fetch_provider('wind')
    assert len(parsed['direct-north'])==71
    assert sum(v is not None for v in parsed['direct-north'].values())==69
    assert 'частичный' in parsed.diagnostics['direct-north']['parse_note']
    assert len(parsed['east-north'])==72


def test_reordered_short_batch_maps_by_location_identity(monkeypatch):
    data=payload('wave');data.pop(2);data.reverse()
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    parsed=weather.fetch_provider('wave')
    assert len(parsed['direct-north'])==72 and len(parsed['east-south'])==72
    assert parsed['direct-south']=={}
    assert parsed.diagnostics['direct-south']['status']=='invalid_response'


def test_partial_wave_failure_keeps_wind_and_retry_bypasses_failure_cache(monkeypatch):
    calls=[];working=False
    def fetch(kind):
        calls.append(kind)
        if kind=='wave' and not working:raise httpx.ReadTimeout('upstream timeout')
        data=payload(kind)
        return {p['id']:{t:v for t,v in zip(part['hourly']['time'],part['hourly']['wind_speed_10m' if kind=='wind' else 'wave_height'])}
                for p,part in zip(weather.POINTS,data)}
    monkeypatch.setattr(weather,'fetch_provider',fetch)
    service=weather.WeatherService();raw=service.snapshot();enriched=weather.enrich_snapshot(raw,Settings())
    north=enriched['points'][0]
    assert all(h['wind']==10 and h['wave'] is None for h in north['hourly'])
    assert all(h['risk_index'] is None and h['wind_index']==50 and h['wave_index'] is None for h in north['hourly'])
    assert north['availability']['wave']['status']=='request_error'
    assert 'ожидания' in north['availability']['wave']['reason']
    assert len(calls)==2
    service.snapshot();assert len(calls)==2
    working=True
    recovered=service.snapshot(retry=True)
    assert len(calls)==4
    assert recovered['points'][0]['availability']['wave']['available_hours']==72
    throttled=service.snapshot(retry=True)
    assert len(calls)==4 and throttled['retry_after_seconds']>0


def test_null_waves_are_explained_not_turned_into_zero(monkeypatch):
    def fetch(kind):
        data=payload(kind)
        if kind=='wave':data[0]['hourly']['wave_height']=[None]*72
        monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
        # Calls are sequential here: no race between HTTP mock substitutions.
        return weather.fetch_provider(kind)
    wind=fetch('wind');wave=fetch('wave')
    monkeypatch.setattr(weather,'fetch_provider',lambda kind:wind if kind=='wind' else wave)
    north=weather.WeatherService().snapshot()['points'][0]
    assert north['availability']['wave']['status']=='no_coverage'
    assert north['availability']['wave']['http_status']==200
    assert 'null' in north['availability']['wave']['reason']
    assert all(h['wave'] is None for h in north['hourly'])
    assert north['availability']['wind']['available_hours']==72


def test_request_hour_does_not_move_after_slow_provider_response(monkeypatch):
    start=datetime(2026,11,12,16,59,59,tzinfo=timezone.utc)
    clock=iter([start,start+timedelta(seconds=4)])
    def fetch(kind):
        data=payload(kind,start.replace(minute=0,second=0))
        return {p['id']:dict(zip(part['hourly']['time'],part['hourly']['wind_speed_10m' if kind=='wind' else 'wave_height'])) for p,part in zip(weather.POINTS,data)}
    monkeypatch.setattr(weather,'fetch_provider',fetch)
    monkeypatch.setattr(weather,'utcnow',lambda:next(clock))
    raw=weather.WeatherService().snapshot()
    assert raw['starts_at'].startswith('2026-11-12T16:00:00')
    assert raw['fetched_at'].startswith('2026-11-12T17:00:03')
    assert raw['points'][0]['availability']['wind']['available_hours']==72


def test_outside_horizon_and_http_errors_are_diagnosable(monkeypatch):
    def fetch(kind):
        if kind=='wave':raise httpx.HTTPStatusError('rate limited',request=httpx.Request('GET','https://marine-api.open-meteo.com'),response=httpx.Response(429))
        future=weather.utcnow()+timedelta(days=10)
        data=payload(kind,future.replace(minute=0,second=0,microsecond=0))
        return {p['id']:dict(zip(part['hourly']['time'],part['hourly']['wind_speed_10m'])) for p,part in zip(weather.POINTS,data)}
    monkeypatch.setattr(weather,'fetch_provider',fetch)
    raw=weather.WeatherService().snapshot();north=raw['points'][0]
    assert north['availability']['wind']['status']=='outside_horizon'
    assert north['availability']['wave']['http_status']==429
    assert '429' in raw['errors'][0]['message']
    assert all(h['wind'] is None and h['wave'] is None for h in north['hourly'])


@pytest.mark.parametrize('field',['hourly_units','hourly'])
def test_null_object_affects_only_its_location(monkeypatch,field):
    data=payload('wind');data[0][field]=None
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    parsed=weather.fetch_provider('wind')
    assert parsed['direct-north']=={}
    assert len(parsed['direct-mid'])==72
    assert parsed.diagnostics['direct-north']['status']=='invalid_response'
