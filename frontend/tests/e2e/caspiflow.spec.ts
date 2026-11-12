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
  await expect(page.locator('#analytics')).toContainText('MAE 2.03 ч');
});

test('storm button, slider, recommendation change, and reset', async ({page}) => {
  const setStorm = async (value: number, action: ()=>Promise<unknown>) => {
    const response = page.waitForResponse(r=>r.url().endsWith(`/api/dashboard?storm=${value}`) && r.status()===200);
    await action();
    return (await (await response).json()).shipments[0];
  };
  await setStorm(80,()=>page.getByRole('button',{name:'Симулировать шторм'}).click());
  await expect(page.locator('.weather-visual')).toContainText('Сильный шторм');
  await expect(page.locator('.detail-metrics strong').first()).not.toContainText('14.9');
  const data = await setStorm(100,()=>page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100'));
  await expect(page.locator('.detail-metrics strong').first()).toContainText(String(data.route.delay_hours));
  await expect(page.locator('.route-card').filter({hasText:'Западный сухопутный'})).toContainText('Самый быстрый в сценарии');
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#ec8d35"]')).toHaveCount(1);
  await page.screenshot({path:`../docs/screenshots/storm-${test.info().project.name}.png`,fullPage:true,scale:'css'});
  await setStorm(0,()=>page.getByRole('button',{name:'Сбросить сценарий'}).click());
  await expect(page.locator('.detail-metrics strong').first()).toContainText('14.9');
  await expect(page.locator('.weather-visual')).toContainText('Спокойное море');
  await expect(page.locator('.leaflet-overlay-pane path[stroke="#ec8d35"]')).toHaveCount(0);
});

test('map tiles, port popup, zoom, pan, cargo markers and route geometry', async ({page}) => {
  await expect(page.locator('.leaflet-tile-loaded').first()).toBeVisible();
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
    await page.getByRole('button',{name:'Посмотреть'}).click();
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
