'use client';
import {useEffect,useRef,useState} from 'react';
type Props={shipment:{id:string;report_snapshot?:string};mode:'manual'|'auto';storm?:number;portLoad?:number|null;disabled?:boolean;onRefresh:()=>void};
export default function ReportButton({shipment,mode,storm=0,portLoad=null,disabled=false,onRefresh}:Props){
 const controller=useRef<AbortController|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[stale,setStale]=useState(false);
 useEffect(()=>{setError('');setStale(false);setBusy(false);return()=>controller.current?.abort();},[shipment.id,shipment.report_snapshot,mode,storm,portLoad]);
 async function download(){
  if(!shipment.report_snapshot)return;
  controller.current?.abort();const active=new AbortController();controller.current=active;setBusy(true);setError('');setStale(false);
  const query=new URLSearchParams({mode,expected_snapshot:shipment.report_snapshot});
  if(mode==='manual'){query.set('storm',String(storm));if(portLoad!==null)query.set('port_load',String(portLoad));}
  try{
   const response=await fetch(`/api/reports/${shipment.id}?${query}`,{signal:active.signal});
   if(!response.ok){setStale(response.status===409);const payload=await response.json();throw new Error(typeof payload.detail==='string'?payload.detail:'Не удалось сформировать отчёт');}
   if(!response.headers.get('content-type')?.includes('application/pdf'))throw new Error('Сервер вернул неверный формат отчёта');
   const blob=await response.blob();if(active.signal.aborted)return;
   const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`CaspiFlow-${shipment.id}-${mode}${mode==='manual'?`-storm-${storm}`:''}.pdf`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){if(!active.signal.aborted)setError((e as Error).message);}finally{if(!active.signal.aborted)setBusy(false);}
 }
 return <div className="report-control"><button className="secondary" disabled={disabled||busy||!shipment.report_snapshot} onClick={download}>{busy?'Формируем PDF…':'Сформировать отчёт'}</button>{error&&<p className="report-error" role="alert">{error}{stale&&<button className="secondary" onClick={()=>{setError('');setStale(false);onRefresh();}}>Обновить расчёт</button>}</p>}</div>;
}
