import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'caspiflow.sqlite'
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
 conn = sqlite3.connect(DB)
 conn.row_factory = sqlite3.Row
 try:
  yield conn
  conn.commit()
 finally: conn.close()

def initialize():
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
 global model, metrics, residual
 with db() as c: rows=c.execute('SELECT features,delay FROM history ORDER BY id').fetchall()
 x=np.array([json.loads(r['features']) for r in rows]); y=np.array([r['delay'] for r in rows])
 xt,xv,yt,yv=train_test_split(x,y,test_size=.2,random_state=42)
 model=RandomForestRegressor(n_estimators=100,max_depth=12,min_samples_leaf=3,random_state=42,n_jobs=1)
 model.fit(xt,yt); pred=model.predict(xv); residual=float(np.quantile(np.abs(yv-pred),.9))
 metrics={'name':'Random Forest','train_samples':len(xt),'test_samples':len(xv),'mae_hours':round(mean_absolute_error(yv,pred),2),'residual_p90_hours':round(residual,2),'features':['wind_m_s','wave_m','port_load_percent','historical_delay_hours','distance_km','transfers'],'synthetic':True,'seed':42,'limitation':'Обучено и проверено только на синтетике. Интервал ±p90 ошибки на синтетической тестовой выборке не гарантирует точность на реальных рейсах.'}

@asynccontextmanager
async def lifespan(app):
 if not os.environ.get('CUSTOMS_API_KEY'): raise RuntimeError('Set CUSTOMS_API_KEY before startup')
 initialize();train();yield

app=FastAPI(title='CaspiFlow Demo API',version='0.1.0',lifespan=lifespan)
key_header=APIKeyHeader(name='X-API-Key',auto_error=False)
def authorize(key: str|None=Depends(key_header)):
 if not key or not secrets.compare_digest(key,os.environ['CUSTOMS_API_KEY']): raise HTTPException(401,'Invalid API key')

def route_view(route,weight,storm):
 exposure=route['exposure']; wind=7+storm*.24*exposure; wave=.6+storm*.045*exposure
 load=min(99,route['load']+storm*.15*exposure)
 features=[wind,wave,load,route['history'],sum(s['km'] for s in route['segments']),route['transfers']]
 delay=round(float(model.predict([features])[0]),1)
 co2=round(sum(s['km']*FACTORS[s['mode']]*weight for s in route['segments']))
 return {**route,'delay_hours':delay,'total_hours':round(route['hours']+delay,1),'co2_kg':co2,'wind':round(wind,1),'wave':round(wave,1),'load':round(load),'interval':[round(max(0,delay-residual),1),round(delay+residual,1)]}

def shipment_view(item,storm):
 routes=[route_view(r,item['weight'],storm) for r in ROUTES]
 current=next(r for r in routes if r['id']==item['route_id'])
 with db() as c: declaration=c.execute('SELECT id,digest,created_at FROM customs WHERE shipment_id=?',(item['id'],)).fetchone()
 return {**item,'route':current,'alternatives':routes,'customs':dict(declaration) if declaration else None}

@app.get('/health')
def health():return {'status':'ok','data':'synthetic'}
@app.get('/model')
def model_info():return metrics
@app.get('/dashboard')
def dashboard(storm: int=Query(0,ge=0,le=100)):
 with db() as c: items=[json.loads(r[0]) for r in c.execute('SELECT data FROM shipments ORDER BY id')]; ports=[json.loads(r[0]) for r in c.execute('SELECT data FROM ports')]
 return {'shipments':[shipment_view(s,storm) for s in items],'ports':ports,'model':metrics,'storm':storm,'data_source':'Синтетические демонстрационные данные','as_of':datetime.now(timezone.utc).isoformat()}
@app.get('/shipments/{shipment_id}')
def shipment(shipment_id:str,storm:int=Query(0,ge=0,le=100)):
 with db() as c: row=c.execute('SELECT data FROM shipments WHERE id=?',(shipment_id,)).fetchone()
 if not row: raise HTTPException(404,'Груз не найден')
 return shipment_view(json.loads(row[0]),storm)

class Declaration(BaseModel):
 shipment_id:str=Field(pattern=r'^CF-2026-\d{4}$')
 hs_code:str=Field(pattern=r'^\d{10}$')
 invoice_number:str=Field(min_length=3,max_length=60,pattern=r'^[A-Za-zА-Яа-я0-9 /_-]+$')
 declared_value:float=Field(gt=0,le=1_000_000_000,allow_inf_nan=False)
 country:str=Field(pattern=r'^(IR|RU|AZ|KZ|TM)$')

@app.post('/customs',dependencies=[Depends(authorize)])
def customs(data:Declaration):
 with db() as c:
  if not c.execute('SELECT 1 FROM shipments WHERE id=?',(data.shipment_id,)).fetchone():raise HTTPException(404,'Груз не найден')
  old=c.execute('SELECT * FROM customs WHERE shipment_id=?',(data.shipment_id,)).fetchone()
  payload=json.dumps(data.model_dump(),sort_keys=True,ensure_ascii=False); digest=hashlib.sha256(payload.encode()).hexdigest()
  if old:
   if old['digest']!=digest:raise HTTPException(409,'Заявка уже существует с другими данными')
   return {'id':old['id'],'status':'Демо-проверка пройдена','digest':old['digest'],'duplicate':True}
  id='DEMO-'+secrets.token_hex(5).upper()
  c.execute('INSERT INTO customs VALUES (?,?,?,?,?)',(id,data.shipment_id,payload,digest,datetime.now(timezone.utc).isoformat()))
 return {'id':id,'status':'Демо-проверка пройдена','digest':digest,'duplicate':False,'notice':'Не является таможенным оформлением'}
