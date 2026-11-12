from backend import main,weather
from backend.settings import Settings,recommend
from backend.tests.test_operations import client,provider_fixture


def test_manual_land_has_no_marine_wave_input_and_is_explicitly_unvalidated(client,monkeypatch):
    seen=[];predict=main.model.predict
    def spy(x):seen.extend(x);return predict(x)
    monkeypatch.setattr(main.model,'predict',spy)
    for intensity in (0,100):
        data=client.get(f'/shipments/CF-2026-0841?storm={intensity}').json()
        land=next(r for r in data['alternatives'] if r['id']=='west')
        assert land['wave']==land['prediction']['inputs']['wave_m']==0
        assert land['prediction']['validation_scope']=='unvalidated_land'
        assert land['prediction']['transport_modes']==['rail','road']
        assert 'Тип транспорта не входит' in land['prediction']['limitation']
        assert 'wave_m' in land['prediction']['outside_training_range']
        assert data['recommendation']['conditional']
        assert 'Сухопутный прогноз отдельно не валидирован' in data['recommendation']['reason']
    # Three routes x current/baseline. Both land calls use zero, including baseline.
    assert len(seen)==12
    assert all(seen[i][1]==0 for i in (2,3,8,9))
    assert seen[6][1]>0  # storm marine route still uses the scenario wave
    assert 'transport_mode' not in main.metrics['features']


def test_auto_land_is_independent_of_marine_wave_and_shares_validation_scope(client,monkeypatch):
    forecasts=[]
    for wave in (1,4):
        monkeypatch.setattr(weather,'fetch_provider',lambda kind:provider_fixture(kind,wind=12,wave=wave))
        main.weather_service=weather.WeatherService()
        forecasts.append(client.get('/forecast').json()['shipments'][0])
    first,second=[next(r for r in s['alternatives'] if r['id']=='west') for s in forecasts]
    assert first['prediction']==second['prediction']
    assert first['delay_hours']==second['delay_hours']
    assert first['prediction']['validation_scope']=='unvalidated_land'
    assert first['prediction']['inputs']['wave_m']==0
    assert first['passage']['complete']  # coverage is separate from model validation
    direct=[next(r for r in s['alternatives'] if r['id']=='direct') for s in forecasts]
    assert direct[0]['delay_hours']!=direct[1]['delay_hours']
    assert direct[0]['prediction']['validation_scope']=='synthetic_only'


def test_land_comparison_remains_conditional_even_if_inputs_are_in_numeric_range():
    route={'id':'land','delay_hours':2,'total_hours':10,'co2_kg':100,
           'economics':{'transport_usd':100,'total_cost_usd':400},
           'prediction':{'outside_training_range':[],'validation_scope':'unvalidated_land'}}
    decision=recommend([route],'land',Settings())
    assert decision['route_id']=='land' and decision['conditional']
    assert 'Сухопутный прогноз отдельно не валидирован' in decision['reason']
