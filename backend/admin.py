"""Local operator authentication. Passwords and bearer session tokens never enter audit."""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime,timezone
from typing import Literal
from fastapi import Cookie,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field,model_validator
from backend.settings import Settings,load_settings

COOKIE='caspiflow_admin'
SESSION_SECONDS=8*3600

def hash_password(password):
    salt=secrets.token_bytes(16)
    value=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32,maxmem=64*1024*1024)
    return f'scrypt$16384${salt.hex()}${value.hex()}'

def check_password(password,encoded):
    try:
        kind,n,salt,digest=encoded.split('$')
        if kind!='scrypt' or n!='16384':return False
        value=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32,maxmem=64*1024*1024)
        return secrets.compare_digest(value.hex(),digest)
    except (ValueError,TypeError):return False

class Login(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password:str=Field(min_length=1,max_length=256)

class Cargo(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True,allow_inf_nan=False)
    id:str=Field(pattern=r'^CF-2026-[0-9]{4}$')
    name:str=Field(min_length=2,max_length=100)
    owner:str=Field(min_length=2,max_length=100)
    weight:float=Field(gt=0,le=100000)
    route_id:Literal['direct','west','east']
    status:Literal['planned','in_transit','delayed','delivered']='planned'
    progress:float=Field(0,ge=0,le=1)
    container:str=Field(default='',max_length=40)
    @model_validator(mode='after')
    def status_progress(self):
        if self.status=='planned' and self.progress!=0:raise ValueError('Запланированный груз: прогресс должен быть 0')
        if self.status=='delivered' and self.progress!=1:raise ValueError('Доставленный груз: прогресс должен быть 1')
        return self

def register_admin(app,db,authorize):
    def audit(c,action,subject,details=None):
        c.execute('INSERT INTO audit(created_at,action,subject,details) VALUES (?,?,?,?)',
                  (datetime.now(timezone.utc).isoformat(),action,subject,json.dumps(details or {},ensure_ascii=False)))
    def session(token:str|None=Cookie(None,alias=COOKIE),_=Depends(authorize)):
        if not token or len(token)>256:raise HTTPException(401,'Требуется вход администратора')
        digest=hashlib.sha256(token.encode()).hexdigest()
        with db() as c:row=c.execute('SELECT expires_at FROM admin_sessions WHERE token_hash=?',(digest,)).fetchone()
        if not row or row[0]<=time.time():raise HTTPException(401,'Сессия отсутствует или истекла')
        return digest

    @app.post('/admin/login',dependencies=[Depends(authorize)])
    def login(data:Login,response:Response,request:Request,old:str|None=Cookie(None,alias=COOKIE)):
        encoded=os.environ.get('CASPIFLOW_ADMIN_PASSWORD_HASH')
        if not encoded:raise HTTPException(503,'Пароль администратора не настроен на сервере')
        now=time.time()
        # Serialize the rate check and password check to prevent parallel bypasses.
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM admin_attempts WHERE created_at<?',(now-300,))
            if c.execute('SELECT COUNT(*) FROM admin_attempts').fetchone()[0]>=5:
                raise HTTPException(429,'Слишком много попыток. Повторите через 5 минут.')
            if not check_password(data.password,encoded):
                c.execute('INSERT INTO admin_attempts(created_at) VALUES (?)',(now,))
                audit(c,'login_failed','admin')
                # Commit the failed attempt before raising outside the transaction.
                failed=True
            else:
                failed=False;token=secrets.token_urlsafe(48);digest=hashlib.sha256(token.encode()).hexdigest()
                c.execute('DELETE FROM admin_sessions WHERE expires_at<=?',(now,))
                if old:c.execute('DELETE FROM admin_sessions WHERE token_hash=?',(hashlib.sha256(old.encode()).hexdigest(),))
                c.execute('INSERT INTO admin_sessions VALUES (?,?,?)',(digest,now+SESSION_SECONDS,datetime.now(timezone.utc).isoformat()))
                c.execute('DELETE FROM admin_attempts');audit(c,'login','admin')
        if failed:raise HTTPException(401,'Неверный пароль')
        response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,samesite='strict',secure=os.environ.get('APP_ORIGIN','').startswith('https://'),path='/')
        response.headers['Cache-Control']='no-store'
        return {'authenticated':True,'expires_in':SESSION_SECONDS}

    @app.get('/admin/session')
    def session_info(_=Depends(session)):
        return {'authenticated':True}

    @app.post('/admin/logout')
    def logout(response:Response,digest=Depends(session)):
        with db() as c:c.execute('DELETE FROM admin_sessions WHERE token_hash=?',(digest,));audit(c,'logout','admin')
        response.delete_cookie(COOKIE,path='/',httponly=True,samesite='strict')
        return {'authenticated':False}

    @app.get('/admin/data')
    def data(_=Depends(session)):
        with db() as c:
            shipments=[json.loads(r[0]) for r in c.execute('SELECT data FROM shipments ORDER BY id')]
            declarations=[{**dict(r),'payload':json.loads(r['payload'])} for r in c.execute('SELECT * FROM customs ORDER BY created_at DESC')]
            logs=[dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')]
        return {'shipments':shipments,'declarations':declarations,'settings':load_settings(db).model_dump(),'audit':logs}

    @app.post('/admin/shipments')
    def create(cargo:Cargo,_=Depends(session)):
        item={**cargo.model_dump(),'updated_at':datetime.now(timezone.utc).isoformat()}
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM shipments WHERE id=?',(cargo.id,)).fetchone():raise HTTPException(409,'Груз с таким ID уже существует')
            c.execute('INSERT INTO shipments VALUES (?,?)',(cargo.id,json.dumps(item,ensure_ascii=False)))
            audit(c,'shipment_created',cargo.id,{'status':cargo.status,'route_id':cargo.route_id})
        return item

    @app.put('/admin/shipments/{shipment_id}')
    def update(shipment_id:str,cargo:Cargo,_=Depends(session)):
        if shipment_id!=cargo.id:raise HTTPException(422,'ID груза нельзя изменить')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT data FROM shipments WHERE id=?',(shipment_id,)).fetchone()
            if not row:raise HTTPException(404,'Груз не найден')
            previous=json.loads(row[0]);item={**previous,**cargo.model_dump()}
            # Keep the position snapshot timestamp: edits must not silently shift manual ETA.
            c.execute('UPDATE shipments SET data=? WHERE id=?',(json.dumps(item,ensure_ascii=False),shipment_id))
            audit(c,'shipment_updated',shipment_id,{'before':{k:previous.get(k) for k in Cargo.model_fields},'after':cargo.model_dump()})
        return item

    @app.put('/admin/settings')
    def settings(value:Settings,_=Depends(session)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute("SELECT value FROM settings WHERE key='operator'").fetchone()[0]
            c.execute("UPDATE settings SET value=? WHERE key='operator'",(value.model_dump_json(),))
            audit(c,'settings_updated','operator',{'before':json.loads(old),'after':value.model_dump()})
        return value.model_dump()
