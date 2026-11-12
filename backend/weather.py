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

def timestamp(value):
    """UTC epoch seconds, or the documented ISO fallback when an upstream omits timeformat."""
    if isinstance(value,bool):raise ValueError('Invalid hourly time')
    if isinstance(value,(int,float)) and math.isfinite(value):
        if value!=int(value):raise ValueError('Non-integer hourly timestamp')
        result=int(value)
    elif isinstance(value,str):
        try:result=int(value)
        except ValueError:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
            result=int(parsed.timestamp())
    else:raise ValueError('Invalid hourly time')
    # Hourly UTC series must not be silently shifted or mistaken for milliseconds.
    if result%3600 or not 946684800<=result<=4102444800:raise ValueError('Invalid hourly UTC timestamp')
    return result

class ProviderData(dict):
    def __init__(self):
        super().__init__();self.diagnostics={}

class ProviderResponseError(ValueError):
    def __init__(self,message,status):
        super().__init__(message);self.http_status=status

def fetch_provider(kind):
    points=POINTS if kind=='wind' else POINTS[:6]
    variable='wind_speed_10m' if kind=='wind' else 'wave_height'
    expected_unit='m/s' if kind=='wind' else 'm'
    params={'latitude':','.join(str(p['lat']) for p in points),'longitude':','.join(str(p['lon']) for p in points),
            'hourly':variable,'forecast_hours':72,'timezone':'UTC','cell_selection':'nearest','timeformat':'unixtime'}
    if kind=='wind':params['wind_speed_unit']='ms'
    response=httpx.get(SOURCES[kind],params=params,timeout=httpx.Timeout(10,connect=4),follow_redirects=False)
    response.raise_for_status()
    data=response.json();parts=data if isinstance(data,list) else [data]
    if not all(isinstance(part,dict) for part in parts):raise ProviderResponseError('Invalid forecast locations',response.status_code)
    fetched=utcnow().isoformat();result=ProviderData();assigned={}
    # location_id takes priority. Coordinates recover shortened/reordered partial batches.
    for i,part in enumerate(parts):
        index=part.get('location_id')
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(points):
            lat=part.get('latitude');lon=part.get('longitude')
            if isinstance(lat,(int,float)) and isinstance(lon,(int,float)):
                index=min(range(len(points)),key=lambda j:(points[j]['lat']-lat)**2+(points[j]['lon']-lon)**2)
                if math.hypot(points[index]['lat']-lat,points[index]['lon']-lon)>.5:continue
            elif len(parts)==len(points):index=i
            else:continue
        if index in assigned:continue
        assigned[index]=part
    invalid=0
    for i,point in enumerate(points):
        part=assigned.get(i)
        diagnostic={'http_status':response.status_code,'field':variable,'expected_unit':expected_unit,
                    'fetched_at':fetched,'requested_coordinates':{'latitude':point['lat'],'longitude':point['lon']}}
        result[point['id']]={}
        try:
            if part is None:raise ValueError('В пакетном ответе отсутствует эта точка')
            diagnostic['grid_coordinates']={'latitude':part.get('latitude'),'longitude':part.get('longitude')}
            units=part.get('hourly_units');unit=units.get(variable) if isinstance(units,dict) else None;diagnostic['unit']=unit
            if unit!=expected_unit:raise ValueError('Несоответствие единиц (units): ожидались '+expected_unit)
            hourly=part.get('hourly')
            if not isinstance(hourly,dict):raise ValueError('Нет объекта hourly для этой точки')
            times=hourly.get('time');values=hourly.get(variable)
            if not isinstance(times,list) or not isinstance(values,list):raise ValueError('Нет массива hourly.time или hourly.'+variable)
            if not times:raise ValueError('Временной ряд пуст')
            series={};bad_times=0
            for j,t in enumerate(times):
                try:stamp=timestamp(t)
                except (ValueError,OverflowError):bad_times+=1;continue
                series[stamp]=number(values[j]) if j<len(values) else None
            if not series:raise ValueError('Не удалось распознать временные метки UTC')
            result[point['id']]=series
            diagnostic.update(response_hours=len(times),valid_response_hours=sum(v is not None for v in series.values()),
                provider_start=datetime.fromtimestamp(min(series),timezone.utc).isoformat(),
                provider_end=datetime.fromtimestamp(max(series),timezone.utc).isoformat())
            if len(times)!=len(values) or bad_times:
                diagnostic['parse_note']='Ответ частичный: длины времени/значений различаются или есть ошибочные метки; корректные часы сохранены'
        except (ValueError,TypeError,KeyError) as exc:
            invalid+=1;diagnostic.update(status='invalid_response',reason=str(exc))
        result.diagnostics[point['id']]=diagnostic
    # A single broken location must never erase the valid locations in the batch.
    if invalid==len(points):
        reason=next(iter(result.diagnostics.values()))['reason']
        raise ProviderResponseError(reason,response.status_code)
    return result

def source_error(kind,exc):
    status=getattr(exc,'http_status',None)
    if isinstance(exc,httpx.HTTPStatusError):status=exc.response.status_code
    if status==429:reason='Open-Meteo ограничил частоту запросов (HTTP 429)'
    elif status and status>=400:reason=f'Open-Meteo вернул HTTP {status}'
    elif isinstance(exc,httpx.TimeoutException):reason='Превышено время ожидания Open-Meteo'
    elif isinstance(exc,httpx.ConnectError):reason='Не удалось соединиться с Open-Meteo'
    else:reason='Не удалось разобрать ответ Open-Meteo: '+str(exc)
    return {'source':kind,'http_status':status,'error_type':type(exc).__name__,'message':reason}

class WeatherService:
    def __init__(self):
        self.cache=None;self.expires=0;self.lock=threading.Lock();self.last_retry=None
    def snapshot(self,retry=False):
        with self.lock:
            now=time.monotonic()
            if retry and self.last_retry is not None and now-self.last_retry<10 and self.cache is not None:
                return {**self.cache,'retry_after_seconds':max(1,math.ceil(10-(now-self.last_retry)))}
            if self.cache is not None and now<self.expires and not retry:return self.cache
            if retry:self.last_retry=now
            # Fix the forecast anchor BEFORE I/O. A response arriving after the hour
            # boundary must not silently change the requested window.
            requested=utcnow();start=requested.replace(minute=0,second=0,microsecond=0)
            errors=[];values={}
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs={kind:pool.submit(fetch_provider,kind) for kind in SOURCES}
                for kind,job in jobs.items():
                    try:values[kind]=job.result()
                    except (httpx.HTTPError,ValueError,TypeError,KeyError) as exc:
                        values[kind]={};errors.append(source_error(kind,exc))
            fetched=utcnow();times=[start+timedelta(hours=i) for i in range(72)];points=[]
            for point in POINTS:
                hourly=[]
                for t in times:
                    stamp=int(t.timestamp())
                    hourly.append({'time':t.isoformat(),'wind':values['wind'].get(point['id'],{}).get(stamp),
                                   'wave':values['wave'].get(point['id'],{}).get(stamp) if point['section']!='west' else None})
                availability={}
                for kind in SOURCES:
                    diagnostic=dict(getattr(values[kind],'diagnostics',{}).get(point['id'],{}))
                    count=sum(h[kind] is not None for h in hourly)
                    failure=next((e for e in errors if e['source']==kind),None)
                    if kind=='wave' and point['section']=='west':
                        state='not_applicable';reason='Сухопутная точка: морские волны не запрашиваются и не подставляются'
                    elif failure:
                        state='request_error';reason=failure['message'];diagnostic['http_status']=failure['http_status']
                    elif diagnostic.get('status')=='invalid_response':
                        state='invalid_response';reason=diagnostic['reason']
                    elif count==72:state='available';reason='Доступны все 72 почасовых значения'
                    elif count:
                        state='partial';reason=f'Доступно {count} из 72 часов; остальные часы оставлены пустыми'
                    elif any(v is not None for v in values[kind].get(point['id'],{}).values()):
                        state='outside_horizon';reason='Временные метки ответа не пересекаются с запрошенным окном UTC'
                    else:
                        state='no_coverage';reason='Open-Meteo не вернул числовых значений для этой точки и периода (null или отсутствующее поле); покрытие не подтверждено'
                    availability[kind]={**diagnostic,'status':state,'reason':reason,'available_hours':count,'requested_hours':72}
                points.append({**point,'hourly':hourly,'availability':availability})
            ttl=min(60 if errors else 900,max(1,(start+timedelta(hours=1)-fetched).total_seconds()))
            self.cache={'source':'Open-Meteo','requested_at':requested.isoformat(),'fetched_at':fetched.isoformat(),'starts_at':start.isoformat(),
                        'expires_at':(fetched+timedelta(seconds=ttl)).isoformat(),'points':points,'errors':errors,
                        'retry_after_seconds':0,
                        'attribution':'Weather data by Open-Meteo (CC BY 4.0); underlying model providers: see Open-Meteo documentation.',
                        'links':{'wind':'https://open-meteo.com/en/docs','wave':'https://open-meteo.com/en/docs/marine-weather-api'}}
            self.expires=time.monotonic()+ttl
            return self.cache

def risk(wind,wave,settings,sea=True):
    complete=wind is not None and (wave is not None or not sea)
    index=None if not complete else round(min(100,100*max(wind/settings.wind_danger,(wave or 0)/settings.wave_danger)),1)
    danger=(wind is not None and wind>=settings.wind_danger) or (wave is not None and wave>=settings.wave_danger)
    warning=(wind is not None and wind>=settings.wind_warning) or (wave is not None and wave>=settings.wave_warning)
    wind_index=None if wind is None else round(min(100,100*wind/settings.wind_danger),1)
    wave_index=None if wave is None or not sea else round(min(100,100*wave/settings.wave_danger),1)
    return {'wind_index':wind_index,'wave_index':wave_index,'risk_index':index,'severity':'danger' if danger else 'warning' if warning else 'low' if complete else 'unknown',
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
