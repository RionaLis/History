#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 2: загрузка элементов-кандидатов и извлечение признаков -> features.jsonl"""
import json, re, sys
sys.path.insert(0, '/home/user/wd')
import wapi

CAND = '/home/user/wd/candidates.jsonl'
OUT = '/home/user/wd/features.jsonl'
CLASSES = '/home/user/wd/classes.json'

TIME_P = ('P571', 'P580', 'P585', 'P569')          # начало / основание / точка во времени / рождение
END_P = ('P576', 'P582', 'P570', 'P399')           # прекращение / конец / смерть
KEEP = ('P31', 'P279', 'P17', 'P361', 'P150', 'P30', 'P131', 'P155', 'P156',
        'P2348', 'P642', 'P527', 'P740', 'P1830', 'P1001')


def year_of(v):
    t = (v.get('time') or '')
    m = re.match(r'^([+-])(\d+)-(\d{2})-(\d{2})', t)
    if not m:
        return None
    y = int(m.group(2))
    return -y if m.group(1) == '-' else y


def extract(e):
    lab = e.get('labels', {})
    desc = e.get('descriptions', {})
    al = e.get('aliases', {})
    f = {
        'id': e['id'],
        'ru': (lab.get('ru') or {}).get('value'),
        'en': (lab.get('en') or {}).get('value'),
        'ru_desc': (desc.get('ru') or {}).get('value'),
        'en_desc': (desc.get('en') or {}).get('value'),
        'ru_al': [a['value'] for a in al.get('ru', [])],
        'en_al': [a['value'] for a in al.get('en', [])],
        'sitelinks': len(e.get('sitelinks', {}) or {}),
        'ruwiki': (e.get('sitelinks', {}) or {}).get('ruwiki', {}).get('title'),
        'enwiki': (e.get('sitelinks', {}) or {}).get('enwiki', {}).get('title'),
        'p31': [], 'p279': [], 'dates': [], 'ends': [], 'refs': [],
    }
    cl = e.get('claims', {}) or {}
    for p in ('P31',):
        for c in cl.get(p, [])[:6]:
            dv = (c.get('mainsnak') or {}).get('datavalue') or {}
            if dv.get('value', {}).get('id'):
                f['p31'].append(dv['value']['id'])
    for c in cl.get('P279', [])[:6]:
        dv = (c.get('mainsnak') or {}).get('datavalue') or {}
        if dv.get('value', {}).get('id'):
            f['p279'].append(dv['value']['id'])
    for p in TIME_P:
        for c in cl.get(p, [])[:4]:
            dv = (c.get('mainsnak') or {}).get('datavalue') or {}
            y = year_of(dv.get('value', {}))
            if y is not None:
                f['dates'].append([p, y, dv.get('value', {}).get('precision')])
    for p in END_P:
        for c in cl.get(p, [])[:4]:
            dv = (c.get('mainsnak') or {}).get('datavalue') or {}
            y = year_of(dv.get('value', {}))
            if y is not None:
                f['ends'].append([p, y, dv.get('value', {}).get('precision')])
    for p in KEEP[2:]:
        for c in cl.get(p, [])[:4]:
            dv = (c.get('mainsnak') or {}).get('datavalue') or {}
            v = dv.get('value')
            if isinstance(v, dict) and v.get('id'):
                f['refs'].append([p, v['id']])
    return f


def main():
    objs = [json.loads(l) for l in open(CAND, encoding='utf-8')]
    qids = []
    for o in objs:
        for c in o['cands']:
            qids.append(c['qid'])
    qids = list(dict.fromkeys(qids))
    print('уникальных кандидатов: %d' % len(qids), flush=True)

    feats = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        d = wapi.get(wapi.WD, {'action': 'wbgetentities', 'ids': '|'.join(chunk),
                               'props': 'labels|descriptions|aliases|claims|sitelinks',
                               'languages': 'ru|en'})
        if d:
            for q, e in (d.get('entities') or {}).items():
                if 'missing' in e:
                    continue
                feats[q] = extract(e)
        print('  ...%d/%d (получено %d)' % (min(i + 50, len(qids)), len(qids), len(feats)), flush=True)

    # метки классов (P31/P279) — для проверки типа
    cls = sorted({c for f in feats.values() for c in f['p31'] + f['p279']})
    print('классов: %d' % len(cls), flush=True)
    clsinfo = {}
    for i in range(0, len(cls), 50):
        d = wapi.get(wapi.WD, {'action': 'wbgetentities', 'ids': '|'.join(cls[i:i + 50]),
                               'props': 'labels|claims', 'languages': 'ru|en'})
        if d:
            for q, e in (d.get('entities') or {}).items():
                if 'missing' in e:
                    continue
                par = []
                for p in ('P31', 'P279'):
                    for c in (e.get('claims', {}) or {}).get(p, [])[:6]:
                        dv = (c.get('mainsnak') or {}).get('datavalue') or {}
                        if dv.get('value', {}).get('id'):
                            par.append(dv['value']['id'])
                clsinfo[q] = {'ru': (e.get('labels', {}).get('ru') or {}).get('value'),
                              'en': (e.get('labels', {}).get('en') or {}).get('value'),
                              'par': par}
        print('  классы ...%d/%d' % (min(i + 50, len(cls)), len(cls)), flush=True)
    # второй уровень родителей
    par2 = sorted({p for v in clsinfo.values() for p in v['par']} - set(clsinfo))
    for i in range(0, len(par2), 50):
        d = wapi.get(wapi.WD, {'action': 'wbgetentities', 'ids': '|'.join(par2[i:i + 50]),
                               'props': 'labels', 'languages': 'ru|en'})
        if d:
            for q, e in (d.get('entities') or {}).items():
                if 'missing' in e:
                    continue
                clsinfo[q] = {'ru': (e.get('labels', {}).get('ru') or {}).get('value'),
                              'en': (e.get('labels', {}).get('en') or {}).get('value'), 'par': []}
    with open(CLASSES, 'w', encoding='utf-8') as f:
        json.dump(clsinfo, f, ensure_ascii=False)
    with open(OUT, 'w', encoding='utf-8') as f:
        for q in qids:
            if q in feats:
                f.write(json.dumps(feats[q], ensure_ascii=False) + '\n')
    print('признаков сохранено: %d' % len(feats), flush=True)


if __name__ == '__main__':
    main()
