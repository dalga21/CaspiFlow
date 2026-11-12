import { NextRequest, NextResponse } from 'next/server';
export const dynamic = 'force-dynamic';
async function proxy(req: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  const route = path.join('/');
  const adminRead = /^(admin\/session|admin\/data)$/.test(route);
  const adminWrite = req.method==='POST' ? /^(admin\/login|admin\/logout|admin\/shipments)$/.test(route) : req.method==='PUT' && /^(admin\/settings|admin\/shipments\/CF-2026-[0-9]{4})$/.test(route);
  const allowed = req.method === 'GET' ? /^(dashboard|forecast|model|health|shipments\/CF-2026-[0-9]{4})$/.test(route)||adminRead : (req.method==='POST'&&route==='customs')||adminWrite;
  if (!allowed) return NextResponse.json({detail:'Not found'}, {status:404});
  const host = req.headers.get('host');
  const localOrigins = ['http://localhost:3000', 'http://127.0.0.1:3000'];
  const expectedOrigin = process.env.APP_ORIGIN || `http://${host}`;
  const trustedOrigin = process.env.APP_ORIGIN ? expectedOrigin === process.env.APP_ORIGIN : localOrigins.includes(expectedOrigin);
  if (req.method !== 'GET' && (!trustedOrigin || req.headers.get('origin') !== expectedOrigin)) return NextResponse.json({detail:'Запрос с другого сайта отклонён'}, {status:403});
  try {
    const headers: Record<string,string> = {'Content-Type':'application/json'};
    if (req.method !== 'GET'||route.startsWith('admin/')) {
      if (!process.env.CUSTOMS_API_KEY) return NextResponse.json({detail:'API не настроен'}, {status:503});
      headers['X-API-Key'] = process.env.CUSTOMS_API_KEY;
    }
    if(route.startsWith('admin/')) headers['Cookie']=req.headers.get('cookie')||'';
    const body = req.method !== 'GET' ? await req.text() : undefined;
    if (body && new TextEncoder().encode(body).byteLength > 8192) return NextResponse.json({detail:'Слишком большой запрос'}, {status:413});
    const response = await fetch(`${process.env.API_URL || 'http://127.0.0.1:8000'}/${route}${req.nextUrl.search}`, {method:req.method,headers,body,cache:'no-store',signal:AbortSignal.timeout(15000)});
    const outgoing=new Headers({'Content-Type':'application/json','Cache-Control':'no-store'});
    const cookie=response.headers.get('set-cookie');if(cookie)outgoing.set('set-cookie',cookie);
    return new NextResponse(await response.text(), {status:response.status,headers:outgoing});
  } catch { return NextResponse.json({detail:'Backend недоступен. Проверьте запуск FastAPI.'}, {status:502}); }
}
export const GET=proxy;
export const POST=proxy;

export const PUT=proxy;
