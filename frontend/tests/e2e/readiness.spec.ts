import {test,expect,type Locator} from '@playwright/test';
import type {Forecast,Shipment} from '../../app/types';
const fmt=(v:number,digits=1)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits}).format(v);
function delta(v:number,less:string,more:string,unit:string,digits=1){const n=Number(v.toFixed(digits));return n===0?'Без изменения':`${n<0?less:more} ${fmt(Math.abs(n),digits)} ${unit}`;}
async function compare(card:Locator,shipment:Shipment|Forecast['shipments'][number]){
 const winner=shipment.alternatives.find(r=>r.id===shipment.recommendation.route_id)!;
 const current=shipment.alternatives.find(r=>r.id===shipment.route_id)!;
 await expect(card).toContainText(winner.name);
 await expect(card.getByTestId('action-time')).toHaveText(delta(winner.total_hours!-current.total_hours!,'Быстрее на','Дольше на','ч'));
 await expect(card.getByTestId('action-cost')).toHaveText(delta(winner.economics.total_cost_usd!-current.economics.total_cost_usd!,'Экономия','Доплата','USD',2));
 await expect(card.getByTestId('action-co2')).toHaveText(delta(winner.co2_kg-current.co2_kg,'Меньше на','Больше на','кг CO₂',0));
 await expect(card).toContainText('Сухопутный прогноз отдельно не валидирован');
 await expect(card).toContainText('Условная рекомендация');
}

test('logist action uses actual manual API deltas, follows cargo and inspects without rerouting',async({page,request})=>{
 const base=await(await request.get('/api/dashboard')).json();
 await page.goto('/');const card=page.locator('.logist-action');
 await expect(card.getByRole('heading',{name:'Что делать логисту?'})).toBeVisible();
 await compare(card,base.shipments[0]);
 const response=page.waitForResponse(r=>r.url().endsWith('storm=100')&&r.ok());
 await page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100');
 const storm=await(await response).json();await compare(card,storm.shipments[0]);
 await card.getByRole('button',{name:'Посмотреть расчёт',exact:true}).click();
 const winner=storm.shipments[0].recommendation.route_id;
 await expect(page.locator('.route-card').filter({hasText:storm.shipments[0].alternatives.find((r:{id:string})=>r.id===winner).name})).toHaveClass(/chosen|selected/);
 expect((await(await request.get('/api/shipments/CF-2026-0841')).json()).route_id).toBe('direct');
 await page.locator('.cargo-item').filter({hasText:storm.shipments[1].id}).click();await compare(card,storm.shipments[1]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
 await page.screenshot({path:`../docs/screenshots/jury-action-manual-${test.info().project.name}.png`,fullPage:false,scale:'css'});
});

test('auto action appears before weather charts and handles missing current and all missing forecasts',async({page,request})=>{
 const data=await(await request.get('/api/forecast')).json() as Forecast;
 await page.goto('/');await page.getByRole('button',{name:'Автопрогноз',exact:true}).click();
 const card=page.locator('.logist-action');await compare(card,data.shipments[0]);
 expect(await card.evaluate((el)=>!!(el.compareDocumentPosition(document.querySelector('.live-weather')!)&Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
 await page.getByRole('combobox',{name:'Груз автопрогноза'}).selectOption(data.shipments[1].id);await compare(card,data.shipments[1]);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
 await page.screenshot({path:`../docs/screenshots/jury-action-auto-${test.info().project.name}.png`,fullPage:false,scale:'css'});
 const fixture=structuredClone(data);
 const target=fixture.shipments[1];
 const winner=target.alternatives.find(r=>r.id!==target.route_id)!;
 target.recommendation={route_id:winner.id,conditional:true,reason:'Частичные данные',scores:[{route_id:winner.id,score:0}]};
 const current=target.alternatives.find(r=>r.id===target.route_id)!;current.delay_hours=null;current.total_hours=null;current.eta_at=null;current.economics.total_cost_usd=null;
 await page.route('**/api/forecast*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)}));
 await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click();
 await expect(card.getByTestId('action-time')).toHaveText('Недостаточно данных');
 await expect(card.getByTestId('action-cost')).toHaveText('Недостаточно данных');
 target.recommendation={route_id:null,conditional:true,reason:'Нет данных',scores:[]};
 await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click();
 await expect(card).toContainText('Недостаточно данных для рекомендации');
 await expect(card.getByRole('button',{name:'Посмотреть расчёт',exact:true})).toHaveCount(0);
 await expect(card.getByRole('button',{name:'Сформировать отчёт',exact:true})).toBeVisible();
 await expect(card).not.toContainText(/NaN|Infinity/);
});

test('action hides obsolete recommendation on pending or failed manual scenario',async({page})=>{
 await page.goto('/');const card=page.locator('.logist-action');
 await expect(card.getByTestId('action-time')).toBeVisible();
 let release!:()=>void;const waiting=new Promise<void>(resolve=>release=resolve);
 await page.route('**/api/dashboard?storm=100',async r=>{await waiting;await r.fulfill({status:502,contentType:'application/json',body:'{}'});});
 await page.getByRole('slider',{name:'Интенсивность шторма'}).fill('100');
 await expect(card).toContainText('Пересчитываем решение');
 await expect(card.getByTestId('action-time')).toHaveCount(0);
 release();await expect(card).toContainText('Решение не обновлено');
 await expect(card.getByRole('button')).toHaveCount(0);
 await page.unroute('**/api/dashboard?storm=100');
 await page.getByRole('button',{name:'Повторить загрузку'}).click();
 await expect(card.getByTestId('action-time')).toBeVisible();
});
