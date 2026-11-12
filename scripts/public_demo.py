#!/usr/bin/env python3
"""Isolated short-lived HTTPS demo. No local database or .env is copied."""
import argparse
import atexit
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import tarfile
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime/public-demo'
PYTHON = ROOT / 'backend/.venv/bin/python'
TUNNEL = ROOT / '.runtime/tools/cloudflared'
FRONTEND_PORT, BACKEND_PORT = 3010, 8010


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
    path.chmod(0o600)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def initialize():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o700)
    (STATE / 'data').mkdir(exist_ok=True)
    if not (STATE / 'secrets.json').exists():
        sys.path.insert(0, str(ROOT))
        from backend.admin import hash_password
        password = secrets.token_urlsafe(32)
        private_json(STATE / 'secrets.json', {
            'CUSTOMS_API_KEY': secrets.token_urlsafe(48),
            'CASPIFLOW_ADMIN_PASSWORD_HASH': hash_password(password),
        })
        p = STATE / 'admin-password.txt'
        p.write_text(password + '\n'); p.chmod(0o600)
    return json.loads((STATE / 'secrets.json').read_text())


def prepare():
    initialize()
    if not TUNNEL.is_file():
        raise SystemExit('Install official cloudflared into .runtime/tools/cloudflared first (see docs/PUBLIC_DEPLOYMENT.md).')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    source = STATE / 'releases' / sha
    if not source.exists():
        source.mkdir(parents=True)
        archive = STATE / 'source.tar'
        with archive.open('wb') as f:
            subprocess.run(['git', 'archive', sha], cwd=ROOT, stdout=f, check=True)
        with tarfile.open(archive) as f:
            f.extractall(source, filter='data')
        archive.unlink()
    env = os.environ.copy()
    for key in ('CUSTOMS_API_KEY', 'CASPIFLOW_ADMIN_PASSWORD_HASH', 'APP_ORIGIN', 'API_URL', 'CASPIFLOW_DB_PATH'):
        env.pop(key, None)
    env['NEXT_TELEMETRY_DISABLED'] = '1'
    with (STATE / 'build.log').open('w') as log:
        if not (source / 'frontend/node_modules/next').exists():
            subprocess.run(['npm', 'ci', '--no-audit', '--no-fund'], cwd=source / 'frontend', env=env, stdout=log, stderr=log, check=True)
        subprocess.run(['npm', 'run', 'build'], cwd=source / 'frontend', env=env, stdout=log, stderr=log, check=True)
    private_json(STATE / 'release.json', {'sha': sha, 'source': str(source)})
    print('Production release built:', sha[:12], flush=True)


def spawn(command, source, env, name):
    log = (STATE / (name + '.log')).open('a')
    process = subprocess.Popen(command, cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    log.close()
    return process


def wait_http(url, children, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(p.poll() is not None for p in children):
            raise RuntimeError('A demo process exited; inspect private logs in .runtime/public-demo/')
        try:
            response = httpx.get(url, timeout=3, follow_redirects=False)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Health check timed out: ' + url)


def run():
    configured = initialize()
    release = json.loads((STATE / 'release.json').read_text())
    source = Path(release['source'])
    children = []
    def cleanup():
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
        for p in children:
            try: p.wait(timeout=8)
            except subprocess.TimeoutExpired: p.kill()
        (STATE / 'supervisor.pid').unlink(missing_ok=True)
    atexit.register(cleanup)
    def stop(_sig, _frame): raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop);signal.signal(signal.SIGINT, stop)
    for port in (FRONTEND_PORT, BACKEND_PORT):
        with socket.socket() as s:
            try: s.bind(('127.0.0.1', port))
            except OSError: raise RuntimeError(f'Port {port} is occupied; no existing service was stopped')
    env = os.environ.copy()
    env.update(configured)
    env.update(NODE_ENV='production',NEXT_TELEMETRY_DISABLED='1',
               API_URL=f'http://127.0.0.1:{BACKEND_PORT}',
               CASPIFLOW_DB_PATH=str(STATE / 'data/caspiflow.sqlite'))
    # Only this dedicated Next port is published. No filesystem server or backend tunnel.
    log = STATE / 'tunnel.log';log.write_text('')
    children.append(spawn([str(TUNNEL),'tunnel','--no-autoupdate','--protocol','http2','--url',f'http://127.0.0.1:{FRONTEND_PORT}'],source,env,'tunnel'))
    origin = None
    for _ in range(60):
        if children[0].poll() is not None: raise RuntimeError('Tunnel failed; inspect tunnel.log')
        match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',log.read_text())
        if match: origin=match[0];break
        time.sleep(1)
    if not origin: raise RuntimeError('Cloudflare did not assign a URL within 60 seconds')
    env['APP_ORIGIN'] = origin
    children.append(spawn([str(PYTHON),'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',str(BACKEND_PORT),'--no-access-log','--no-proxy-headers'],source,env,'backend'))
    wait_http(f'http://127.0.0.1:{BACKEND_PORT}/health',children)
    children.append(spawn(['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',str(FRONTEND_PORT)],source / 'frontend',env,'frontend'))
    wait_http(f'http://127.0.0.1:{FRONTEND_PORT}/api/health',children)
    children.append(spawn(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],source,env,'awake'))
    # The hostname can exist before the tunnel is connected (initial HTTP 530).
    wait_http(origin + '/api/health', children, timeout=120)
    private_json(STATE / 'deployment.json', {'url':origin,'admin_url':origin+'/admin','sha':release['sha'],
        'database':str(STATE/'data/caspiflow.sqlite'),'source':str(source),'pid':os.getpid(),
        'started_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'hosting':'MacBook via Cloudflare Quick Tunnel'})
    while True:
        if any(p.poll() is not None for p in children): raise RuntimeError('A demo process exited; supervisor stopping all demo processes')
        time.sleep(2)


def start():
    initialize()
    pidfile = STATE / 'supervisor.pid'
    if pidfile.exists() and alive(int(pidfile.read_text())):
        status();return
    prepare()
    log=(STATE/'supervisor.log').open('a')
    p=subprocess.Popen([str(PYTHON),str(Path(__file__).resolve()),'run'],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    log.close();pidfile.write_text(str(p.pid))
    for _ in range(180):
        if p.poll() is not None: raise SystemExit('Startup failed. See .runtime/public-demo/supervisor.log')
        path=STATE/'deployment.json'
        if path.exists() and json.loads(path.read_text()).get('pid')==p.pid:
            status();return
        time.sleep(1)
    raise SystemExit('Startup still pending. Run status; see private logs. Do not start a second copy.')


def status():
    p=STATE/'supervisor.pid'
    print('Supervisor:', 'running' if p.exists() and alive(int(p.read_text())) else 'stopped')
    d=STATE/'deployment.json'
    if d.exists():
        data=json.loads(d.read_text());print('URL:',data['url']);print('Admin:',data['admin_url'])
    print('Private admin password file: .runtime/public-demo/admin-password.txt (never paste into chat)')


def shutdown():
    p=STATE/'supervisor.pid'
    if p.exists() and alive(int(p.read_text())):
        os.kill(int(p.read_text()),signal.SIGTERM)
        for _ in range(20):
            if not p.exists():break
            time.sleep(1)
    print('Public demo stopped. Its SQLite and secrets are retained. Local ports 3000/8000 were untouched.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','run','status','stop','prepare']);args=parser.parse_args()
    {'start':start,'run':run,'status':status,'stop':shutdown,'prepare':prepare}[args.action]()
