'use client';
import {useState} from 'react';
export default function AdminLogin(){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function login(e:React.FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError('');const form=e.currentTarget;const password=new FormData(form).get('password');try{const r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});const payload=await r.json();if(!r.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Не удалось войти');form.reset();window.location.replace('/admin');}catch(e){setError((e as Error).message);setBusy(false);}}
 return <main className="admin-login"><section className="panel"><div className="eyebrow">CASPIFLOW · ОПЕРАТОР</div><h1>Вход администратора</h1><p>Доступ проверяется сервером. Публичных тестовых учётных данных нет.</p><form onSubmit={login}><label>Пароль администратора<input name="password" type="password" autoComplete="current-password" required maxLength={256}/></label>{error&&<p className="error-banner" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy?'Проверяем…':'Войти'}</button></form><a href="/">Вернуться к логистике</a></section></main>;
}
