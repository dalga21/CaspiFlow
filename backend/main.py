import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from backend.ml import FEATURES, fit_model
from backend.settings import Settings,initialize_settings,load_settings,economics,recommend
from backend.weather import WeatherService,enrich_snapshot,passage
from backend.admin import register_admin
from backend.reports import snapshot_id,render_report

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('CASPIFLOW_DB_PATH', str(ROOT / 'caspiflow.sqlite'))).resolve()
PORTS = [
 {'id':'astrakhan','name':'Астрахань','country':'Россия','lat':46.35,'lon':48.04,'load':72},
 {'id':'makhachkala','name':'Махачкала','country':'Россия','lat':42.98,'lon':47.50,'load':58},
 {'id':'aktau','name':'Актау','country':'Казахстан','lat':43.65,'lon':51.16,'load':64},
 {'id':'baku','name':'Баку','country':'Азербайджан','lat':40.37,'lon':49.85,'load':81},
 {'id':'anzali','name':'Энзели','country':'Иран','lat':37.47,'lon':49.46,'load':69},
 {'id':'amirabad','name':'Амирабад','country':'Иран','lat':36.85,'lon':53.37,'load':54},
 {'id':'turkmenbashi','name':'Туркменбаши','country':'Туркменистан','lat':40.02,'lon':52.97,'load':47},
]
ROUTES = [
 {'id':'direct','name':'Прямой каспийский','ports':['astrakhan','anzali'],'segments':[{'mode':'rail','km':280},{'mode':'sea','km':1060},{'mode':'road','km':45}],'hours':58,'transfers':2,'load':72,'history':8,'exposure':1},
 {'id':'west','name':'Западный сухопутный','ports':['astrakhan','makhachkala','baku','anzali'],'segments':[{'mode':'rail','km':690},{'mode':'road','km':940}],'hours':72,'transfers':3,'load':81,'history':11,'exposure':0.08},
 {'id':'east','name':'Через Актау и Амирабад','ports':['astrakhan','aktau','amirabad','anzali'],'segments':[{'mode':'rail','km':720},{'mode':'sea','km':900},{'mode':'road','km':310}],'hours':83,'transfers':3,'load':64,'history':7,'exposure':0.7},
]
FACTORS = {'sea':0.016,'rail':0.022,'road':0.085}

@contextmanager
def db():
 conn = sqlite3.connect(DB, timeout=15)
 conn.row_factory = sqlite3.Row
 try:
  yield conn
  conn.commit()
 finally: conn.close()

def initialize():
 initialize_settings(db)
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS ports(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,features TEXT NOT NULL,delay REAL NOT NULL);
CREATE TABLE IF NOT EXISTS customs(id TEXT PRIMARY KEY,shipment_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,created_at TEXT NOT NULL);''')
  if not c.execute('SELECT COUNT(*) FROM ports').fetchone()[0]:
   c.executemany('INSERT INTO ports VALUES (?,?)',[(p['id'],json.dumps(p)) for p in PORTS])
  if not c.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]:
   cargo = [('CF-2026-0841','Промышленное оборудование',24.8,'Волга Трейд','direct',0.43),('CF-2026-0842','Зерно · 4 контейнера',82.0,'АгроЭкспорт','east',0.62),('CF-2026-0843','Текстиль и ткани',18.6,'Caspian Textile','west',0.28),('CF-2026-0844','Комплектующие',32.4,'Север Логистик','direct',0.76)]
   for id,name,weight,owner,route,progress in cargo:
    item=dict(id=id,name=name,weight=weight,owner=owner,route_id=route,progress=progress,container='CSPU '+id[-4:]+' 6',updated_at=datetime.now(timezone.utc).isoformat())
    c.execute('INSERT INTO shipments VALUES (?,?)',(id,json.dumps(item)))
  if not c.execute('SELECT COUNT(*) FROM history').fetchone()[0]:
   rng=np.random.default_rng(42)
   for i in range(2400):
    wind=rng.uniform(3,33); wave=rng.uniform(.3,5.5); load=rng.uniform(30,99); hist=rng.uniform(2,16); distance=rng.uniform(800,2300); transfers=int(rng.integers(1,5))
    x=[wind,wave,load,hist,distance,transfers]
    y=max(0,.42*wind+1.9*wave+.17*max(load-55,0)+.4*hist+.001*distance+1.5*transfers+max(wind-18,0)*.65+rng.normal(0,2))
    c.execute('INSERT INTO history VALUES (?,?,?)',(i,json.dumps(x),float(y)))

def train():
 global model, metrics, residual, bundle
 with db() as c: rows=c.execute('SELECT features,delay FROM history ORDER BY id').fetchall()
 bundle=fit_model(rows)
 model=bundle.estimator; metrics=bundle.metrics; residual=bundle.radius

@asynccontextmanager
async def lifespan(app):
 if not os.environ.get('CUSTOMS_API_KEY'): raise RuntimeError('Set CUSTOMS_API_KEY before startup')
 global weather_service
 initialize();train();weather_service=WeatherService()
 with db() as c:c.execute('DELETE FROM admin_sessions')
 yield

app=FastAPI(title='CaspiFlow Demo API',version='0.1.0',lifespan=lifespan)
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
 return JSONResponse(status_code=422,content={'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]})

key_header=APIKeyHeader(name='X-API-Key',auto_error=False)
def authorize(key: str|None=Depends(key_header)):
 if not key or not secrets.compare_digest(key,os.environ['CUSTOMS_API_KEY']): raise HTTPException(401,'Invalid API key')

def prediction_scope(route):
 modes=list(dict.fromkeys(s['mode'] for s in route['segments']))
 land='sea' not in modes
 return {'transport_modes':modes,'validation_scope':'unvalidated_land' if land else 'synthetic_only',
         'limitation':('Сухопутный прогноз отдельно не валидирован. Тип транспорта не входит в признаки модели; '
                       'волны 0 означают отсутствие моря и выходят за диапазон обучения. Это ориентировочная оценка, не подтверждённый ETA.') if land else None}

def route_view(route,weight,storm,port_load=None,departure_at=None,settings=None):
 if settings is None:settings=load_settings(db)
 exposure=route['exposure']; wind=7+storm*.24*exposure
 has_sea=any(s['mode']=='sea' for s in route['segments'])
 wave=.6+storm*.045*exposure if has_sea else 0
 base_load=route['load'] if port_load is None else port_load
 load=min(99,base_load+storm*.15*exposure)
 features=[wind,wave,load,route['history'],sum(s['km'] for s in route['segments']),route['transfers']]
 baseline_features=[7,.6 if has_sea else 0,base_load,*features[3:]]
 # Both before and after come from the trained estimator, never a hand-written delay formula.
 predicted=model.predict([features,baseline_features])
 delay=round(float(predicted[0]),1); base_delay=round(float(predicted[1]),1)
 total=round(route['hours']+delay,1); base_total=round(route['hours']+base_delay,1)
 co2=round(sum(s['km']*FACTORS[s['mode']]*weight for s in route['segments']))
 departure=datetime.fromisoformat(departure_at) if departure_at else datetime.now(timezone.utc)
 outside=[FEATURES[i][0] for i,v in enumerate(features) if v<bundle.bounds[0,i] or v>bundle.bounds[1,i]]
 return {**route,'economics':economics(route,weight,delay,settings),'delay_hours':delay,'total_hours':total,'co2_kg':co2,
  'wind':round(wind,2),'wave':round(wave,2),'load':round(load,1),
  'interval':[round(max(0,delay-residual),1),round(delay+residual,1)],
  'baseline':{'delay_hours':base_delay,'total_hours':base_total,
              'eta_at':(departure+timedelta(hours=base_total)).isoformat()},
  'delay_change_hours':round(delay-base_delay,1),
  'eta_at':(departure+timedelta(hours=total)).isoformat(),
  'risk_level':'high' if storm*exposure>=60 else 'elevated' if storm*exposure>=25 else 'low',
  'hazard_legs':([['astrakhan','anzali']] if route['id']=='direct' else [['aktau','amirabad']] if route['id']=='east' else []) if storm*exposure>=25 else [],
  'prediction':{'model_version':metrics['version'],'source':'RandomForestRegressor.predict',
                'inputs':dict(zip(metrics['features'],features)), 'outside_training_range':outside,**prediction_scope(route)}}

def manual_context(storm,port_load,settings):
 return {'mode':'manual','storm':storm,'port_load':port_load,'settings':settings.model_dump(),
         'model_version':metrics['version'],'emission_factors':FACTORS}

def auto_context(weather,settings):
 return {'mode':'auto','settings':settings.model_dump(),'model_version':metrics['version'],'emission_factors':FACTORS,
         'weather':{'starts_at':weather['starts_at'],'fetched_at':weather['fetched_at'],'errors':weather['errors'],
                    'spatial_notes':[p['name']+': '+p['availability']['wave']['spatial_note'] for p in weather['points'] if p.get('availability',{}).get('wave',{}).get('spatial_note')]}}

def shipment_view(item,storm,port_load=None,settings=None):
 if settings is None:settings=load_settings(db)
 # Fixed snapshot anchor: storm changes ETA, not departure or stored cargo position.
 departure=datetime.fromisoformat(item['updated_at'])-timedelta(hours=next(r for r in ROUTES if r['id']==item['route_id'])['hours']*item['progress'])
 routes=[route_view(r,item['weight'],storm,port_load,departure.isoformat(),settings=settings) for r in ROUTES]
 current=next(r for r in routes if r['id']==item['route_id'])
 with db() as c: declaration=c.execute('SELECT id,digest,created_at FROM customs WHERE shipment_id=?',(item['id'],)).fetchone()
 decision=recommend(routes,item['route_id'],settings)
 result={**item,'status':item.get('status','in_transit'),'recommendation':decision,'departed_at':departure.isoformat(),'route':current,'alternatives':routes,'customs':dict(declaration) if declaration else None}
 result['report_snapshot']=snapshot_id(result,manual_context(storm,port_load,settings))
 return result

@app.get('/health')
def health():return {'status':'ok','data':'synthetic'}
@app.get('/model')
def model_info():return metrics
@app.get('/dashboard')
def dashboard(storm: int=Query(0,ge=0,le=100),port_load: int|None=Query(None,ge=30,le=99)):
 settings=load_settings(db)
 with db() as c: items=[json.loads(r[0]) for r in c.execute('SELECT data FROM shipments ORDER BY id')]; ports=[json.loads(r[0]) for r in c.execute('SELECT data FROM ports')]
 return {'shipments':[shipment_view(s,storm,port_load,settings=settings) for s in items],'ports':ports,'model':metrics,'settings':settings.model_dump(),'storm':storm,'port_load':port_load,'data_source':'Синтетические демонстрационные данные','as_of':datetime.now(timezone.utc).isoformat()}
@app.get('/shipments/{shipment_id}')
def shipment(shipment_id:str,storm:int=Query(0,ge=0,le=100),port_load:int|None=Query(None,ge=30,le=99)):
 with db() as c: row=c.execute('SELECT data FROM shipments WHERE id=?',(shipment_id,)).fetchone()
 if not row: raise HTTPException(404,'Груз не найден')
 return shipment_view(json.loads(row[0]),storm,port_load)

class Declaration(BaseModel):
 model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
 shipment_id:str=Field(pattern=r'^CF-2026-[0-9]{4}$')
 hs_code:str=Field(pattern=r'^[0-9]{10}$')
 invoice_number:str=Field(min_length=3,max_length=60,pattern=r'^[A-Za-zА-Яа-я0-9 /_-]+$')
 declared_value:float=Field(gt=0,le=1_000_000_000,allow_inf_nan=False)
 country:str=Field(pattern=r'^(IR|RU|AZ|KZ|TM)$')

@app.post('/customs',dependencies=[Depends(authorize)])
def customs(data:Declaration):
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  if not c.execute('SELECT 1 FROM shipments WHERE id=?',(data.shipment_id,)).fetchone():raise HTTPException(404,'Груз не найден')
  old=c.execute('SELECT * FROM customs WHERE shipment_id=?',(data.shipment_id,)).fetchone()
  payload=json.dumps(data.model_dump(),sort_keys=True,ensure_ascii=False); digest=hashlib.sha256(payload.encode()).hexdigest()
  if old:
   if old['digest']!=digest:raise HTTPException(409,'Заявка уже существует с другими данными')
   return {'id':old['id'],'status':'Демо-проверка пройдена','digest':old['digest'],'duplicate':True}
  id='DEMO-'+secrets.token_hex(5).upper()
  c.execute('INSERT INTO customs VALUES (?,?,?,?,?)',(id,data.shipment_id,payload,digest,datetime.now(timezone.utc).isoformat()))
 return {'id':id,'status':'Демо-проверка пройдена','digest':digest,'duplicate':False,'notice':'Не является таможенным оформлением'}


register_admin(app,db,authorize)

@app.get('/forecast')
def forecast(retry:bool=Query(False)):
 settings=load_settings(db)
 weather=enrich_snapshot(weather_service.snapshot(retry=retry),settings)
 passages={r['id']:passage(r,weather,settings) for r in ROUTES}
 with db() as c:
  items=[json.loads(r[0]) for r in c.execute('SELECT data FROM shipments ORDER BY id')]
  ports=[json.loads(r[0]) for r in c.execute('SELECT data FROM ports')]
 shipments=[]
 for item in items:
  alternatives=[]
  for r in ROUTES:
   leg=passages[r['id']];delay=None;inputs=None;outside=[]
   if leg['complete']:
    inputs=[leg['wind'],leg['wave'],r['load'],r['history'],sum(s['km'] for s in r['segments']),r['transfers']]
    delay=round(float(model.predict([inputs])[0]),1)
    outside=[FEATURES[i][0] for i,v in enumerate(inputs) if v<bundle.bounds[0,i] or v>bundle.bounds[1,i]]
   total=None if delay is None else round(r['hours']+delay,1)
   co2=round(sum(s['km']*FACTORS[s['mode']]*item['weight'] for s in r['segments']))
   alternatives.append({**r,'co2_kg':co2,'delay_hours':delay,'total_hours':total,
    'eta_at':None if total is None else (datetime.fromisoformat(weather['starts_at'])+timedelta(hours=total)).isoformat(),
    'prediction':{'source':'RandomForestRegressor.predict' if delay is not None else 'unavailable','model_version':metrics['version'],
                  'inputs':None if inputs is None else dict(zip(metrics['features'],inputs)),'outside_training_range':outside,**prediction_scope(r)},
    'passage':leg,'economics':economics(r,item['weight'],delay,settings)})
  decision=recommend(alternatives,item['route_id'],settings)
  shipment={**item,'status':item.get('status','in_transit'),'alternatives':alternatives,'recommendation':decision}
  shipment['report_snapshot']=snapshot_id(shipment,auto_context(weather,settings))
  shipments.append(shipment)
 return {'mode':'auto','weather':weather,'shipments':shipments,'ports':ports,'settings':settings.model_dump(),
         'alerts':[a for leg in passages.values() for a in leg['alerts']],'model_version':metrics['version'],
         'data_notice':'Погода — модельный прогноз Open-Meteo; грузы и геометрия демонстрационные. Новый план отправления в текущий час, без фактического перенаправления.'}

@app.get('/reports/{shipment_id}',dependencies=[Depends(authorize)])
def report(shipment_id:str,mode:Literal['manual','auto']=Query('manual'),storm:int=Query(0,ge=0,le=100),
           port_load:int|None=Query(None,ge=30,le=99),expected_snapshot:str=Query(pattern=r'^[a-f0-9]{64}$')):
 if mode=='auto':
  if storm or port_load is not None:raise HTTPException(422,'Ручные параметры неприменимы к автопрогнозу')
  data=forecast(retry=False);shipment=next((s for s in data['shipments'] if s['id']==shipment_id),None)
  if shipment is None:raise HTTPException(404,'Груз не найден')
  context=auto_context(data['weather'],Settings.model_validate(data['settings']))
 else:
  with db() as c:row=c.execute('SELECT data FROM shipments WHERE id=?',(shipment_id,)).fetchone()
  if not row:raise HTTPException(404,'Груз не найден')
  settings=load_settings(db);shipment=shipment_view(json.loads(row[0]),storm,port_load,settings=settings)
  context=manual_context(storm,port_load,settings)
 if shipment['report_snapshot']!=expected_snapshot or snapshot_id(shipment,context)!=expected_snapshot:
  raise HTTPException(409,'Данные расчёта изменились. Обновите расчёт и сформируйте отчёт повторно.')
 pdf=render_report(shipment,context,metrics)
 return Response(pdf,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="CaspiFlow-{shipment_id}-{mode}.pdf"',
     'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
