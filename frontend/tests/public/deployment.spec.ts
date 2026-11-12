import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import type {Forecast} from '../../app/types';
const origin=process.env.CASPIFLOW_PUBLIC_URL!;
const privateRoot=path.resolve('../.runtime/public-demo');

// Requests all use the real public origin; no intercepted responses or localhost checks.
test('public health, ML, cargo, CO2, map and manual storm',async({page,request})=>{
 const health=await request.get('/api/health');expect(health.status()).toBe(200);
 const model=await(await request.get('/api/model')).json();
 expect(model).toEqual(JSON.parse(readFileSync('../docs/ml_metrics.json','utf8')).metrics);
 const before=await(await request.get('/api/dashboard')).json();
 expect(before.shipments).toHaveLength(4);
 await page.goto('/');await expect(page.locator('.cargo-item')).toHaveCount(4);
 await expect(page.locator('.leaflet-container')).toBeVisible();
 const attribution=page.locator('.leaflet-control-attribution');
 await expect(attribution).toBeVisible();
 await expect(attribution).toContainText('Leaflet | © OpenStreetMap contributors');
 await expect(attribution.locator('svg,img,.leaflet-attribution-flag')).toHaveCount(0);
 await expect(attribution.locator('a')).toHaveCount(2);
 await expect(attribution.getByRole('link',{name:'Leaflet',exact:true})).toHaveAttribute('href','https://leafletjs.com');
 await expect(attribution.getByRole('link',{name:'OpenStreetMap',exact:true})).toHaveAttribute('href','https://www.openstreetmap.org/copyright');
 await expect(page.locator('.leaflet-tile-loaded').first()).toBeVisible();
 await page.getByRole('button',{name:'Zoom out'}).click();
 const port=page.locator('.leaflet-overlay-pane path[fill="#183e53"]').first();
 await port.click();await expect(page.locator('.leaflet-popup-content')).toContainText('Загрузка');
 await page.locator('.leaflet-popup-close-button').click();
 for(const shipment of before.shipments)for(const r of shipment.alternatives){
  const co2=r.segments.reduce((sum:number,s:{mode:string;km:number})=>sum+s.km*({sea:.016,rail:.022,road:.085}[s.mode]||0)*shipment.weight,0);
  expect(Math.abs(r.co2_kg-co2)).toBeLessThanOrEqual(.5);
 }
 const response=page.waitForResponse(r=>r.url().endsWith('/api/dashboard?storm=80')&&r.ok());
 await page.getByRole('button',{name:'Симулировать шторм'}).click();
 const storm=await(await response).json();
 expect(storm.shipments[0].route.delay_hours).toBeGreaterThan(before.shipments[0].route.delay_hours);
 await expect(page.locator('.weather-visual')).toContainText('Сильный шторм');
 const reset=page.waitForResponse(r=>r.url().endsWith('/api/dashboard?storm=0')&&r.ok());
 await page.getByRole('button',{name:'Сбросить сценарий'}).click();await reset;
 await expect(page.locator('.weather-visual')).toContainText('Спокойное море');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`../docs/screenshots/public-home-${test.info().project.name}.png`,fullPage:true,scale:'css'});
});

test('public Open-Meteo forecast and every point chart use real API values',async({page,request})=>{
 const r=await request.get('/api/forecast');expect(r.status()).toBe(200);const data=await r.json() as Forecast;
 expect(data.weather.errors).toEqual([]);expect(data.weather.points).toHaveLength(7);
 await page.goto('/');await expect(page.locator('.cargo-item').first()).toBeVisible();
 await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 await expect(page.locator('.forecast-source')).toContainText('Open-Meteo');
 for(const point of data.weather.points){
  expect(point.hourly).toHaveLength(72);
  expect(point.availability?.wind.http_status).toBe(200);
  expect(point.hourly.filter(h=>h.wind!==null).length).toBeGreaterThan(0);
  await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption(point.id);
  const charts=page.locator('.weather-charts>.hourly-chart');
  for(const [i,key] of ['wind','wave','risk_index'].entries()){
   const count=point.hourly.filter(h=>typeof h[key as keyof typeof h]==='number').length;
   if(count)await expect(charts.nth(i).getByRole('img')).toBeVisible();
   else await expect(charts.nth(i)).toContainText('Недостаточно данных');
  }
 }
 for(const shipment of data.shipments){
  const direct=shipment.alternatives.find(r=>r.id==='direct')!;
  expect(direct.prediction.source).toBe('RandomForestRegressor.predict');
  expect(direct.eta_at).not.toBeNull();expect(direct.economics.total_cost_usd).not.toBeNull();
 }
 await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption('direct-south');
 await expect(page.locator('.live-weather')).toContainText('пространственное приближение');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.locator('.live-weather').screenshot({path:`../docs/screenshots/public-weather-${test.info().project.name}.png`,scale:'css'});
});

test('public customs validates, saves and reloads a labelled demonstration declaration',async({page,request})=>{
 const data=await(await request.get('/api/dashboard')).json();
 const shipment=data.shipments.find((s:{customs:unknown})=>!s.customs);expect(shipment).toBeTruthy();
 let id:string|undefined;
 try{
  await page.goto('/');await page.locator('.cargo-item').filter({hasText:shipment.id}).click();
  await page.getByRole('button',{name:'Подать заявку'}).click();const dialog=page.getByRole('dialog');
  await dialog.locator('[name=hs_code]').fill('abc');
  await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
  expect(await dialog.locator('[name=hs_code]').evaluate((el:HTMLInputElement)=>el.validity.patternMismatch)).toBe(true);
  await dialog.locator('[name=hs_code]').fill('8471300000');
  await dialog.locator('[name=declared_value]').fill('48000');
  await dialog.locator('[name=invoice_number]').fill('PUBLIC-DEMO-PLAYWRIGHT');
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/customs')&&r.request().method()==='POST');
  await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
  const r=await pending;expect(r.status()).toBe(200);const saved=await r.json();id=saved.id;
  expect(saved.notice).toContain('Не является таможенным оформлением');
  await expect(dialog).not.toBeVisible();await page.reload();
  await page.locator('.cargo-item').filter({hasText:shipment.id}).click();
  await page.getByRole('button',{name:'Посмотреть'}).click();
  await expect(page.getByRole('dialog')).toContainText(id!);
  await expect(page.getByRole('dialog')).toContainText('SHA-256:');
  await page.screenshot({path:`../docs/screenshots/public-customs-${test.info().project.name}.png`,scale:'css'});
 }finally{
  // Delete only this test declaration in the isolated public DB. No local DB is touched.
  if(id)execFileSync('../backend/.venv/bin/python',['-c','import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("DELETE FROM customs WHERE id=? AND payload LIKE ?",(sys.argv[2],"%PUBLIC-DEMO-PLAYWRIGHT%")); c.commit()',path.join(privateRoot,'data/caspiflow.sqlite'),id]);
 }
});

test('public admin enforces HTTPS session, Origin, server authentication and logout',async({page,context,request})=>{
 await page.goto('/admin');await expect(page).toHaveURL(/\/admin\/login$/);
 expect((await request.get('/api/admin/data')).status()).toBe(401);
 expect((await request.get('/api/admin/data',{headers:{Cookie:'caspiflow_admin=forged'}})).status()).toBe(401);
 expect((await request.post('/api/admin/login',{data:{password:'invalid'},headers:{Origin:'https://foreign.invalid'}})).status()).toBe(403);
 const password=readFileSync(path.join(privateRoot,'admin-password.txt'),'utf8').trim();
 await page.getByLabel('Пароль администратора').fill(password);
 await page.getByRole('button',{name:'Войти',exact:true}).click();
 await expect(page).toHaveURL(/\/admin$/);await expect(page.getByRole('heading',{name:'Грузы и статусы'})).toBeVisible();
 const cookie=(await context.cookies()).find(c=>c.name==='caspiflow_admin');
 expect(cookie?.secure).toBe(true);expect(cookie?.httpOnly).toBe(true);expect(cookie?.sameSite).toBe('Strict');
 const data=await page.request.get('/api/admin/data');expect(data.status()).toBe(200);
 const settings=(await data.json()).settings;
 const saved=await page.request.put('/api/admin/settings',{data:settings,headers:{Origin:origin}});expect(saved.status()).toBe(200);
 await page.screenshot({path:`../docs/screenshots/public-admin-${test.info().project.name}.png`,fullPage:true,scale:'css'});
 await page.getByRole('button',{name:'Выйти',exact:true}).click();await expect(page).toHaveURL(/\/admin\/login$/);
 expect((await page.request.get('/api/admin/data')).status()).toBe(401);
});
