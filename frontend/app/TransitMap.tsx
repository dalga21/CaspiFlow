'use client';
import {useState} from 'react';
import {MapContainer,TileLayer,Polyline,CircleMarker,Popup,Polygon,Tooltip} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import type {Dashboard,Shipment} from './types';
const sea:[number,number][]=[[46.9,49.2],[46.3,51.5],[44.7,51.8],[43.3,50.4],[41.8,52.6],[41.0,53.1],[39.8,53.6],[38,53.7],[36.8,53.2],[36.7,51],[37.4,49.2],[38.8,48.9],[40.1,50.1],[41.2,49.1],[42.9,47.6],[44.7,46.8],[46.4,48.3]];
export default function TransitMap({data,selected,onSelect,routeId,storm}:{data:Dashboard;selected:Shipment;onSelect:(id:string)=>void;routeId:string;storm:number}){
 const [tilesUnavailable,setTilesUnavailable]=useState(false);
 const port=(id:string)=>data.ports.find(p=>p.id===id)!;
 const route=selected.alternatives.find(r=>r.id===routeId)||selected.route;
 const points=route.ports.map(id=>[port(id).lat,port(id).lon] as [number,number]);
 return <MapContainer center={[41.7,50.5]} zoom={5} minZoom={4} maxZoom={9} scrollWheelZoom={false} className="transit-map" aria-label="Карта каспийских грузовых маршрутов">
  <Polygon positions={sea} pathOptions={{fillColor:'#b8d8e4',fillOpacity:0.65,color:'#8eb9c9',weight:1}} />
  <TileLayer eventHandlers={{tileerror:()=>setTilesUnavailable(true)}} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
  {selected.alternatives.filter(r=>r.id!==route.id).map(r=><Polyline key={r.id} positions={r.ports.map(id=>[port(id).lat,port(id).lon])} pathOptions={{color:'#8b9eb3',weight:2,dashArray:'5 7',opacity:0.65}} />)}
  <Polyline positions={points} pathOptions={{color:'#057c85',weight:4,opacity:.9}} />
  {selected.alternatives.flatMap(r=>r.hazard_legs.map((leg,i)=><Polyline key={`hazard-${r.id}-${i}`} positions={leg.map(id=>[port(id).lat,port(id).lon])} pathOptions={{color:'#d6752c',weight:6,dashArray:'8 8',opacity:.85}}><Tooltip>Условно опасный морской участок · {r.name}. Синтетический сценарий, не запрет навигации.</Tooltip></Polyline>))}
  {storm>0&&<CircleMarker center={[41.8,50.8]} radius={30+storm*.5} pathOptions={{color:'#ec8d35',fillColor:'#f9ae52',fillOpacity:.18,weight:1,dashArray:'5 5'}}><Tooltip>Сценарий шторма · {storm}%</Tooltip></CircleMarker>}
  {data.ports.map(p=><CircleMarker key={p.id} center={[p.lat,p.lon]} radius={6} pathOptions={{color:'white',weight:2,fillColor:'#183e53',fillOpacity:1}}><Tooltip permanent direction="right" offset={[7,0]}>{p.name}</Tooltip><Popup><strong>{p.name}</strong><br/>{p.country}<br/>Загрузка: {p.load}% (базовый снимок; синтетика)</Popup></CircleMarker>)}
  {data.shipments.map(s=>{
   const vertices=s.route.ports.map(id=>port(id));
   const distances=vertices.slice(1).map((p,i)=>Math.hypot((p.lat-vertices[i].lat), (p.lon-vertices[i].lon)*Math.cos(p.lat*Math.PI/180)));
   let remaining=s.progress*distances.reduce((a,b)=>a+b,0),index=0;
   while(index<distances.length-1&&remaining>distances[index]){remaining-=distances[index];index++;}
   const a=vertices[index],b=vertices[index+1],fraction=distances[index]?remaining/distances[index]:0;
   return <CircleMarker key={s.id} center={[a.lat+(b.lat-a.lat)*fraction,a.lon+(b.lon-a.lon)*fraction]} radius={s.id===selected.id?10:7} pathOptions={{color:'white',weight:3,fillColor:s.id===selected.id?'#03a99b':'#63829b',fillOpacity:1}} eventHandlers={{click:()=>onSelect(s.id)}}><Tooltip>{s.id} · {s.name}</Tooltip></CircleMarker>
  })}
  {tilesUnavailable&&<div className="tile-status" role="status">Подложка недоступна · показана локальная схема Каспия</div>}
 </MapContainer>;
}
