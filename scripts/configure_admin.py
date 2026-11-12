#!/usr/bin/env python3
"""Set local admin password. --generate stores it only in a private ignored file."""
import argparse,getpass,os,secrets,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.admin import hash_password
parser=argparse.ArgumentParser();parser.add_argument('--generate',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[1];env=root/'.env'
content=env.read_text() if env.exists() else ''
if 'CASPIFLOW_ADMIN_PASSWORD_HASH=' in content and args.generate:
    print('Admin is already configured; no credentials changed.');sys.exit(0)
password=secrets.token_urlsafe(24) if args.generate else getpass.getpass('Новый пароль администратора (от 12 символов): ')
if len(password)<12:raise SystemExit('Пароль должен содержать не менее 12 символов')
if not args.generate and password!=getpass.getpass('Повторите пароль: '):raise SystemExit('Пароли различаются')
if not content:
    content='CUSTOMS_API_KEY='+secrets.token_urlsafe(36)+'\nAPI_URL=http://127.0.0.1:8000\n'
lines=[line for line in content.splitlines() if not line.startswith('CASPIFLOW_ADMIN_PASSWORD_HASH=')]
lines.append("CASPIFLOW_ADMIN_PASSWORD_HASH='"+hash_password(password)+"'")
fd=os.open(env,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:f.write('\n'.join(lines)+'\n')
env.chmod(0o600)
if args.generate:
    folder=root/'.runtime';folder.mkdir(exist_ok=True)
    target=folder/'admin-credentials.txt'
    fd=os.open(target,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(password+'\n')
    target.chmod(0o600)
    print('Generated private credentials in .runtime/admin-credentials.txt (0600); restart servers.')
else:
    (root/'.runtime/admin-credentials.txt').unlink(missing_ok=True)
    print('Password hash saved; restart servers. Existing sessions will be cleared on startup.')
