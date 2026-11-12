import pytest
from backend import weather
from backend.tests.test_weather_partial import payload,response


def test_marine_prefers_sea_while_wind_keeps_nearest_cell(monkeypatch):
    calls=[]
    def get(url,params,**kw):
        kind='wave' if 'marine-api' in url else 'wind'
        calls.append((kind,params['cell_selection']))
        return response(payload(kind))
    monkeypatch.setattr(weather.httpx,'get',get)
    marine=weather.fetch_provider('wave');weather.fetch_provider('wind')
    assert calls==[('wave','sea'),('wind','nearest')]
    assert marine.diagnostics['direct-south']['cell_selection']=='sea'


def test_nearby_sea_cell_is_real_data_and_disclosed(monkeypatch):
    data=payload('wave')
    data[2]['latitude']=39.625;data[2]['longitude']=49.375015
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    result=weather.fetch_provider('wave');diagnostic=result.diagnostics['direct-south']
    assert len(result['direct-south'])==72
    assert diagnostic['grid_distance_km']==pytest.approx(17.13,abs=.1)
    assert diagnostic['grid_coordinates']=={'latitude':39.625,'longitude':49.375015}
    assert 'пространственное приближение' in diagnostic['spatial_note']
    assert diagnostic['requested_coordinates']=={'latitude':39.7,'longitude':49.2}


def test_remote_sea_grid_is_rejected_without_erasing_other_points(monkeypatch):
    data=payload('wave');data[2]['latitude']=40.7;data[2]['longitude']=50.2
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    result=weather.fetch_provider('wave')
    assert result['direct-south']=={}
    assert result.diagnostics['direct-south']['grid_distance_km']>25
    assert result.diagnostics['direct-south']['status']=='invalid_response'
    assert len(result['direct-north'])==72


def test_sea_selection_does_not_invent_values_when_provider_still_has_gaps(monkeypatch):
    data=payload('wave');data[2]['hourly']['wave_height']=[None]*72
    monkeypatch.setattr(weather.httpx,'get',lambda *a,**kw:response(data))
    result=weather.fetch_provider('wave')
    assert len(result['direct-south'])==72
    assert all(v is None for v in result['direct-south'].values())
