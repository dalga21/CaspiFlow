import {test,expect,type Page} from '@playwright/test';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import type {Forecast} from '../../app/types';

async function openForecast(page:Page){
 await page.goto('/');await expect(page.locator('.cargo-item').first()).toBeVisible();
 const response=page.waitForResponse(r=>r.url().endsWith('/api/forecast')&&r.status()===200,{timeout:30000});
 await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 const data=await(await response).json() as Forecast;
 await expect(page.locator('.point-data-status')).toBeVisible();
 return data;
}

function waveFailure(data:Forecast){
 const failed=structuredClone(data);
 failed.weather.errors=[{source:'wave',message:'Open-Meteo вернул HTTP 503'}];
 for(const p of failed.weather.points){
  if(p.section==='west')continue;
  p.hourly=p.hourly.map(h=>({...h,wave:null,risk_index:null,wave_index:null,wind_index:h.wind===null?null:Math.min(100,100*h.wind/failed.settings.wind_danger)}));
  if(p.availability)p.availability.wave={status:'request_error',reason:'Open-Meteo вернул HTTP 503',http_status:503,available_hours:0,requested_hours:72};
 }
 for(const shipment of failed.shipments){
  for(const route of shipment.alternatives){if(route.id==='west')continue;route.delay_hours=null;route.total_hours=null;route.eta_at=null;route.passage.complete=false;route.prediction.inputs=null;route.prediction.source='unavailable';route.economics.total_cost_usd=null;route.economics.delay_cost_usd=null;route.economics.potential_savings_usd=null;}
 }
 return failed;
}

test('live forecast renders every available series for all seven points',async({page})=>{
 const data=await openForecast(page);
 const north=data.weather.points.find(p=>p.id==='direct-north')!;
 expect(north.hourly.filter(h=>h.wind!==null).length,'Live north wind coverage').toBeGreaterThan(0);
 const counts:Record<string,unknown>={};
 for(const point of data.weather.points){
  await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption(point.id);
  const values=[point.hourly.map(h=>h.wind),point.hourly.map(h=>h.wave),point.hourly.map(h=>h.risk_index)];
  const charts=page.locator('.weather-charts>.hourly-chart');
  for(let i=0;i<3;i++){
   const count=values[i].filter(v=>typeof v==='number'&&Number.isFinite(v)).length;
   if(count)await expect(charts.nth(i).getByRole('img')).toBeVisible();
   else {await expect(charts.nth(i).getByRole('img')).toHaveCount(0);await expect(charts.nth(i)).toContainText('Недостаточно данных');}
  }
  counts[point.id]={name:point.name,wind:values[0].filter(v=>v!==null).length,wave:values[1].filter(v=>v!==null).length,risk:values[2].filter(v=>v!==null).length,availability:point.availability};
  if(point.id==='direct-north'||point.id==='direct-south')await page.locator('.live-weather').screenshot({path:`../docs/screenshots/weather-fixed-${point.id}-${test.info().project.name}.png`,scale:'css'});
 }
 const file='../docs/weather_chart_probe.json';const report=existsSync(file)?JSON.parse(readFileSync(file,'utf8')):{};
 report[test.info().project.name]={fetched_at:data.weather.fetched_at,starts_at:data.weather.starts_at,errors:data.weather.errors,points:counts};
 writeFileSync(file,JSON.stringify(report,null,2)+'\n');
});

test('wind remains visible when Marine API fails and partial indicator is explicit',async({page,request})=>{
 const live=await(await request.get('/api/forecast')).json() as Forecast;
 const fixture=waveFailure(live);
 await page.route('**/api/forecast*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)}));
 await openForecast(page);
 const charts=page.locator('.weather-charts>.hourly-chart');
 await expect(charts.nth(0).getByRole('img')).toBeVisible();
 await expect(charts.nth(1)).toContainText('HTTP 503');
 await expect(charts.nth(1).getByRole('img')).toHaveCount(0);
 await expect(charts.nth(2)).toContainText('Недостаточно данных');
 await expect(charts.nth(2).getByRole('img')).toHaveCount(0);
 await expect(page.locator('.partial-weather-indicators')).toContainText('частичные данные');
 await expect(page.locator('.partial-weather-indicators').getByRole('img')).toBeVisible();
 await expect(page.locator('.point-data-status')).toContainText('Волны: 0 из 72');
});

test('retry issues a fresh forecast request and recovers wave graphs',async({page,request})=>{
 const live=await(await request.get('/api/forecast')).json() as Forecast;
 expect(live.weather.points[0].hourly.filter(h=>h.wave!==null).length,'Live north wave coverage').toBeGreaterThan(0);
 const failed=waveFailure(live);const urls:string[]=[];
 await page.route('**/api/forecast*',r=>{urls.push(r.request().url());return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(r.request().url().includes('retry=true')?live:failed)});});
 await openForecast(page);
 await expect(page.locator('.weather-charts>.hourly-chart').nth(1).getByRole('img')).toHaveCount(0);
 await page.getByRole('button',{name:'Повторить запрос погоды',exact:true}).click();
 await expect.poll(()=>urls.some(url=>url.endsWith('/api/forecast?retry=true'))).toBe(true);
 await expect(page.locator('.weather-charts>.hourly-chart').nth(1).getByRole('img')).toBeVisible();
 await expect(page.locator('.forecast-source .error-banner')).toHaveCount(0);
});

test('missing hours make line gaps rather than removing healthy weather data',async({page,request})=>{
 const fixture=await(await request.get('/api/forecast')).json() as Forecast;
 const north=fixture.weather.points[0];
 north.hourly=north.hourly.map((h,i)=>i%5===0?{...h,wind:null,risk_index:null,wind_index:null}:h);
 if(north.availability)north.availability.wind={status:'partial',reason:'Часть часов отсутствует',available_hours:north.hourly.filter(h=>h.wind!==null).length,requested_hours:72,http_status:200};
 await page.route('**/api/forecast*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)}));
 await openForecast(page);
 const chart=page.locator('.weather-charts>.hourly-chart').first();
 await expect(chart.getByRole('img')).toBeVisible();
 await expect(chart).toContainText('из 72 часов');
 const d=await chart.locator('path').getAttribute('d');
 expect((d?.match(/M/g)||[]).length).toBeGreaterThan(1);
 await expect(page.locator('.weather-charts>.hourly-chart').nth(1).getByRole('img')).toBeVisible();
 await expect(page.locator('.point-data-status')).toContainText('Недостаточно данных');
});

test('marine sea cell restores direct route forecast and discloses spatial approximation',async({page})=>{
 const data=await openForecast(page);
 const south=data.weather.points.find(p=>p.id==='direct-south')!;
 expect(south.availability?.wave.cell_selection).toBe('sea');
 expect(south.availability?.wave.grid_distance_km).toBeLessThanOrEqual(25);
 expect(south.hourly.filter(h=>h.wave!==null).length,'Live south marine coverage').toBeGreaterThan(0);
 await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption(south.id);
 await expect(page.locator('.point-data-status')).toContainText('пространственное приближение');
 await expect(page.locator('.weather-charts>.hourly-chart').nth(1).getByRole('img')).toBeVisible();
 await expect(page.locator('.weather-charts>.hourly-chart').nth(2).getByRole('img')).toBeVisible();
 for(const shipment of data.shipments){
  const route=shipment.alternatives.find(r=>r.id==='direct')!;
  expect(route.passage.complete).toBe(true);
  expect(route.delay_hours).not.toBeNull();
  expect(route.eta_at).not.toBeNull();
  expect(route.economics.total_cost_usd).not.toBeNull();
  expect(route.prediction.source).toBe('RandomForestRegressor.predict');
 }
 await page.locator('.live-weather').screenshot({path:`../docs/screenshots/marine-sea-direct-south-${test.info().project.name}.png`,scale:'css'});
});
