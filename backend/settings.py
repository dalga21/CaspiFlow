"""Validated operator thresholds, demonstration tariffs and decision weights."""
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    wind_warning:float=Field(12,gt=0,le=60)
    wind_danger:float=Field(20,gt=0,le=80)
    wave_warning:float=Field(2,gt=0,le=15)
    wave_danger:float=Field(3.5,gt=0,le=20)
    delay_usd_per_hour:float=Field(150,ge=0,le=1000000)
    sea_usd_per_tkm:float=Field(.02,ge=0,le=100)
    rail_usd_per_tkm:float=Field(.035,ge=0,le=100)
    road_usd_per_tkm:float=Field(.08,ge=0,le=100)
    transfer_usd:float=Field(75,ge=0,le=1000000)
    eta_weight:float=Field(.45,ge=0,le=1)
    cost_weight:float=Field(.4,ge=0,le=1)
    co2_weight:float=Field(.15,ge=0,le=1)
    @model_validator(mode='after')
    def consistency(self):
        if self.wind_warning>=self.wind_danger or self.wave_warning>=self.wave_danger:
            raise ValueError('Порог предупреждения должен быть ниже опасного')
        if self.eta_weight+self.cost_weight+self.co2_weight<=0:
            raise ValueError('Хотя бы один вес рекомендации должен быть положительным')
        if abs(self.eta_weight+self.cost_weight+self.co2_weight-1)>1e-6:
            raise ValueError('Сумма весов времени, стоимости и CO₂ должна быть 1')
        return self

def load_settings(db):
    with db() as c: row=c.execute("SELECT value FROM settings WHERE key='operator'").fetchone()
    return Settings.model_validate_json(row[0]) if row else Settings()

def initialize_settings(db):
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admin_sessions(token_hash TEXT PRIMARY KEY,expires_at REAL NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admin_attempts(id INTEGER PRIMARY KEY,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,action TEXT NOT NULL,subject TEXT NOT NULL,details TEXT NOT NULL);''')
        c.execute("INSERT OR IGNORE INTO settings VALUES ('operator',?)",(Settings().model_dump_json(),))

def economics(route,weight,delay,settings):
    transport=sum(s['km']*weight*getattr(settings,f"{s['mode']}_usd_per_tkm") for s in route['segments'])+route['transfers']*settings.transfer_usd
    transport=round(transport,2)
    waiting=None if delay is None else round(delay*settings.delay_usd_per_hour,2)
    return {'currency':'USD','tariffs_demonstration':True,'transport_usd':round(transport,2),
            'delay_cost_usd':waiting,'total_cost_usd':None if waiting is None else round(transport+waiting,2)}

def recommend(routes,current_id,settings):
    current=next(r for r in routes if r['id']==current_id)
    valid=[r for r in routes if r['delay_hours'] is not None]
    for r in routes:
        r['economics']['additional_transport_usd']=round(r['economics']['transport_usd']-current['economics']['transport_usd'],2)
        r['economics']['potential_savings_usd']=None
    if not valid:return {'route_id':None,'conditional':True,'reason':'Нет полных прогнозов для сравнения','scores':[]}
    values={'eta':lambda r:r['total_hours'],'cost':lambda r:r['economics']['total_cost_usd'],'co2':lambda r:r['co2_kg']}
    spans={k:(min(f(r) for r in valid),max(f(r) for r in valid)) for k,f in values.items()}
    weights={k:getattr(settings,k+'_weight') for k in values}; total=sum(weights.values())
    scored=[]
    for r in valid:
        normalized={k:0 if spans[k][1]==spans[k][0] else (f(r)-spans[k][0])/(spans[k][1]-spans[k][0]) for k,f in values.items()}
        score=sum(normalized[k]*weights[k] for k in values)/total
        scored.append({'route_id':r['id'],'score':round(score,6),'normalized':normalized})
        r['economics']['additional_transport_usd']=round(r['economics']['transport_usd']-current['economics']['transport_usd'],2)
        base=current['economics']['total_cost_usd']; candidate=r['economics']['total_cost_usd']
        r['economics']['potential_savings_usd']=None if base is None else round(base-candidate,2)
    # Even unavailable candidates have known transport tariffs.
    for r in routes:
        r['economics'].setdefault('additional_transport_usd',round(r['economics']['transport_usd']-current['economics']['transport_usd'],2))
        r['economics'].setdefault('potential_savings_usd',None)
    best=min(scored,key=lambda r:(r['score'],r['route_id']))
    partial=len(valid)!=len(routes)
    outside=any(r.get('prediction',{}).get('outside_training_range') for r in valid)
    land_unvalidated=any(r.get('prediction',{}).get('validation_scope')=='unvalidated_land' for r in valid)
    return {'route_id':best['route_id'],'conditional':partial or outside or land_unvalidated,'weights':weights,'scores':scored,
            'excluded_routes':[r['id'] for r in routes if r['delay_hours'] is None],
            'reason':('Условный выбор: часть маршрутов без полного прогноза. ' if partial else '')+('Есть признаки вне диапазона обучения; надёжность сравнения не подтверждена. ' if outside else '')+
                     ('Сухопутный прогноз отдельно не валидирован. ' if land_unvalidated else '')+
                     'Минимум взвешенного нормированного времени, стоимости и CO₂ среди доступных вариантов. Меньший балл лучше; тарифы демонстрационные.'}
