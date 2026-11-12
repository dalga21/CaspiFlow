import { NextRequest, NextResponse } from 'next/server';
export const dynamic = 'force-dynamic';
async function proxy(req: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  const route = path.join('/');
  const allowed = req.method === 'GET' ? /^(dashboard|model|health|shipments\/CF-2026-\d{4})$/.test(route) : req.method === 'POST' && route === 'customs';
  if (!allowed) return NextResponse.json({detail:'Not found'}, {status:404});
  const host = req.headers.get('host');
  const localOrigins = ['http://localhost:3000', 'http://127.0.0.1:3000'];
  const expectedOrigin = process.env.APP_ORIGIN || `http://${host}`;
  const trustedOrigin = process.env.APP_ORIGIN ? expectedOrigin === process.env.APP_ORIGIN : localOrigins.includes(expectedOrigin);
  if (req.method === 'POST' && (!trustedOrigin || req.headers.get('origin') !== expectedOrigin)) return NextResponse.json({detail:'Запрос с другого сайта отклонён'}, {status:403});
  try {
    const headers: Record<string,string> = {'Content-Type':'application/json'};
    if (req.method === 'POST') {
      if (!process.env.CUSTOMS_API_KEY) return NextResponse.json({detail:'API не настроен'}, {status:503});
      headers['X-API-Key'] = process.env.CUSTOMS_API_KEY;
    }
    const body = req.method === 'POST' ? await req.text() : undefined;
    if (body && body.length > 8192) return NextResponse.json({detail:'Слишком большой запрос'}, {status:413});
    const response = await fetch(`${process.env.API_URL || 'http://127.0.0.1:8000'}/${route}${req.nextUrl.search}`, {method:req.method,headers,body,cache:'no-store',signal:AbortSignal.timeout(15000)});
    return new NextResponse(await response.text(), {status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  } catch { return NextResponse.json({detail:'Backend недоступен. Проверьте запуск FastAPI.'}, {status:502}); }
}
export const GET=proxy;
export const POST=proxy;
