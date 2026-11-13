'use client';
import type {ReactNode} from 'react';
import type {Decision,Economics,PredictionScope} from './types';

type Choice={id:string;name:string;total_hours:number|null;eta_at:string|null;co2_kg:number;economics:Economics;prediction:PredictionScope};
type Props={shipment:{id:string;route_id:string;alternatives:Choice[];recommendation:Decision};mode:'manual'|'auto';pending?:boolean;error?:boolean;onInspect:(id:string)=>void;report?:ReactNode};
const number=(v:number,digits=1)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits}).format(v);
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
function difference(value:number|null,less:string,more:string,unit:string,digits=1){
 if(value===null)return 'Недостаточно данных';
 const rounded=Number(value.toFixed(digits));
 return rounded===0?'Без изменения':`${rounded<0?less:more} ${number(Math.abs(rounded),digits)} ${unit}`;
}
export default function LogistAction({shipment,mode,pending=false,error=false,onInspect,report}:Props){
 const decision=shipment.recommendation;
 const chosen=shipment.alternatives.find(r=>r.id===decision.route_id);
 const current=shipment.alternatives.find(r=>r.id===shipment.route_id);
 const ready=chosen&&finite(chosen.total_hours)&&finite(chosen.economics.total_cost_usd);
 const title=<h2>Что делать логисту?</h2>;
 if(pending||error)return <section className="panel logist-action" aria-busy={pending} aria-live="polite">{title}<p>{pending?'Пересчитываем решение…':'Решение не обновлено: повторите загрузку. Прежний расчёт не подтверждает новый сценарий.'}</p></section>;
 if(!ready)return <section className="panel logist-action" aria-live="polite">{title}<p>Недостаточно данных для рекомендации. Проверьте доступность погоды и повторите запрос.</p><p className="action-footnote">Отсутствующие прогнозы не заменяются нулями или ручной симуляцией.</p>{report}</section>;
 const deltaTime=finite(current?.total_hours)?chosen.total_hours!-current.total_hours:null;
 const deltaCost=finite(current?.economics.total_cost_usd)?chosen.economics.total_cost_usd!-current.economics.total_cost_usd:null;
 const deltaCo2=finite(current?.co2_kg)?chosen.co2_kg-current.co2_kg:null;
 const land=shipment.alternatives.some(r=>r.prediction.validation_scope==='unvalidated_land'&&decision.scores.some(s=>s.route_id===r.id));
 const same=chosen.id===shipment.route_id;
 return <section className="panel logist-action" aria-live="polite">
  <div className="action-heading">{title}<span className={decision.conditional?'action-conditional':'action-badge'}>{decision.conditional?'Условная рекомендация':'Сценарная рекомендация'}</span></div>
  <p className="action-choice">{same?'Оставить в плане':'Рассмотреть'}: <strong>{chosen.name}</strong></p>
  <p className="action-context">Груз {shipment.id} · {mode==='auto'?'Погода Open-Meteo · новый план отправления':'Ручная симуляция · синтетическая погода'}. Выбор по существующей оценке времени, общей стоимости и CO₂ среди {decision.scores.length} доступных вариантов.</p>
  <dl className="action-deltas">
   <div><dt>Полное время</dt><dd data-testid="action-time">{difference(deltaTime,'Быстрее на','Дольше на','ч')}</dd></div>
   <div><dt>Расходы · демо-тарифы</dt><dd data-testid="action-cost">{difference(deltaCost,'Экономия','Доплата','USD',2)}</dd></div>
   <div><dt>Углеродный след</dt><dd data-testid="action-co2">{difference(deltaCo2,'Меньше на','Больше на','кг CO₂',0)}</dd></div>
  </dl>
  <p className="action-footnote">Сравнение с текущим маршрутом: {current?.name||'неизвестен'}. ETA варианта: {chosen.eta_at?new Date(chosen.eta_at).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'})+' МСК':'нет данных'}.</p>
  {land&&<p className="action-limitation">Сухопутный прогноз отдельно не валидирован; сравнение с ним ориентировочное. Метрики модели получены на синтетике.</p>}
  {decision.conditional&&!land&&<p className="action-limitation">Сравнение условное: часть данных отсутствует или входы выходят за диапазон обучения.</p>}
  <div className="action-controls">{report}<button className="secondary" onClick={()=>onInspect(chosen.id)}>Посмотреть расчёт</button><details><summary>Обоснование выбора</summary><p>{decision.reason}</p></details></div>
  <p className="action-footnote">Просмотр варианта не изменяет маршрут груза. Это поддержка решения диспетчера, не команда перенаправления.</p>
 </section>;
}
