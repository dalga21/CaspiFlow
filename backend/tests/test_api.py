import os
import pytest
from fastapi.testclient import TestClient
from backend import main

@pytest.fixture()
def client(tmp_path,monkeypatch):
 monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite')
 monkeypatch.setenv('CUSTOMS_API_KEY','test-private-key')
 with TestClient(main.app) as c:yield c

def test_scenario_and_routes(client):
 base=client.get('/dashboard').json();storm=client.get('/dashboard?storm=100').json()
 assert len(base['shipments'])==4 and len(base['ports'])==7
 a=base['shipments'][0];b=storm['shipments'][0]
 assert b['route']['delay_hours']>a['route']['delay_hours']
 assert min(b['alternatives'],key=lambda r:r['total_hours'])['id']=='west'
 assert a['route']['co2_kg']==round(24.8*(280*.022+1060*.016+45*.085))
 assert client.get('/dashboard?storm=101').status_code==422
 assert client.get('/shipments/missing').status_code==404
 assert base['model']['mae_hours']<5
 assert base['model']['train_samples']==1440 and base['model']['test_samples']==480

def test_customs_security_validation_idempotency(client):
 payload={'shipment_id':'CF-2026-0841','hs_code':'8471300000','invoice_number':'INV-TEST','declared_value':48000,'country':'IR'}
 assert client.post('/customs',json=payload).status_code==401
 headers={'X-API-Key':'test-private-key'}
 assert client.post('/customs',headers=headers,json={**payload,'hs_code':'abc'}).status_code==422
 first=client.post('/customs',headers=headers,json=payload)
 assert first.status_code==200
 second=client.post('/customs',headers=headers,json=payload).json()
 assert second['duplicate'] and second['id']==first.json()['id']
 assert len(second['digest'])==64
 assert client.post('/customs',headers=headers,json={**payload,'declared_value':1}).status_code==409
 assert client.get('/shipments/CF-2026-0841').json()['customs']['id']==second['id']


def test_metrics_and_explanation_are_measured(client):
 import numpy as np
 from sklearn.model_selection import train_test_split
 from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score
 import json
 with main.db() as c:
  rows=c.execute('SELECT features,delay FROM history ORDER BY id').fetchall()
 x=np.array([json.loads(r['features']) for r in rows]); y=np.array([r['delay'] for r in rows])
 train_cal,test=train_test_split(np.arange(len(y)),test_size=.2,random_state=42)
 train,cal=train_test_split(train_cal,test_size=.25,random_state=43)
 assert not set(train)&set(test) and not set(cal)&set(test) and not set(train)&set(cal)
 m=client.get('/model').json(); pred=main.model.predict(x[test])
 assert m['mae_hours']==round(float(mean_absolute_error(y[test],pred)),4)
 assert m['rmse_hours']==round(float(root_mean_squared_error(y[test],pred)),4)
 assert m['r2']==round(float(r2_score(y[test],pred)),4)
 assert m['mae_hours']<m['baseline_mae_hours']
 assert m['cross_split_overlap']==0 and m['duplicate_feature_rows']==0
 assert m['calibration_samples']==480
 assert m['explanation']['method']=='permutation_importance'
 assert m['explanation']['scope']=='global held-out test'
 assert len(m['explanation']['factors'])==6
 assert m['explanation']['factors'][0]['key']=='wind_m_s'
 expected_coverage=np.mean(np.abs(y[test]-pred)<=main.residual)
 assert m['test_interval_coverage']==round(float(expected_coverage),4)


def test_real_model_calls_eta_hazards_and_reset(client,monkeypatch):
 from datetime import datetime
 calls=[]
 original=main.model.predict
 def spy(values):
  calls.extend(values)
  return original(values)
 monkeypatch.setattr(main.model,'predict',spy)
 base=client.get('/shipments/CF-2026-0841').json()
 storm=client.get('/shipments/CF-2026-0841?storm=100').json()
 reset=client.get('/shipments/CF-2026-0841?storm=0').json()
 assert len(calls)==18  # three routes, current and baseline; three API requests
 assert base['route']==reset['route']
 assert storm['route']['prediction']['inputs']['wind_m_s']==31
 assert storm['route']['prediction']['source']=='RandomForestRegressor.predict'
 assert storm['route']['hazard_legs']==[['astrakhan','anzali']]
 assert not storm['alternatives'][1]['hazard_legs']
 assert storm['route']['baseline']['delay_hours']==base['route']['delay_hours']
 change=(datetime.fromisoformat(storm['route']['eta_at'])-datetime.fromisoformat(base['route']['eta_at'])).total_seconds()/3600
 assert change==pytest.approx(storm['route']['delay_change_hours'])
 assert storm['departed_at']==base['departed_at']
 assert storm['route']['co2_kg']==base['route']['co2_kg']
 assert min(storm['alternatives'],key=lambda r:r['total_hours'])['id']=='west'


def test_weather_load_and_routes_affect_predictions(client):
 import numpy as np
 # Sweep the entire supported storm slider rather than just the endpoints.
 for route in main.ROUTES:
  delays=[main.route_view(route,24.8,storm)['delay_hours'] for storm in range(0,101,5)]
  assert np.all(np.diff(delays)>=0)
 low=client.get('/dashboard?port_load=30').json()
 high=client.get('/dashboard?port_load=99').json()
 assert high['shipments'][0]['route']['delay_hours']>low['shipments'][0]['route']['delay_hours']
 assert len({r['delay_hours'] for r in low['shipments'][0]['alternatives']})>1
 assert client.get('/dashboard?port_load=100').status_code==422
 assert client.get('/dashboard?port_load=29').status_code==422
 for index in (0,1,2):
  x=[15,2,70,8,1385,2]; lo=x.copy(); hi=x.copy()
  lo[index]=[7,.6,30][index]; hi[index]=[31,5.1,99][index]
  assert main.model.predict([hi])[0]>=main.model.predict([lo])[0]


def test_customs_parallel_retries_and_storage(client):
 from concurrent.futures import ThreadPoolExecutor
 payload={'shipment_id':'CF-2026-0842','hs_code':'8471300000','invoice_number':'INV-CONCURRENT','declared_value':100,'country':'KZ'}
 headers={'X-API-Key':'test-private-key'}
 with ThreadPoolExecutor(max_workers=6) as pool:
  responses=list(pool.map(lambda _:client.post('/customs',headers=headers,json=payload),range(6)))
 assert all(r.status_code==200 for r in responses)
 ids={r.json()['id'] for r in responses}
 assert len(ids)==1
 assert sum(not r.json()['duplicate'] for r in responses)==1
 with main.db() as c:
  row=c.execute('SELECT * FROM customs WHERE shipment_id=?',(payload['shipment_id'],)).fetchone()
  assert row['id'] in ids
  assert 'INV-CONCURRENT' in row['payload']


@pytest.mark.parametrize('update',[
 {'hs_code':'８４７１３０００００'}, {'declared_value':-1}, {'declared_value':1e10},
 {'country':'XX'}, {'invoice_number':'   '}, {'extra_field':'unexpected'},
])
def test_customs_rejects_invalid_fields(client,update):
 payload={'shipment_id':'CF-2026-0841','hs_code':'8471300000','invoice_number':'INV-VALID','declared_value':48000,'country':'IR'}
 assert client.post('/customs',headers={'X-API-Key':'test-private-key'},json={**payload,**update}).status_code==422
