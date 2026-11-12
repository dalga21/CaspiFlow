'use client';
import {useState} from 'react';
export const numberFormat=(v:number|null|undefined,digits=1)=>v==null?'нет данных':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits}).format(v);
export const dateFormat=(v:string)=>new Date(v).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});

export function HourlyChart({title,unit,times,values,color='#078e86',threshold,emptyReason,onRetry,retrying=false}:{title:string;unit:string;times:string[];values:(number|null)[];color?:string;threshold?:number;emptyReason?:string;onRetry?:()=>void;retrying?:boolean}){
 values=values.map(v=>typeof v==='number'&&Number.isFinite(v)?v:null);
 const available=values.filter(v=>v!==null).length;
 const [hour,setHour]=useState(0);const max=Math.max(1,threshold||0,...values.filter((v):v is number=>v!==null));
 let d='';let gap=true;
 values.forEach((v,i)=>{if(v===null){gap=true;return;}d+=`${gap?'M':'L'}${35+i/Math.max(1,values.length-1)*640},${145-v/max*115} `;gap=false;});
 const selected=Math.min(hour,Math.max(0,values.length-1));
 return <section className="hourly-chart"><h3>{title}</h3>{available>0&&available<times.length&&<p className="chart-data-note">Доступно {available} из {times.length} часов. Пропуски показаны разрывами.</p>}{values.some(v=>v!==null)?<><div className="chart-axis"><span>0–{numberFormat(max)} {unit}</span><span>72 почасовые точки</span></div><svg viewBox="0 0 710 175" role="img" aria-label={`${title}, почасовые данные; пропуски показаны разрывами`}><line x1="35" x2="675" y1="145" y2="145" stroke="#cbdde1"/><text x="4" y="30">{numberFormat(max)}</text><text x="18" y="145">0</text>{threshold!==undefined&&<><line x1="35" x2="675" y1={145-threshold/max*115} y2={145-threshold/max*115} stroke="#b87629" strokeDasharray="5 5"/><text x="420" y={137-threshold/max*115}>опасный порог {threshold} {unit}</text></>}<path d={d} fill="none" stroke={color} strokeWidth="2.5"/><line x1={35+selected/Math.max(1,values.length-1)*640} x2={35+selected/Math.max(1,values.length-1)*640} y1="25" y2="145" stroke="#839ba6" strokeDasharray="3 3"/><text x="35" y="168">сейчас</text><text x="590" y="168">+71 час</text></svg><input type="range" min="0" max={Math.max(0,times.length-1)} value={selected} onChange={e=>setHour(Number(e.target.value))} aria-label={`Час графика ${title}`}/><p aria-live="polite">{times[selected]?dateFormat(times[selected]):'—'} МСК · {numberFormat(values[selected])} {values[selected]===null?'':unit}</p></>:<div className="empty"><strong>Недостаточно данных</strong><p>{emptyReason||'Нет данных для графика. Нулевые значения вместо пропусков не подставляются.'}</p>{onRetry&&<button className="secondary" disabled={retrying} onClick={onRetry}>{retrying?'Повторяем запрос…':'Повторить запрос'}</button>}</div>}</section>;
}

export function BarChart({title,unit,rows}:{title:string;unit:string;rows:{label:string;value:number|null}[]}){
 const max=Math.max(1,...rows.map(r=>r.value||0));
 return <section className="bar-chart"><h3>{title}</h3>{rows.length===0?<p className="empty">Нет данных</p>:rows.map((r,i)=><div className="bar-row" key={`${r.label}-${i}`}><div><span>{r.label}</span><strong>{numberFormat(r.value)} {r.value===null?'':unit}</strong></div><div className="factor-track"><span style={{width:r.value===null?'0':`${Math.max(0,r.value)/max*100}%`}}/></div></div>)}</section>;
}
