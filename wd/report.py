#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёты: XLSX для ручной проверки + сводка."""
import json, os, re, sys, collections
sys.path.insert(0, '/home/user/wd')
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

OUT = '/home/user/out'
os.makedirs(OUT, exist_ok=True)
FEAT = {json.loads(l)['id']: json.loads(l) for l in open('/home/user/wd/features.jsonl', encoding='utf-8')}
SC = {json.loads(l)['o']['id']: json.loads(l) for l in open('/home/user/wd/scored.jsonl', encoding='utf-8')}
DEC = [json.loads(l) for l in open('/home/user/wd/decisions.jsonl', encoding='utf-8')]
NEW = json.load(open('/home/user/History/data/index.json', encoding='utf-8'))

COLL = {'entity': 'сущность', 'event': 'событие', 'migration': 'миграция'}


def years(a, b):
    def y(v):
        if v is None:
            return ''
        return ('%d до н.э.' % -v) if v < 0 else '%d' % v
    if a == b or b is None:
        return y(a)
    return '%s — %s' % (y(a), y(b))


def link(q):
    return 'https://www.wikidata.org/wiki/%s' % q if q else ''


def norm(s):
    s = str(s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'`.,()\[\]:;!\?—–\-/]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def part_best(rec, part):
    """Лучший кандидат для одной части сборного названия."""
    sc = SC.get(rec['id'])
    if not sc:
        return None
    best = None
    pn = norm(part)
    for c in sc['cands']:
        f = FEAT.get(c['qid'])
        if not f:
            continue
        for v in [f.get('ru'), f.get('ruwiki'), f.get('en')] + (f.get('ru_al') or []):
            if v and norm(v) == pn:
                s = c['score'] + 3
                if not best or s > best[1]:
                    best = (c, s)
                break
        else:
            for v in [f.get('ru'), f.get('en')]:
                if v and (pn.startswith(norm(v)) or norm(v).startswith(pn)) and len(pn) >= 4:
                    if not best or c['score'] > best[1]:
                        best = (c, c['score'])
    return best[0] if best else None


wb = Workbook()
HDR = Font(bold=True, color='FFFFFF')
FILL = PatternFill('solid', fgColor='4A5568')
WRAP = Alignment(vertical='top', wrap_text=True)


def sheet(name, headers, rows, widths):
    ws = wb.create_sheet(name)
    ws.append(headers)
    for i, c in enumerate(ws[1], 1):
        c.font = HDR
        c.fill = FILL
        c.alignment = Alignment(vertical='center', wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    return ws


LINK = json.load(open('/home/user/wd/linkage.json', encoding='utf-8'))
auto = [r for r in DEC if r['decision'] == 'авто']
rev = [r for r in DEC if r['decision'] == 'проверка']
rev.sort(key=lambda r: -(r['score'] or -99))
none = [r for r in rev if not r['qid']]

# ---------- 1. Присвоено ----------
rows = []
for r in sorted(auto, key=lambda x: (x['coll'], x['name'])):
    f = FEAT[r['qid']]
    rows.append([COLL[r['coll']], r['id'], r['name'], r['type'], years(r['start'], r['end']),
                 r['qid'], f.get('ru') or '', f.get('ruwiki') or '', f.get('en') or '',
                 (f.get('ru_desc') or f.get('en_desc') or '')[:120], r['score'],
                 {'keep': 'без изменений', 'replace': 'ЗАМЕНЕНО', 'propose': 'предложено (не применено)',
                  'no_ru': 'нет русской метки'}[r['name_action']],
                 r['new_name'] or '', link(r['qid']), r['path']])
sheet('1. Присвоено (авто)', ['тип объекта', 'id', 'название в базе', 'тип', 'годы', 'Wikidata ID',
                              'русская метка WD', 'статья ру-вики', 'англ. метка WD', 'описание WD',
                              'балл', 'русское название', 'новое название', 'ссылка', 'файл'],
      rows, [11, 24, 34, 15, 20, 12, 26, 26, 22, 40, 6, 20, 26, 34, 40])

# ---------- 2. На проверку ----------
rows = []
for r in rev:
    c = r['cands'][0] if r['cands'] else None
    f = FEAT[c['qid']] if c else {}
    second = r['cands'][1] if len(r['cands']) > 1 else None
    rows.append([COLL[r['coll']], r['id'], r['name'], r['type'], years(r['start'], r['end']),
                 (c['qid'] if c else ''), (f.get('ru') or ''), (f.get('ruwiki') or ''),
                 (f.get('en') or ''), (f.get('ru_desc') or f.get('en_desc') or '')[:120],
                 r['score'] or '',
                 ('%s «%s» (%.1f)' % (second['qid'], second['ru'] or second['en'], second['score'])) if second else '',
                 '; '.join(r['reasons']), link(c['qid']) if c else '', r['path']])
sheet('2. На ручную проверку', ['тип объекта', 'id', 'название в базе', 'тип', 'годы',
                                'лучший кандидат', 'русская метка WD', 'статья ру-вики', 'англ. метка WD',
                                'описание WD', 'балл', 'конкурент', 'почему спорно', 'ссылка', 'файл'],
      rows, [11, 24, 34, 15, 20, 14, 26, 26, 22, 40, 6, 30, 60, 34, 40])

# ---------- 3. Русские названия ----------
rows = []
for r in DEC:
    if r['name_action'] in ('—', None):
        continue
    f = FEAT.get(r['qid']) or {}
    rows.append([{'keep': 'оставлено', 'replace': 'ЗАМЕНЕНО', 'propose': 'предложено',
                  'no_ru': 'нет в Wikidata'}[r['name_action']],
                 COLL[r['coll']], r['id'], r['name'], r['new_name'] or '', r['qid'] or '',
                 f.get('ru') or '', f.get('ruwiki') or '',
                 ', '.join((f.get('ru_al') or [])[:4]), r['name_reason'], r['path']])
MANUAL = [
    ('hominin_robustus', 'Парантроп массивный',
     'в Wikidata русской метки нет; название по русскоязычным источникам (Антропогенез.ру, BBC Russian, N+1). '
     'Вариант: «Парантроп робустус» — подтвердите'),
    ('hominin_naledi', 'Хомо наледи',
     'в Wikidata метка латинская; взято из русских вариантов (aliases) Wikidata. '
     'Варианты: «Человек из Диналеди» (так в ру-вики в списке рода Люди), «Человек наледи» — подтвердите'),
]
byid = {r['id']: r for r in DEC}
for oid, newname, note in MANUAL:
    r = byid[oid]
    f = FEAT.get(r['qid']) or {}
    rows.append(['ЗАМЕНЕНО', COLL[r['coll']], r['id'], r['name'], newname, r['qid'] or '',
                 f.get('ru') or '', f.get('ruwiki') or '', ', '.join((f.get('ru_al') or [])[:4]),
                 note, r['path']])

order = {'ЗАМЕНЕНО': 0, 'предложено': 1, 'нет в Wikidata': 2, 'оставлено': 3}
rows.sort(key=lambda x: (order[x[0]], x[2]))
sheet('3. Русские названия', ['что сделано', 'тип объекта', 'id', 'было', 'стало / предложение',
                              'Wikidata ID', 'русская метка WD', 'статья ру-вики', 'варианты WD (aliases)',
                              'комментарий', 'файл'],
      rows, [16, 11, 24, 34, 34, 12, 24, 24, 40, 52, 40])

# ---------- 4. Сборные объекты ----------
rows = []
for r in DEC:
    sc = SC.get(r['id'])
    if not sc or not sc['composite']:
        continue
    for i, p in enumerate(r['parts']):
        b = part_best(r, p)
        f = FEAT.get(b['qid']) if b else {}
        rows.append([COLL[r['coll']], r['id'] if i == 0 else '', r['name'] if i == 0 else '',
                     p, (b['qid'] if b else ''), (f.get('ru') or ''), (f.get('ruwiki') or ''),
                     (f.get('ru_desc') or f.get('en_desc') or '')[:100],
                     (b['score'] if b else ''), link(b['qid']) if b else '', r['path'] if i == 0 else ''])
sheet('4. Сборные (нужно решение)', ['тип объекта', 'id', 'название в базе', 'часть названия',
                                     'возможный QID', 'русская метка WD', 'статья ру-вики', 'описание WD',
                                     'балл', 'ссылка', 'файл'],
      rows, [11, 24, 36, 32, 14, 26, 26, 40, 6, 34, 40])

# ---------- 5. Ничего не найдено ----------
rows = []
for r in none:
    rows.append([COLL[r['coll']], r['id'], r['name'], r['type'], years(r['start'], r['end']),
                 (r['summary'] if 'summary' in r else '')[:140], r['path']])
sheet('5. Кандидатов не найдено', ['тип объекта', 'id', 'название в базе', 'тип', 'годы', 'описание', 'файл'],
      rows, [11, 26, 40, 16, 20, 70, 42])

# ---------- 6. Карта <-> таблица ----------
def _norm(s):
    return norm(s)


def _match(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    return (len(a) >= 6 and b.startswith(a)) or (len(b) >= 6 and a.startswith(b))


import json as _json
GEO = _json.load(open('/home/user/History/assets/map/data/events.geojson', encoding='utf-8'))
MNAME = _json.load(open('/home/user/wd/map_names.json', encoding='utf-8'))
contour = set()
for _d in MNAME.values():
    for _k in _d:
        if _norm(_k):
            contour.add(_norm(_k))
rows = []
for f in GEO['features']:
    pr = f['properties']
    t = _norm(pr.get('title'))
    hit = next((e for e in NEW['events'] if _match(_norm(e['name']), t)), None)
    rows.append([pr.get('year'), pr.get('title'), pr.get('kind'),
                 pr.get('content') or '', hit['id'] if hit else '',
                 (hit['name'] if hit else ''), ((hit.get('wikidata') or '') if hit else ''),
                 'ДА' if hit else 'НЕТ — точка не связана с базой',
                 '%.5f, %.5f' % (f['geometry']['coordinates'][1], f['geometry']['coordinates'][0])])
rows.sort(key=lambda r: (r[0] if r[0] is not None else 0))
sheet('6. Точки событий на карте', ['год', 'название точки на карте', 'тип', 'привязка к content/*.md',
                                    'id события в базе', 'название в базе', 'wikidata', 'связь', 'координаты'],
      rows, [8, 40, 12, 30, 24, 34, 12, 32, 20])

# контуры стран/империй на карте vs сущности таблицы
rows = []
for e in NEW['entities']:
    if e['type'] not in ('state', 'empire', 'colony', 'polity'):
        continue
    keys = [_norm(e['name'])] + [_norm(a) for a in (e.get('aliases') or [])]
    hit = next((c for k in keys if len(k) > 2 for c in contour if _match(k, c)), None)
    rows.append([e['id'], e['name'], e['type'], years(e['start'], e['end']), e.get('wikidata') or '',
                 hit or '', 'ДА' if hit else 'нет контура по названию'])
rows.sort(key=lambda r: (r[6], r[1]))
sheet('7. Контур карты у сущности', ['id', 'название в базе', 'тип', 'годы', 'wikidata',
                                     'название контура OHM', 'находится ли контур'],
      rows, [24, 38, 12, 22, 12, 34, 26])

# ---------- 0. Сводка ----------
ws = wb.active
ws.title = '0. Сводка'
tot = collections.Counter(r['coll'] for r in DEC)
a = collections.Counter(r['coll'] for r in auto)
comp = sum(1 for r in SC.values() if r['composite'])
lines = [
    ['Wikidata ID и русские названия — итоги автоматической сверки', ''],
    ['', ''],
    ['Всего объектов в базе (entities + events + migrations)', len(DEC)],
    ['  сущности (гоминины, культуры, народы, государства, империи, колонии)', tot['entity']],
    ['  события', tot['event']],
    ['  линии миграций и распространения технологий', tot['migration']],
    ['', ''],
    ['Wikidata ID присвоен автоматически (записан в файлы)', len(auto)],
    ['  сущности', a['entity']],
    ['  события', a['event']],
    ['  миграции', a['migration']],
    ['Отправлено на ручную проверку', len(rev)],
    ['  из них сборные названия (несколько предметов в одном)', comp],
    ['  из них кандидатов не найдено вовсе', len(none)],
    ['', ''],
    ['Русские названия', ''],
    ['  заменено на русское (было латинское/иное)', sum(1 for r in DEC if r['name_action'] == 'replace')],
    ['  оставлено как есть (уже совпадает с Wikidata)', sum(1 for r in DEC if r['name_action'] == 'keep')],
    ['  предложено на ваше решение', sum(1 for r in DEC if r['name_action'] == 'propose')],
    ['  в Wikidata нет русской метки', sum(1 for r in DEC if r['name_action'] == 'no_ru')],
    ['', ''],
    ['Связка «карта ↔ таблица» (проверка)', ''],
    ['  сущностей, у которых находится контур на карте (было)', LINK['before']],
    ['  сущностей, у которых находится контур на карте (стало)', LINK['after']],
    ['  из них «географических» типов state/empire/colony/polity', '%d из %d (было %d)' % (LINK['geo_after'], LINK['geo_total'], LINK['geo_before'])],
    ['  точек событий на карте всего', len(GEO['features'])],
    ['  из них связаны с событием в базе', LINK['ev_linked']],
    ['  из них НЕ связаны (висят только на карте)', LINK['ev_orphan']],
    ['  в тайлах OpenHistoricalMap нет свойства wikidata — связь только по названию', ''],
    ['', ''],
    ['Как работать с листом «2. На ручную проверку»', ''],
    ['  строки отсортированы по убыванию балла: сверху — почти наверняка верные', ''],
    ['  «лучший кандидат» — то, что нашёл скрипт; колонка «почему спорно» — причина', ''],
    ['  чтобы принять: впишите wikidata: "Q…" во фронтматтер файла из колонки «файл»', ''],
    ['  и пересоберите индекс: python3 tools/build.py', ''],
]
for row in lines:
    ws.append(row)
ws['A1'].font = Font(bold=True, size=14)
for r in (3, 8, 12, 16, 22):
    ws.cell(row=r, column=1).font = Font(bold=True)
ws.column_dimensions['A'].width = 68
ws.column_dimensions['B'].width = 14

wb.save(os.path.join(OUT, 'wikidata-сверка.xlsx'))
print('XLSX записан:', os.path.join(OUT, 'wikidata-сверка.xlsx'))
print('листов:', len(wb.sheetnames), wb.sheetnames)
