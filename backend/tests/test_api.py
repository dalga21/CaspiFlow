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
 assert base['model']['train_samples']==1920 and base['model']['test_samples']==480

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
