'use client';
import type {Shipment} from './types';
type Props={phase:'calm'|'storm';shipment:Shipment;pending:boolean;error:boolean;onStorm:()=>void;onReset:()=>void;onFinish:()=>void};
const fmt=(v:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(v);
export default function DemoScenario({phase,shipment,pending,error,onStorm,onReset,onFinish}:Props){
 const route=shipment.route;const winner=shipment.alternatives.find(r=>r.id===shipment.recommendation.route_id);
 return <section className="panel jury-demo" aria-label="Демонстрационный сценарий для жюри" aria-live="polite">
  <div><strong>Демо для жюри · {phase==='calm'?'1. Спокойная погода':'2. Сильный шторм'}</strong><p>{shipment.id} · ручная симуляция · шторм {phase==='calm'?0:100}% · нагрузка из маршрутов. Погода и грузы синтетические; тарифы и веса текущие.</p></div>
  {pending?<p>Пересчитываем сценарий…</p>:error?<p>Сценарий не подтверждён: повторите загрузку.</p>:<p className="demo-result">Задержка текущего пути: {fmt(route.baseline.delay_hours)} → {fmt(route.delay_hours)} ч. {phase==='storm'&&winner&&(winner.id!==shipment.route_id?`Рассмотрите альтернативу: ${winner.name}.`:'При текущих весах рекомендован прежний путь.')} Сравнение и ограничения показаны в карточке ниже.</p>}
  <div className="demo-controls">{phase==='calm'?<button className="primary" disabled={pending||error} onClick={onStorm}>2. Сильный шторм</button>:<button className="secondary" onClick={onReset}>Повторить с начала</button>}<button className="secondary" onClick={onFinish}>Завершить демо</button></div>
 </section>;
}
