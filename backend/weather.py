"""Live Open-Meteo data. Missing values are never converted to synthetic weather."""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import httpx

POINTS=[
 {'id':'direct-north','name':'Северный Каспий','lat':44.1,'lon':48.4,'section':'direct'},
 {'id':'direct-mid','name':'Средний Каспий','lat':41.9,'lon':48.8,'section':'direct'},
 {'id':'direct-south','name':'Южный Каспий','lat':39.7,'lon':49.2,'section':'direct'},
 {'id':'east-north','name':'Южнее Актау','lat':42.5,'lon':51.5,'section':'east'},
 {'id':'east-mid','name':'Восточный Каспий','lat':40.2,'lon':52.2,'section':'east'},
 {'id':'east-south','name':'Подход к Амирабаду','lat':37.8,'lon':53.0,'section':'east'},
 {'id':'west-land','name':'Сухопутный узел Баку','lat':40.37,'lon':49.85,'section':'west'},
]
SOURCES={'wind':'https://api.open-meteo.com/v1/forecast','wave':'https://marine-api.open-meteo.com/v1/marine'}

def utcnow():return datetime.now(timezone.utc)

def number(value):
    return float(value) if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None

def fetch_provider(kind):
    points=POINTS if kind=='wind' else POINTS[:6]
    variable='wind_speed_10m' if kind=='wind' else 'wave_height'
    params={'latitude':','.join(str(p['lat']) for p in points),'longitude':','.join(str(p['lon']) for p in points),
            'hourly':variable,'forecast_hours':72,'timezone':'UTC','cell_selection':'nearest','timeformat':'unixtime'}
    if kind=='wind':params['wind_speed_unit']='ms'
    response=httpx.get(SOURCES[kind],params=params,timeout=httpx.Timeout(10,connect=4),follow_redirects=False)
    response.raise_for_status()
    data=response.json();parts=data if isinstance(data,list) else [data]
    if len(parts)!=len(points):raise ValueError('Unexpected number of forecast locations')
    result={}
    for point,part in zip(points,parts):
        expected_unit='m/s' if kind=='wind' else 'm'
        if part.get('hourly_units',{}).get(variable)!=expected_unit:raise ValueError('Unexpected forecast units')
        hourly=part.get('hourly',{}); times=hourly.get('time',[]);values=hourly.get(variable,[])
        if len(times)!=len(values):raise ValueError('Forecast times/values differ')
        result[point['id']]={int(t):number(v) for t,v in zip(times,values)}
    return result

class WeatherService:
    def __init__(self):self.cache=None;self.expires=0;self.lock=threading.Lock()
    def snapshot(self):
        with self.lock:
            if self.cache is not None and time.monotonic()<self.expires:return self.cache
            errors=[];values={}
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs={kind:pool.submit(fetch_provider,kind) for kind in SOURCES}
                for kind,job in jobs.items():
                    try:values[kind]=job.result()
                    except (httpx.HTTPError,ValueError,TypeError,KeyError) as exc:
                        values[kind]={}; errors.append({'source':kind,'message':f'Open-Meteo {kind}: данные недоступны ({type(exc).__name__})'})
            fetched=utcnow();start=fetched.replace(minute=0,second=0,microsecond=0)
            times=[start+timedelta(hours=i) for i in range(72)]
            points=[]
            for point in POINTS:
                hourly=[]
                for t in times:
                    stamp=int(t.timestamp())
                    hourly.append({'time':t.isoformat(),'wind':values['wind'].get(point['id'],{}).get(stamp),
                                   'wave':values['wave'].get(point['id'],{}).get(stamp) if point['section']!='west' else None})
                points.append({**point,'hourly':hourly})
            ttl=min(60 if errors else 900,max(1,(start+timedelta(hours=1)-fetched).total_seconds()))
            self.cache={'source':'Open-Meteo','fetched_at':fetched.isoformat(),'starts_at':start.isoformat(),
                        'expires_at':(fetched+timedelta(seconds=ttl)).isoformat(),'points':points,'errors':errors,
                        'attribution':'Weather data by Open-Meteo (CC BY 4.0); underlying model providers: see Open-Meteo documentation.',
                        'links':{'wind':'https://open-meteo.com/en/docs','wave':'https://open-meteo.com/en/docs/marine-weather-api'}}
            self.expires=time.monotonic()+ttl
            return self.cache

def risk(wind,wave,settings,sea=True):
    complete=wind is not None and (wave is not None or not sea)
    index=None if not complete else round(min(100,100*max(wind/settings.wind_danger,(wave or 0)/settings.wave_danger)),1)
    danger=(wind is not None and wind>=settings.wind_danger) or (wave is not None and wave>=settings.wave_danger)
    warning=(wind is not None and wind>=settings.wind_warning) or (wave is not None and wave>=settings.wave_warning)
    return {'risk_index':index,'severity':'danger' if danger else 'warning' if warning else 'low' if complete else 'unknown',
            'complete':complete}

def enrich_snapshot(raw,settings):
    return {**raw,'points':[{**p,'hourly':[{**h,**risk(h['wind'],h['wave'],settings,p['section']!='west')} for h in p['hourly']]} for p in raw['points']],
            'method':'Индекс = min(100, 100 × max(ветер / опасный порог ветра, волна / опасный порог волн)). Не вероятность. При пропуске обязательного поля индекс отсутствует. Известный опасный ветер всё равно вызывает предупреждение.',
            'thresholds':{k:getattr(settings,k) for k in ('wind_warning','wind_danger','wave_warning','wave_danger')}}

def passage(route,weather,settings):
    """Approximate new departure now. Durations proportional to schematic segment km."""
    start=datetime.fromisoformat(weather['starts_at']);distance=sum(s['km'] for s in route['segments'])
    sea_segment=next((s for s in route['segments'] if s['mode']=='sea'),None)
    points=[p for p in weather['points'] if p['section']==route['id']]
    if sea_segment:
        before=sum(s['km'] for s in route['segments'][:next(i for i,s in enumerate(route['segments']) if s['mode']=='sea')])
        begins=route['hours']*before/distance;duration=route['hours']*sea_segment['km']/distance
    else:begins=0;duration=route['hours']
    samples=[];alerts=[];encountered=[]
    for i,p in enumerate(points):
        offset=begins+duration*(i+.5)/len(points)
        at=start+timedelta(hours=offset)
        hour=next((h for h in p['hourly'] if datetime.fromisoformat(h['time'])<=at<datetime.fromisoformat(h['time'])+timedelta(hours=1)),None)
        samples.append({'point_id':p['id'],'name':p['name'],'passage_at':at.isoformat(),
                        'wind':None if hour is None else hour['wind'],
                        'wave':None if hour is None else hour['wave'] if sea_segment else 0,
                        'wave_applicability':'marine forecast' if sea_segment else 'no sea segment; zero is not a sea observation'})
        # Only weather during the planned passage through this third of the sea leg.
        left=start+timedelta(hours=begins+duration*i/len(points));right=start+timedelta(hours=begins+duration*(i+1)/len(points))
        window=[h for h in p['hourly'] if left<=datetime.fromisoformat(h['time'])+timedelta(hours=1) and datetime.fromisoformat(h['time'])<right]
        encountered.extend([{**h,'wave':h['wave'] if sea_segment else 0} for h in window])
        warnings=[h for h in window if h['severity'] in ('warning','danger')]
        if warnings:
            first=warnings[0];worst='danger' if any(h['severity']=='danger' for h in warnings) else 'warning'
            alerts.append({'id':f"{route['id']}:{p['id']}:{first['time']}",'route_id':route['id'],'point_id':p['id'],'section_name':p['name'],
                           'starts_at':first['time'],'ends_at':warnings[-1]['time'],'severity':worst,
                           'message':'Порог ветра/волн превышен в плановом окне прохождения.','source':'Open-Meteo'})
        if not window or right>datetime.fromisoformat(p['hourly'][-1]['time'])+timedelta(hours=1) or any(h['wind'] is None or (sea_segment and h['wave'] is None) for h in window):
            alerts.append({'id':f"gap:{route['id']}:{p['id']}",'route_id':route['id'],'point_id':p['id'],'section_name':p['name'],
                           'starts_at':left.isoformat(),'ends_at':right.isoformat(),'severity':'data_gap',
                           'message':'Неполное покрытие погодой в окне прохождения; безопасные условия не подтверждены.','source':'Open-Meteo'})
    complete=bool(samples) and all(s['wind'] is not None and s['wave'] is not None for s in samples)
    # Refuse full ML prediction if any required part of the passage window has a data gap.
    complete=complete and not any(a['severity']=='data_gap' for a in alerts)
    return {'samples':samples,'complete':complete,'alerts':alerts,
            'window_start':(start+timedelta(hours=begins)).isoformat(),'window_end':(start+timedelta(hours=begins+duration)).isoformat(),
            'wind':max((s['wind'] for s in encountered if s['wind'] is not None),default=None),
            'wave':max((s['wave'] for s in encountered if s['wave'] is not None),default=None),
            'timing_assumption':'Новый план отправления в текущий час UTC; часы сегментов пропорциональны км. Окна до ML-задержки, без расписаний и обратного пересчёта.'}
