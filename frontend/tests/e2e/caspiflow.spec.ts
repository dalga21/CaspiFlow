import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import path from 'node:path';

const ids = ['CF-2026-0841','CF-2026-0842','CF-2026-0843','CF-2026-0844'];
const format = (n: number) => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(n);

test.beforeEach(async ({page}) => {
  await page.goto('/');
  await expect(page.locator('.cargo-item')).toHaveCount(4);
  await expect(page.locator('.leaflet-container')).toBeVisible();
});

test('all navigation sections, cargo search and cargo selection', async ({page}) => {
  for (const [name, target] of [['Мои грузы','#cargo'],['Маршруты','#routes'],['Цифровая таможня','#shipment-detail'],['ML-аналитика','#analytics'],['Обзор перевозок','#top']]) {
    const button = page.getByRole('button', {name, exact: true});
    await button.click();
    await expect(button).toHaveClass(/active/);
    await expect(page.locator(target)).toBeInViewport();
  }
  for (const id of ids) {
    await page.locator('.cargo-item').filter({hasText: id}).click();
    await expect(page.locator('#shipment-detail h2')).toHaveText(id);
    await expect(page.locator('#routes')).toContainText(id);
  }
  const search = page.getByRole('textbox', {name:'Поиск груза'});
  for (const query of ['0842','Зерно','АгроЭкспорт']) {
    await search.fill(query);
    await expect(page.locator('.cargo-item')).toHaveCount(1);
    await expect(page.locator('.cargo-item')).toContainText('0842');
  }
  await search.fill('несуществующий груз');
  await expect(page.getByText('Грузы не найдены')).toBeVisible();
  await search.fill('');
  await expect(page.locator('.cargo-item')).toHaveCount(4);
});

test('route predictions and CO₂ agree with API for every cargo and route', async ({page, request}) => {
  const data = await (await request.get('/api/dashboard')).json();
  const factors: Record<string, number> = {sea:.016,rail:.022,road:.085};
  for (const shipment of data.shipments) {
    await page.locator('.cargo-item').filter({hasText: shipment.id}).click();
    for (const route of shipment.alternatives) {
      await page.locator('.route-card').filter({hasText: route.name}).click();
      await expect(page.locator('.detail-metrics strong').nth(0)).toContainText(String(route.delay_hours));
      await expect(page.locator('.detail-metrics strong').nth(1)).toContainText(format(route.total_hours));
      await expect(page.locator('.detail-metrics strong').nth(2)).toContainText(format(route.co2_kg/1000));
      expect(route.total_hours).toBeCloseTo(route.hours+route.delay_hours,1);
      const calculated = route.segments.reduce((sum: number, s: {mode: string; km: number})=>sum+s.km*factors[s.mode]*shipment.weight,0);
      expect(Math.abs(route.co2_kg-calculated)).toBeLessThanOrEqual(.5);
    }
  }
  const sum = data.shipments.reduce((total: number, s: {route: {co2_kg: number}})=>total+s.route.co2_kg,0);
  await expect(page.locator('.metric').nth(2)).toContainText(format(sum/1000));
  await expect(page.locator('#analytics')).toContainText('Почему ИИ дал такой прогноз?');
});

test('storm button, slider, recommendation change, and reset', async ({page, request}) => {
  const base = (await (await request.get('/api/dashboard')).json()).shipments[0].route.delay_hours;
  const setStorm = async (value: number, action: ()=>Promise<unknown>) => {
    const response = page.waitForResponse(r=>r.url().endsWith(`/api/dashboard?storm=${value}`) && r.status()===200);
    await action();
    return (await (await response).json()).shipments[0];
  };
  await setStorm(80,()=>page.getByRole('button',{name:'Симулировать шторм'}).click());
  await expect(page.locator('.weather-visual')).toContainText('Сильный шторм');
  await expect(page.locator('.detail-metrics strong').first()).not.toContainText(String(base));
  const data = await setStorm(100,()=>page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100'));
  await expect(page.locator('.detail-metrics strong').first()).toContainText(String(data.route.delay_hours));
  await expect(page.locator('.route-card').filter({hasText:'Западный сухопутный'})).toContainText('Самый быстрый в сценарии');
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#ec8d35"]')).toHaveCount(1);
  await expect.poll(()=>page.locator('img.leaflet-tile').evaluateAll(images=>images.length>0&&images.every(img=>(img as HTMLImageElement).complete&&(img as HTMLImageElement).naturalWidth>0)),{timeout:20000}).toBe(true);
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await expect.poll(()=>page.evaluate(()=>window.scrollY)).toBe(0);
  await page.screenshot({path:`../docs/screenshots/storm-${test.info().project.name}.png`,fullPage:true,scale:'css'});
  await setStorm(0,()=>page.getByRole('button',{name:'Сбросить сценарий'}).click());
  await expect(page.locator('.detail-metrics strong').first()).toContainText(String(base));
  await expect(page.locator('.weather-visual')).toContainText('Спокойное море');
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#ec8d35"]')).toHaveCount(0);
});

test('map tiles, port popup, zoom, pan, cargo markers and route geometry', async ({page}) => {
  await expect(page.locator('.leaflet-tile-loaded').first()).toBeVisible();
  const attribution=page.locator('.leaflet-control-attribution');
  await expect(attribution).toHaveCount(1);
  await expect(attribution).toBeVisible();
  await expect(attribution).toContainText('OpenStreetMap contributors');
  await expect(attribution.getByRole('link',{name:'Leaflet',exact:true})).toHaveAttribute('href','https://leafletjs.com');
  await expect(attribution.getByRole('link',{name:'OpenStreetMap',exact:true})).toHaveAttribute('href','https://www.openstreetmap.org/copyright');
  await expect(attribution.locator('svg,img,.leaflet-attribution-flag')).toHaveCount(0);
  await page.locator('.transit-map').screenshot({path:`../docs/screenshots/map-attribution-${test.info().project.name}.png`,scale:'css'});
  const zoomOut = page.getByRole('button',{name:'Zoom out'});
  await zoomOut.click();
  const port = page.locator('.leaflet-overlay-pane path[fill="#183e53"]').filter({visible:true});
  await expect(port).toHaveCount(7);
  for (const [index, name] of ['Астрахань','Махачкала','Актау','Баку','Энзели','Амирабад','Туркменбаши'].entries()) {
    await port.nth(index).click();
    await expect(page.locator('.leaflet-popup-content')).toContainText(name);
    await expect(page.locator('.leaflet-popup-content')).toContainText('Загрузка:');
    await page.locator('.leaflet-popup-close-button').click();
    await expect(page.locator('.leaflet-popup-content')).toHaveCount(0);
  }
  const line = page.locator('.leaflet-overlay-pane path[stroke="#057c85"]');
  const before = await line.getAttribute('d');
  await page.locator('.route-card').filter({hasText:'Западный сухопутный'}).click();
  await expect(line).not.toHaveAttribute('d',before!);
  const marker = page.locator('.leaflet-overlay-pane path[fill="#63829b"]').first();
  await marker.click();
  await expect(page.locator('#shipment-detail h2')).toHaveText(ids[1]);
  await page.locator('.transit-map').scrollIntoViewIfNeeded();
  const box = (await page.locator('.transit-map').boundingBox())!;
  const pane = page.locator('.leaflet-map-pane');
  const previous = await pane.getAttribute('style');
  await page.mouse.move(box.x+box.width*.7,box.y+box.height*.6);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width*.7+35,box.y+box.height*.6+30,{steps:8});
  await page.mouse.up();
  await expect(pane).not.toHaveAttribute('style',previous!);
  await page.getByRole('button',{name:'Zoom in'}).click();
});

test('customs validation, API failure, submission, receipt and persistence', async ({page, request}) => {
  const dashboard = await (await request.get('/api/dashboard')).json();
  const shipment = dashboard.shipments.find((s: {customs: unknown})=>!s.customs);
  expect(shipment, 'Need an unsubmitted demo shipment').toBeTruthy();
  let createdId: string|undefined;
  try {
    await page.locator('.cargo-item').filter({hasText:shipment.id}).click();
    await page.getByRole('button',{name:'Подать заявку'}).click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('[name=hs_code]').fill('abc');
    await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
    expect(await dialog.locator('[name=hs_code]').evaluate((el: HTMLInputElement)=>el.validity.patternMismatch)).toBe(true);
    await dialog.locator('[name=hs_code]').fill('8471300000');
    await dialog.locator('[name=declared_value]').fill('0');
    await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
    expect(await dialog.locator('[name=declared_value]').evaluate((el: HTMLInputElement)=>el.validity.rangeUnderflow)).toBe(true);
    await dialog.locator('[name=declared_value]').fill('48000');
    await dialog.locator('[name=invoice_number]').fill('INV-PLAYWRIGHT');
    await page.route('**/api/customs',r=>r.fulfill({status:502,contentType:'application/json',body:JSON.stringify({detail:'Тест: backend недоступен'})}));
    await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
    await expect(dialog.getByRole('alert')).toHaveText('Тест: backend недоступен');
    await page.unroute('**/api/customs');
    const response = page.waitForResponse(r=>r.url().endsWith('/api/customs') && r.request().method()==='POST');
    await dialog.getByRole('button',{name:'Сохранить демо-заявку'}).click();
    const submitted = await response;
    expect(submitted.status()).toBe(200);
    createdId = (await submitted.json()).id;
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole('status')).toContainText(createdId!);
    await page.reload();
    await page.locator('.cargo-item').filter({hasText:shipment.id}).click();
    await page.getByRole('button',{name:'Посмотреть',exact:true}).click();
    await expect(page.getByRole('dialog')).toContainText(createdId!);
    await expect(page.getByRole('dialog')).toContainText('SHA-256:');
    await page.screenshot({path:`../docs/screenshots/customs-${test.info().project.name}.png`,fullPage:false,scale:'css'});
    await page.getByRole('button',{name:'Закрыть',exact:true}).click();
  } finally {
    // Remove only the declaration created by this test, preserving existing demo data.
    if (createdId) execFileSync('../backend/.venv/bin/python',['-c',
      'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("DELETE FROM customs WHERE id=? AND payload LIKE ?",(sys.argv[2],"%INV-PLAYWRIGHT%")); c.commit(); c.close()',
      path.resolve('../backend/caspiflow.sqlite'),createdId]);
  }
});

test('modal keyboard focus stays inside and Escape closes it', async ({page}) => {
  const trigger = page.locator('.customs-row button');
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
  for (let i=0;i<10;i++) {
    await page.keyboard.press('Tab');
    expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('responsive layout, clean console, and screenshots', async ({page}) => {
  const errors: string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.reload();
  await expect(page.locator('.cargo-item')).toHaveCount(4);
  const originalViewport = page.viewportSize()!;
  const widths = test.info().project.name==='mobile'?[320,390,768]:[1024,1280,1440];
  for (const width of widths) {
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}px`).toBe(true);
  }
  await page.setViewportSize(originalViewport);
  await expect(page.locator('.leaflet-container')).toBeVisible();
  await expect.poll(()=>page.locator('img.leaflet-tile').evaluateAll(images=>images.length>0&&images.every(img=>(img as HTMLImageElement).complete&&(img as HTMLImageElement).naturalWidth>0)),{timeout:20000}).toBe(true);
  await page.screenshot({path:`../docs/screenshots/${test.info().project.name}.png`,fullPage:true,scale:'css'});
  expect(errors).toEqual([]);
});

test('dashboard failure is shown and retry recovers', async ({page}) => {
  await page.route('**/api/dashboard?storm=0',r=>r.fulfill({status:502,contentType:'application/json',body:'{}'}));
  await page.reload();
  await expect(page.getByText('Не удалось получить данные. Проверьте backend и повторите.')).toBeVisible();
  await page.unroute('**/api/dashboard?storm=0');
  await page.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(page.locator('.cargo-item')).toHaveCount(4);
});

test('explainable AI shows measured global importance and actual route inputs', async ({page,request}) => {
  const data=await (await request.get('/api/dashboard')).json();
  await page.getByRole('button',{name:'ML-аналитика',exact:true}).click();
  const insights=page.locator('#analytics');
  await expect(insights.getByRole('heading',{name:'Почему ИИ дал такой прогноз?'})).toBeVisible();
  await expect(insights.locator('.factor-row')).toHaveCount(6);
  await expect(insights).toContainText('Permutation importance');
  await expect(insights).toContainText('не доказывают причинность');
  for (const [i,key] of ['mae_hours','rmse_hours','r2','baseline_mae_hours'].entries()) {
    await expect(insights.locator('.quality-grid strong').nth(i)).toContainText(new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(data.model[key]));
  }
  await expect(insights.locator('.prediction-inputs')).toContainText('Ветер');
  await page.locator('.route-card').filter({hasText:'Западный сухопутный'}).click();
  await expect(insights).toContainText('Западный сухопутный');
  await expect(insights.locator('.prediction-inputs')).toContainText('1 630');
  await insights.screenshot({path:`../docs/screenshots/explainable-ai-${test.info().project.name}.png`,scale:'css'});
});

test('port congestion, ETA comparison, risk sections and fastest route action', async ({page,request}) => {
  const load=page.getByRole('combobox',{name:'Загрузка логистических узлов'});
  const setLoad=async(value:string)=>{
    const response=page.waitForResponse(r=>r.url().includes(`port_load=${value}`)&&r.status()===200);
    await load.selectOption(value);
    return (await (await response).json()).shipments[0].route;
  };
  const low=await setLoad('30');
  const high=await setLoad('99');
  expect(high.delay_hours).toBeGreaterThan(low.delay_hours);
  await expect(page.locator('.detail-metrics strong').first()).toContainText(String(high.delay_hours));
  await page.getByRole('button',{name:'Сбросить сценарий'}).click();
  await expect(load).toHaveValue('');
  const storm=page.waitForResponse(r=>r.url().endsWith('storm=100')&&r.status()===200);
  await page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100');
  const shipment=(await (await storm).json()).shipments[0];
  const comparison=page.getByRole('region',{name:'До и после сценария'});
  await expect(comparison).toContainText('шторм 100%');
  await expect(comparison).toContainText(String(shipment.route.delay_change_hours).replace('.',','));
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#d6752c"]')).toHaveCount(2);
  await comparison.getByRole('button',{name:'Показать быстрый маршрут'}).click();
  await expect(page.locator('.route-card.chosen')).toContainText('Западный сухопутный');
  await expect(page.locator('.eta-line')).toContainText('Просмотр альтернативы');
  const west=shipment.alternatives.find((r:{id:string})=>r.id==='west');
  await expect(page.locator('.detail-metrics strong').nth(1)).toContainText(format(west.total_hours));
  const stored=await (await request.get('/api/shipments/CF-2026-0841')).json();
  expect(stored.route_id).toBe('direct');
});

test('failed scenario never presents stale predictions as the requested storm', async ({page}) => {
  await page.route('**/api/dashboard?storm=100',r=>r.fulfill({status:502,contentType:'application/json',body:'{}'}));
  await page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100');
  await expect(page.locator('.error-banner[role=alert]')).toContainText('последние успешно загруженные данные');
  await expect(page.locator('.weather-visual')).toContainText('Спокойное море');
  await expect(page.getByRole('region',{name:'До и после сценария'})).toContainText('шторм 0%');
  await page.unroute('**/api/dashboard?storm=100');
  await page.getByRole('button',{name:'Повторить загрузку'}).click();
  await expect(page.locator('.weather-visual')).toContainText('Сильный шторм');
  await expect(page.getByRole('region',{name:'До и после сценария'})).toContainText('шторм 100%');
});

test('integration gateway rejects foreign origin and oversized payloads', async ({request}) => {
  const payload={shipment_id:ids[0],hs_code:'8471300000',invoice_number:'INV-BLOCKED',declared_value:48000,country:'IR'};
  expect((await request.post('/api/customs',{data:payload,headers:{Origin:'https://foreign.invalid'}})).status()).toBe(403);
  expect((await request.post('/api/customs',{data:payload})).status()).toBe(403);
  expect((await request.post('/api/customs',{data:{...payload,invoice_number:'Я'.repeat(5000)},headers:{Origin:'http://127.0.0.1:3000'}})).status()).toBe(413);
  expect((await request.post('http://127.0.0.1:8000/customs',{data:payload})).status()).toBe(401);
  expect((await request.get('/api/unknown')).status()).toBe(404);
  expect((await request.get('/api/dashboard?storm=101')).status()).toBe(422);
});

test('map remains usable without external tiles', async ({page}) => {
  await page.route('**/*.tile.openstreetmap.org/**',route=>route.abort());
  await page.reload();
  await expect(page.getByRole('status')).toContainText('Подложка недоступна');
  await expect(page.locator('.leaflet-overlay-pane path[fill="#183e53"]')).toHaveCount(7);
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#057c85"]')).toBeVisible();
});
