import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const origin='http://127.0.0.1:3000';
const fmt=(v:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(v);

test('auto mode uses live application forecast, 72-hour charts and source metadata',async({page})=>{
 await page.goto('/');await expect(page.locator('.cargo-item').first()).toBeVisible();
 const response=page.waitForResponse(r=>r.url().endsWith('/api/forecast')&&r.status()===200,{timeout:30000});
 await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 const data=await(await response).json();
 await expect(page.getByRole('heading',{name:'Автопрогноз · 72 часа'})).toBeVisible();
 await expect(page.locator('.forecast-source')).toContainText('Open-Meteo');
 await expect(page.locator('.live-weather')).toContainText('не является вероятностью');
 expect(data.weather.points).toHaveLength(7);
 expect(data.weather.points[0].hourly).toHaveLength(72);
 await page.locator('.live-weather summary').click();
 await expect(page.locator('.live-weather tbody tr')).toHaveCount(72);
 await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption('direct-south');
 await expect(page.locator('.live-weather tbody tr')).toHaveCount(72);
 await expect(page.locator('.auto-route-grid article')).toHaveCount(3);
 const group=page.locator('.dispatcher-alerts');
 if(data.alerts.length){
  await expect(group.locator('li')).toHaveCount(data.alerts.length);
  await group.getByRole('button',{name:'Отметить прочитанным'}).first().click();
  await expect(group.getByRole('button',{name:'Прочитано'}).first()).toBeDisabled();
 }
 await page.locator('.live-weather summary').click();
 await page.getByRole('combobox',{name:'Точка прогноза'}).selectOption('direct-north');
 const originalViewport=page.viewportSize()!;
 for(const width of [320,390,768,1440]){
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.setViewportSize(originalViewport);
 await page.locator('.forecast-map').scrollIntoViewIfNeeded();
 await expect.poll(()=>page.locator('img.leaflet-tile').evaluateAll(images=>images.length>0&&images.every(img=>(img as HTMLImageElement).complete&&(img as HTMLImageElement).naturalWidth>0)),{timeout:20000}).toBe(true);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
 await page.screenshot({path:`../docs/screenshots/auto-forecast-${test.info().project.name}.png`,fullPage:true,scale:'css'});
 await page.getByRole('button',{name:'Ручная симуляция',exact:true}).click();
 await expect(page.getByRole('slider',{name:'Интенсивность шторма'})).toBeVisible();
});

test('manual economics and weighted recommendation follow model and tariffs',async({page,request})=>{
 await page.goto('/');await expect(page.locator('.cargo-item').first()).toBeVisible();
 const response=page.waitForResponse(r=>r.url().endsWith('storm=100')&&r.status()===200);
 await page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100');
 const data=await(await response).json();const shipment=data.shipments[0];
 const panel=page.locator('.manual-economics');
 await expect(panel).toContainText('демонстрационные тарифы');
 const winner=shipment.alternatives.find((r:{id:string})=>r.id===shipment.recommendation.route_id);
 await expect(panel.locator('.recommendation')).toContainText(winner.name);
 for(const route of shipment.alternatives){
  await expect(panel.locator('tbody tr').filter({hasText:route.name})).toContainText(fmt(route.economics.transport_usd));
  await expect(panel.locator('tbody tr').filter({hasText:route.name})).toContainText(fmt(route.economics.delay_cost_usd));
 }
 expect(shipment.recommendation.scores).toHaveLength(3);
});

test('admin page and API require a server session and enforce Origin',async({page,request})=>{
 await page.goto('/admin');await expect(page).toHaveURL(/\/admin\/login$/);
 await expect(page.getByRole('heading',{name:'Вход администратора'})).toBeVisible();
 expect((await request.get('/api/admin/data')).status()).toBe(401);
 expect((await request.get('/api/admin/data',{headers:{Cookie:'caspiflow_admin=forged'}})).status()).toBe(401);
 expect((await request.post('/api/admin/login',{data:{password:'invalid'},headers:{Origin:'https://foreign.invalid'}})).status()).toBe(403);
 expect((await request.put('/api/admin/settings',{data:{},headers:{Origin:origin}})).status()).toBe(401);
 expect((await request.get('http://127.0.0.1:8000/admin/data')).status()).toBe(401);
});

test('private admin login, create/edit cargo, settings, journal and logout',async({page,context})=>{
 const password=readFileSync(process.env.CASPIFLOW_ADMIN_CREDENTIALS_PATH||path.resolve('../.runtime/admin-credentials.txt'),'utf8').trim();
 let id='';let originalSettings:Record<string,number>|undefined;
 try{
  await page.goto('/admin/login');
  await page.getByLabel('Пароль администратора').fill(password);
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole('heading',{name:'Грузы и статусы'})).toBeVisible();
  const cookies=await context.cookies();const session=cookies.find(c=>c.name==='caspiflow_admin');
  expect(session?.httpOnly).toBe(true);expect(session?.sameSite).toBe('Strict');
  const initial=await(await page.request.get('/api/admin/data')).json();originalSettings=initial.settings;
  id=Array.from({length:1000},(_,i)=>`CF-2026-${9999-i}`).find(candidate=>!initial.shipments.some((s:{id:string})=>s.id===candidate))!;
  const editor=page.locator('#cargo-editor');
  await editor.getByLabel('ID груза',{exact:true}).fill(id);
  await editor.getByLabel('Название груза',{exact:true}).fill('Playwright temporary cargo');
  await editor.getByLabel('Отправитель',{exact:true}).fill('Playwright operator');
  await editor.getByLabel('Масса, т',{exact:true}).fill('12.5');
  await editor.getByRole('button',{name:'Создать груз',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Груз создан');
  await page.getByRole('button',{name:`Редактировать ${id}`,exact:true}).click();
  await editor.getByLabel('Статус',{exact:true}).selectOption('delayed');
  await editor.getByLabel('Прогресс, от 0 до 1',{exact:true}).fill('0.4');
  await editor.getByRole('button',{name:'Сохранить груз',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Груз обновлён');
  const stored=await(await page.request.get(`/api/shipments/${id}`)).json();
  expect(stored.status).toBe('delayed');expect(stored.weight).toBe(12.5);
  const settings=page.locator('section').filter({has:page.getByRole('heading',{name:'Пороги, экономика и рекомендации',exact:true})});
  await settings.getByLabel('Задержка, USD/ч',{exact:true}).fill(String(originalSettings!.delay_usd_per_hour+1));
  await settings.getByRole('button',{name:'Сохранить настройки'}).click();
  await expect(page.getByRole('status')).toContainText('Пороги и тарифы сохранены');
  await expect(page.locator('.admin-audit')).toContainText('shipment_created');
  await expect(page.locator('.admin-audit')).toContainText('settings_updated');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:`../docs/screenshots/admin-${test.info().project.name}.png`,fullPage:true,scale:'css'});
  expect((await page.request.put('/api/admin/settings',{data:originalSettings,headers:{Origin:origin}})).status()).toBe(200);
  originalSettings=undefined;
  await page.getByRole('button',{name:'Выйти',exact:true}).click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  expect((await page.request.get('/api/admin/data')).status()).toBe(401);
 }finally{
  // Cleanup is independent of an expired browser/test timeout. Restore only this
  // test's settings and remove only its own explicitly marked shipment.
  execFileSync('../backend/.venv/bin/python',['-c',
   'import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); settings=json.loads(sys.argv[3]); c.execute("UPDATE settings SET value=? WHERE key=?",(json.dumps(settings),"operator")) if settings else None; row=c.execute("SELECT data FROM shipments WHERE id=?",(sys.argv[2],)).fetchone(); c.execute("DELETE FROM shipments WHERE id=?",(sys.argv[2],)) if row and json.loads(row[0]).get("owner")=="Playwright operator" else None; c.commit(); c.close()',
   path.resolve('../backend/caspiflow.sqlite'),id,JSON.stringify(originalSettings||null)]);

 }
});

test('auto forecast failure and empty states never turn missing waves into zero',async({page,request})=>{
 const payload=await(await request.get('/api/forecast')).json();
 payload.weather.errors=[{source:'wave',message:'Тест недоступности Open-Meteo'}];
 payload.weather.points=payload.weather.points.map((p:Record<string,unknown>)=>({...p,hourly:(p.hourly as Record<string,unknown>[]).map(h=>({...h,wind:null,wave:null,risk_index:null}))}));
 payload.shipments=payload.shipments.map((s:Record<string,unknown>)=>({...s,recommendation:{route_id:null,conditional:true,scores:[],reason:'Недостаточно данных'},alternatives:(s.alternatives as Record<string,unknown>[]).map(r=>({...r,delay_hours:null,total_hours:null,eta_at:null,passage:{...(r.passage as object),complete:false},economics:{...(r.economics as object),total_cost_usd:null,delay_cost_usd:null}}))}));
 await page.route('**/api/forecast',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payload)}));
 await page.goto('/');await expect(page.locator('.cargo-item').first()).toBeVisible();
 await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 await expect(page.locator('.forecast-source .error-banner')).toContainText('Синтетическая подмена отключена');
 await expect(page.locator('.hourly-chart .empty')).toHaveCount(3);
 await expect(page.locator('.auto-route-grid')).toContainText('ML-прогноз отсутствует');
 payload.shipments=[];
 await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click();
 await expect(page.getByText('Нет грузов для прогнозирования.',{exact:false})).toBeVisible();
});
