import {test,expect} from '@playwright/test';
import {mkdirSync,readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const fmt=(v:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(v);
function pdfText(file:string){return execFileSync('../backend/.venv/bin/python',['-c','import sys; from pypdf import PdfReader; print("\\n".join(p.extract_text() for p in PdfReader(sys.argv[1]).pages))',file],{encoding:'utf8'}).replace(/\s+/g,' ');}

test('jury scenario reproduces calm to storm, recalculates recommendation and exports selected snapshot',async({page,request})=>{
 const calm=await(await request.get('/api/dashboard?storm=0')).json();
 await page.goto('/');await expect(page.locator('.cargo-item')).toHaveCount(4);
 await page.getByRole('button',{name:'Демо для жюри',exact:true}).click();
 const demo=page.getByRole('region',{name:'Демонстрационный сценарий для жюри'});
 await expect(demo).toContainText('1. Спокойная погода');await expect(demo).toContainText('синтетические');
 const response=page.waitForResponse(r=>r.url().endsWith('storm=100')&&r.ok());
 await demo.getByRole('button',{name:'2. Сильный шторм',exact:true}).click();
 const storm=await(await response).json();const shipment=storm.shipments.find((s:{id:string})=>s.id==='CF-2026-0841');
 expect(shipment.route.delay_hours).toBeGreaterThan(calm.shipments[0].route.delay_hours);
 expect(shipment.recommendation.route_id).not.toBe(shipment.route_id);
 await expect(demo.locator('.demo-result')).toContainText(`${fmt(calm.shipments[0].route.delay_hours)} → ${fmt(shipment.route.delay_hours)} ч`);
 const card=page.locator('.logist-action');await expect(card).toContainText('Западный сухопутный');
 await expect(card).toContainText('Сухопутный прогноз отдельно не валидирован');
 const ready=page.waitForEvent('download');await card.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();const download=await ready;
 const folder=path.resolve('../.runtime/report-downloads');mkdirSync(folder,{recursive:true});const file=path.join(folder,`manual-${test.info().project.name}.pdf`);await download.saveAs(file);
 expect(readFileSync(file).subarray(0,5).toString()).toBe('%PDF-');const text=pdfText(file);
 expect(text).toContain(shipment.id);expect(text).toContain('Шторм: 100%');expect(text).toContain(shipment.report_snapshot);
 expect(text).toContain('Сухопутный прогноз отдельно не валидирован');
 for(const route of shipment.alternatives)expect(text).toContain(route.name);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:`../docs/screenshots/final-demo-${test.info().project.name}.png`,scale:'css'});
 const original=page.waitForResponse(r=>r.url().endsWith('storm=0')&&r.ok());await demo.getByRole('button',{name:'Повторить с начала'}).click();await original;
 await expect(demo).toContainText('1. Спокойная погода');
 await demo.getByRole('button',{name:'Завершить демо'}).click();await expect(demo).toHaveCount(0);
});

test('auto report preserves binary PDF through gateway and includes actual selected cargo and sources',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 await expect(page.locator('.point-data-status')).toBeVisible();
 await page.getByRole('combobox',{name:'Груз автопрогноза'}).selectOption('CF-2026-0842');
 const pending=page.waitForResponse(r=>r.url().includes('/api/reports/CF-2026-0842'));
 const ready=page.waitForEvent('download');await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();
 const response=await pending;expect(response.status()).toBe(200);expect(response.headers()['content-type']).toContain('application/pdf');
 expect(response.headers()['content-disposition']).toContain('attachment;');
 const download=await ready;const file=path.resolve(`../.runtime/report-downloads/auto-${test.info().project.name}.pdf`);mkdirSync(path.dirname(file),{recursive:true});await download.saveAs(file);
 expect(readFileSync(file)).toEqual(await response.body());
 const text=pdfText(file);expect(text).toContain('CF-2026-0842');expect(text).toContain('Open-Meteo');expect(text).toContain('CO2');
 expect(text).not.toContain('None');expect(text).not.toContain('scrypt$');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:`../docs/screenshots/final-report-auto-${test.info().project.name}.png`,scale:'css'});
});

test('stale report shows a clear error and refreshes instead of silently changing the exported scenario',async({page})=>{
 await page.goto('/');await expect(page.getByRole('button',{name:'Сформировать отчёт',exact:true})).toBeEnabled();
 let first=true;await page.route('**/api/reports/**',r=>{if(first){first=false;return r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Данные расчёта изменились. Обновите расчёт.'})});}return r.continue();});
 await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();
 await expect(page.locator('.report-error')).toContainText('Данные расчёта изменились');
 await page.getByRole('button',{name:'Обновить расчёт',exact:true}).click();
 await expect(page.getByRole('button',{name:'Сформировать отчёт',exact:true})).toBeEnabled();
 const ready=page.waitForEvent('download');await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();
 expect((await ready).suggestedFilename()).toContain('-storm-0.pdf');
 await expect(page.locator('.report-error')).toHaveCount(0);
});
