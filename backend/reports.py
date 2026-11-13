"""Bounded, in-memory PDF export of an actual application snapshot. No secrets or HTML input."""
import hashlib
import io
import json
import threading
from datetime import datetime,timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak

FONT_DIR=Path(__file__).parent/'assets/fonts'
FONT_LOCK=threading.Lock()
CARGO_FIELDS=('id','name','owner','weight','container','status','route_id','updated_at','progress')


def snapshot_id(shipment,context):
    payload={'cargo':{key:shipment.get(key) for key in CARGO_FIELDS},'routes':shipment['alternatives'],
             'decision':shipment['recommendation'],'context':context}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def number(value,digits=1):
    if value is None:return 'Недостаточно данных'
    return f'{value:,.{digits}f}'.replace(',',' ').replace('.',',')


def timestamp(value):
    if not value:return 'Нет данных'
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M')+' МСК'


def render_report(shipment,context,metrics):
    with FONT_LOCK:
        if 'Caspian' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Caspian',str(FONT_DIR/'NotoSans-Regular.ttf')))
            pdfmetrics.registerFont(TTFont('Caspian-Bold',str(FONT_DIR/'NotoSans-Bold.ttf')))
            pdfmetrics.registerFontFamily('Caspian',normal='Caspian',bold='Caspian-Bold')
    styles={
        'body':ParagraphStyle('body',fontName='Caspian',fontSize=9,leading=13,textColor=colors.HexColor('#18384a'),spaceAfter=6),
        'small':ParagraphStyle('small',fontName='Caspian',fontSize=8,leading=11,textColor=colors.HexColor('#4f6878'),spaceAfter=5),
        'title':ParagraphStyle('title',fontName='Caspian-Bold',fontSize=22,leading=27,textColor=colors.HexColor('#008c87'),spaceAfter=10),
        'heading':ParagraphStyle('heading',fontName='Caspian-Bold',fontSize=12,leading=17,textColor=colors.HexColor('#18384a'),spaceBefore=10,spaceAfter=8),
        'cell':ParagraphStyle('cell',fontName='Caspian',fontSize=8,leading=11,alignment=TA_LEFT),
    }
    def p(text,style='body'):return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    def table(rows,widths):
        t=Table([[p(c,'cell') for c in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f5f3')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d9e6e8'))]))
        return t
    out=io.BytesIO();doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=44,
        title=f"CaspiFlow - {shipment['id']}",author='CaspiFlow',pageCompression=1)
    width=A4[0]-84;routes=shipment['alternatives'];decision=shipment['recommendation']
    current=next(r for r in routes if r['id']==shipment['route_id'])
    winner=next((r for r in routes if r['id']==decision['route_id']),None)
    generated=datetime.now(timezone.utc)
    story=[p('CaspiFlow','title'),p('Прогноз, маршруты и решение логиста','heading'),
        p('ДЕМОНСТРАЦИОННЫЙ ОТЧЁТ. Грузы и обучающая история синтетические. Не является навигационным или таможенным разрешением.','small'),
        p('Сформирован: '+timestamp(generated.isoformat()),'small'),p('Выбранный груз','heading'),
        table([['Параметр','Значение'],['Груз',shipment['id']+' | '+shipment['name']],['Отправитель',shipment['owner']],
               ['Масса / контейнер',number(shipment['weight'])+' т | '+str(shipment.get('container',''))],
               ['Статус / текущий путь',{'planned':'Запланирован','in_transit':'В пути','delayed':'Задержан','delivered':'Доставлен'}.get(shipment.get('status'),str(shipment.get('status')))+' | '+current['name']]], [125,width-125])]
    if context['mode']=='manual':
        story.append(p(f"Режим: ручная симуляция; синтетическая погода. Шторм: {context['storm']}%. Базовая загрузка: "+('из каждого маршрута' if context['port_load'] is None else str(context['port_load'])+'%')+'.'))
        story.append(p('Отправление: '+timestamp(shipment['departed_at'])+'. Общий момент отправления зафиксирован снимком груза.','small'))
    else:
        story.append(p('Режим: автопрогноз Open-Meteo. Новый план отправления, не остаток пути из текущей позиции.'))
        story.append(p('Отправление: '+timestamp(context['weather']['starts_at'])+'; погода получена '+timestamp(context['weather']['fetched_at'])+'.','small'))
    story.extend([p('Что делать логисту?','heading'),p(('Условная рекомендация: ' if decision['conditional'] else 'Сценарная рекомендация: ')+(winner['name'] if winner else 'недостаточно данных')),
                  p(decision['reason'],'small')])
    if winner:
        diffs=[]
        for label,key in [('Полное время, ч','total_hours'),('CO2, кг','co2_kg')]:
            value=None if winner[key] is None or current[key] is None else winner[key]-current[key]
            diffs.append(label+': '+number(value)+(' (вариант минус текущий)' if value is not None else ''))
        a,b=current['economics']['total_cost_usd'],winner['economics']['total_cost_usd']
        savings=None if a is None or b is None else round(a-b,2)
        story.append(p(' | '.join(diffs)))
        story.append(p('Потенциальная экономия: '+number(savings,2)+' USD. Плюс означает экономию, минус - доплату.','small'))
    story.append(p('Сравнение маршрутов','heading'))
    rows=[['Маршрут','Задержка, ч','Полное время, ч','ETA, МСК','Итого, USD','CO2, кг']]
    for r in routes:rows.append([r['name'],number(r['delay_hours']),number(r['total_hours']),timestamp(r['eta_at']).replace(' МСК',''),number(r['economics']['total_cost_usd'],2),number(r['co2_kg'],0)])
    story.extend([table(rows,[105,58,59,102,100,width-424]),
        p('Полное время = плановое время + ML-задержка. ETA = общий момент отправления + полное время. Все альтернативы сравниваются от одной точки отсчёта. Просмотр рекомендации не перенаправляет груз.','small'),PageBreak(),
        p('Параметры и проверяемость','title'),p('Входы существующей модели','heading')])
    rows=[['Маршрут','План, ч','Ветер, м/с','Волна, м','Загрузка, %','История, ч','Км / перегрузки']]
    for r in routes:
        x=r['prediction']['inputs']
        rows.append([r['name'],number(r['hours']),number(x['wind_m_s']) if x else 'Нет данных',number(x['wave_m']) if x else 'Нет данных',
                     number(x['port_load_percent']) if x else 'Нет данных',number(x['historical_delay_hours']) if x else 'Нет данных',
                     str(sum(s['km'] for s in r['segments']))+' / '+str(r['transfers'])])
    story.append(table(rows,[105,45,55,48,60,55,width-368]))
    settings=context['settings'];factors=context['emission_factors']
    story.extend([p('Экономика и метод выбора','heading'),p('Все тарифы демонстрационные, не рыночные. Перевозка = сумма (масса x км сегмента x тариф транспорта) + перегрузки x тариф перегрузки. Стоимость задержки = ML-часы x тариф простоя; итого = перевозка + задержка.','small'),
        p(f"Простой: {number(settings['delay_usd_per_hour'],2)} USD/ч; море: {number(settings['sea_usd_per_tkm'],3)}, ж/д: {number(settings['rail_usd_per_tkm'],3)}, авто: {number(settings['road_usd_per_tkm'],3)} USD/(т*км); перегрузка: {number(settings['transfer_usd'],2)} USD.",'small'),
        p(f"Веса выбора: время {number(settings['eta_weight']*100,0)}%, стоимость {number(settings['cost_weight']*100,0)}%, CO2 {number(settings['co2_weight']*100,0)}%. Минимум взвешенных нормированных показателей среди вариантов с полным прогнозом. Оценка зависит от состава сравниваемых вариантов.",'small'),
        p(f"CO2 = сумма (масса x км x коэффициент транспорта). Коэффициенты демонстрационные: море {number(factors['sea'],3)}, ж/д {number(factors['rail'],3)}, авто {number(factors['road'],3)} кг/(т*км). Это не сертифицированная ESG-оценка.",'small'),
        p('Источники и ограничения','heading'),p('Модель Random Forest '+metrics['version']+': MAE '+number(metrics['mae_hours'],2)+' ч, RMSE '+number(metrics['rmse_hours'],2)+' ч, R2 '+number(metrics['r2'],4)+' только на синтетическом test. Эти метрики не подтверждают точность на реальных рейсах.','small')])
    for r in routes:
        if r['prediction'].get('limitation'):story.append(p(r['name']+': '+r['prediction']['limitation'],'small'))
        if r['prediction'].get('outside_training_range'):story.append(p(r['name']+': входы вне обучения - '+', '.join(r['prediction']['outside_training_range'])+'.','small'))
    if context['mode']=='auto':
        story.append(p('Погода - модельный прогноз Open-Meteo, не измерения буя. Окна прохождения вычислены до ML-задержки; расписания и итеративный сдвиг окон не моделируются.','small'))
        for item in context['weather'].get('errors',[]):story.append(p('Ошибка источника '+item['source']+': '+item['message'],'small'))
        for note in context['weather'].get('spatial_notes',[]):story.append(p(note,'small'))
    else:story.append(p('Погода ручного режима, исходные грузы, загрузка портов и обучающая история синтетические. Сценарий шторма не является наблюдением реальной погоды.','small'))
    story.extend([p('Маршруты и расстояния схематичны. Нет GPS/AIS, проверки вместимости, реальных стыковок и государственной таможенной интеграции. Отсутствующие прогнозы оставлены неизвестными. Тип транспорта не входит в вектор ML; отдельной валидации суши нет.','small'),
        p('Источники: Open-Meteo Weather https://open-meteo.com/en/docs и Marine https://open-meteo.com/en/docs/marine-weather-api (CC BY 4.0; в ручном режиме не используются). Методика CaspiFlow: docs/ML_REPORT.md и docs/WEATHER_AND_OPERATIONS.md.','small'),
        p('Снимок расчёта: '+shipment['report_snapshot']+'. Это идентификатор согласованности, не электронная подпись.','small')])
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('Caspian',8);canvas.setFillColor(colors.HexColor('#607888'))
        canvas.drawString(42,26,'CaspiFlow | Демо-данные | '+shipment['id']);canvas.drawRightString(A4[0]-42,26,str(document.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
