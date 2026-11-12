'use client';
import {Activity,ArrowRight,CloudLightning} from 'lucide-react';
import type {ModelMetrics,Route,Shipment} from './types';

const fmt=(n:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n);
export const eta=(value:string)=>new Date(value).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});

export function ScenarioComparison({shipment,route,storm,onChoose}:{shipment:Shipment;route:Route;storm:number;onChoose:(id:string)=>void}){
 const best=shipment.alternatives.reduce((a,b)=>a.total_hours<=b.total_hours?a:b);
 const baseBest=shipment.alternatives.reduce((a,b)=>a.baseline.total_hours<=b.baseline.total_hours?a:b);
 return <section className="panel scenario-comparison" aria-labelledby="comparison-title">
  <div className="panel-heading"><div><h2 id="comparison-title">До и после сценария</h2><p>{shipment.id} · шторм {storm}% · один момент отправления для всех вариантов</p></div><CloudLightning size={24}/></div>
  <div className="scenario-summary"><div><span>Задержка выбранного пути</span><strong>{fmt(route.baseline.delay_hours)} <ArrowRight size={16}/> {fmt(route.delay_hours)} ч</strong><small>Изменение: {route.delay_change_hours>=0?'+':''}{fmt(route.delay_change_hours)} ч</small></div><div><span>ETA выбранного пути · МСК</span><strong>{eta(route.eta_at)}</strong><small>До сценария: {eta(route.baseline.eta_at)}</small></div><div><span>Быстрейший путь</span><strong>{best.name}</strong><small>До шторма: {baseBest.name}</small></div></div>
  <div className="scenario-options">{shipment.alternatives.map(r=><button key={r.id} className={`scenario-option ${route.id===r.id?'chosen':''}`} aria-pressed={route.id===r.id} onClick={()=>onChoose(r.id)}><strong>{r.name}</strong><span>Полное время: {fmt(r.baseline.total_hours)} → {fmt(r.total_hours)} ч</span><span>ETA: {eta(r.eta_at)} МСК</span><small>{r.risk_level==='high'?'Высокий погодный риск':r.risk_level==='elevated'?'Повышенный погодный риск':'Низкий погодный риск'}{best.id===r.id?' · самый быстрый':''}</small></button>)}</div>
  {best.id!==route.id&&<button className="secondary show-fastest" onClick={()=>onChoose(best.id)}>Показать быстрый маршрут<ArrowRight size={16}/></button>}
  <p className="insight-note">Расчёт от демонстрационного момента отправления, без расписаний и реального перенаправления. CO₂ зависит от пути и массы; шторм сам по себе не меняет коэффициенты выбросов.</p>
 </section>;
}

export function PredictionInsights({model,route}:{model:ModelMetrics;route:Route}){
 const max=Math.max(...model.explanation.factors.map(f=>f.mae_increase_hours),.001);
 return <section className="panel prediction-insights" id="analytics" aria-labelledby="insights-title">
  <div className="panel-heading"><div><h2 id="insights-title">Почему ИИ дал такой прогноз?</h2><p>{model.name} · версия {model.version} · синтетические данные</p></div><Activity size={24}/></div>
  <div className="quality-grid"><div><span>MAE на тесте</span><strong>{fmt(model.mae_hours)} ч</strong></div><div><span>RMSE на тесте</span><strong>{fmt(model.rmse_hours)} ч</strong></div><div><span>R² на тесте</span><strong>{fmt(model.r2)}</strong></div><div><span>MAE медианного baseline</span><strong>{fmt(model.baseline_mae_hours)} ч</strong></div></div>
  <div className="insight-columns"><div><h3>На что опирается модель в целом</h3><p>Permutation importance: рост MAE при перемешивании одного фактора на тестовых рейсах. Чем длиннее полоса, тем сильнее ухудшается точность.</p><div className="factor-chart" role="img" aria-label="Глобальная важность факторов: рост MAE в часах">{model.explanation.factors.map(f=><div className="factor-row" key={f.key}><div><span>{f.label}</span><strong>{f.mae_increase_hours>=0?'+':''}{fmt(f.mae_increase_hours)} ч</strong></div><div className="factor-track"><span style={{width:`${Math.max(0,f.mae_increase_hours)/max*100}%`}}/></div><small>±{fmt(f.std_hours)} ч · стандартное отклонение по {model.explanation.repeats} перестановкам</small></div>)}</div></div><div><h3>Входные данные этого прогноза</h3><p>{route.name} · задержка {fmt(route.delay_hours)} ч. Эти значения переданы в обученную модель через API.</p><dl className="prediction-inputs">{model.explanation.factors.map(f=><div key={f.key}><dt>{f.label}</dt><dd>{fmt(route.prediction.inputs[f.key])} {f.unit}</dd></div>)}</dl><div className="calibration-note"><strong>Как читать диапазон</strong><p>{model.train_samples} рейсов для обучения / {model.calibration_samples} для калибровки / {model.test_samples} для окончательного теста. Номинальный уровень 90%; фактическое покрытие на тесте — {fmt(model.test_interval_coverage*100)}%.</p><p>Ветер, волна и загрузка ограничены монотонно: их увеличение не уменьшает прогноз при прочих равных. Это предположение прототипа, не установленный закон перевозок.</p></div></div></div>
  {route.prediction.limitation&&<p className="data-caution">{route.prediction.limitation}</p>}
  {route.prediction.outside_training_range.length>0&&<p className="error-banner" role="alert">Часть признаков вне диапазона обучения: {route.prediction.outside_training_range.map(key=>model.explanation.factors.find(f=>f.key===key)?.label||key).join(', ')}. Прогноз особенно ненадёжен.</p>}
  <p className="insight-note">Важность глобальная: полосы не являются вкладом в задержку конкретного груза, не складываются в его прогноз и не доказывают причинность. История, погода и грузы синтетические; точность и диапазон не подтверждены реальными рейсами.</p>
  <p className="insight-note">CO₂ = масса × расстояние × коэффициент транспорта. Коэффициенты демонстрационные; порожние рейсы и жизненный цикл не учтены. Это не сертифицированная ESG-метрика.</p>
 </section>;
}
