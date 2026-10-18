#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 4: улучшенный скоринг -> scored.jsonl (с флагами на ручную проверку)."""
import json, math, re, sys, difflib, collections
sys.path.insert(0, '/home/user/wd')
from phase1 import parts_of, stripped

FEAT = {json.loads(l)['id']: json.loads(l) for l in open('/home/user/wd/features.jsonl', encoding='utf-8')}
CLS = json.load(open('/home/user/wd/classes.json', encoding='utf-8'))
LATIN = re.compile(r'^[A-Za-z][A-Za-z .\'\-]*$')
QUAL = ('западн', 'восточн', 'северн', 'южн', 'ранн', 'поздн', 'древн', 'верхн', 'нижн',
        'велик', 'мал', 'перв', 'втор', 'треть', 'средн', 'нов', 'стар')
DISAMB = ('страница значений', 'disambiguation', 'значения в проекте Викимедиа')


def norm(s):
    s = str(s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'`.,()\[\]:;!\?—–\-/]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


STOP = {'империя','царство','государство','держава','культура','период','эпоха','древний','древняя',
        'республика','ханство','каганат','султанат','халифат','колония','владения','история','народ',
        'the','of','and','empire','kingdom','state','period','ancient','dynasty','династия'}


def toks(s):
    return set(t for t in norm(s).split() if len(t) > 2)


def jac(a, b):
    A, B = toks(a) - STOP, toks(b) - STOP
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def fuzzy(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if len(a) < 4 or len(b) < 4:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def class_text(f):
    parts = [f.get('ru_desc') or '', f.get('en_desc') or '', f.get('ru') or '', f.get('en') or '',
             f.get('ruwiki') or '', f.get('enwiki') or '']
    seen = set()
    for c in (f.get('p31') or []) + (f.get('p279') or []):
        for q in [c] + (CLS.get(c, {}).get('par') or []):
            if q in seen:
                continue
            seen.add(q)
            info = CLS.get(q, {})
            parts += [info.get('ru') or '', info.get('en') or '']
    return ' '.join(p for p in parts if p).lower()


EXPECT = json.load(open('/home/user/wd/expect.json', encoding='utf-8'))
BAD = json.load(open('/home/user/wd/bad.json', encoding='utf-8'))
HUMAN, LANG_CLS = 'Q5', ('Q34770', 'Q315', 'Q4917106', 'Q1970428')


def expect_group(o):
    t = o['type']
    if t.startswith('event:'):
        return 'event'
    if t.startswith('migration:'):
        return 'migration'
    return t if t in EXPECT else 'state'


def name_targets(f, is_lat):
    """(строка, метка, вес-за-точное-совпадение)"""
    t = [(f.get('ru'), 'ru_label', 4.0 if not is_lat else 2.0)]
    if f.get('ruwiki'):
        t.append((f.get('ruwiki'), 'ruwiki', 4.0 if not is_lat else 2.0))
    t.append((f.get('en'), 'en_label', 4.0 if is_lat else 1.8))
    if f.get('enwiki'):
        t.append((f.get('enwiki'), 'enwiki', 3.8 if is_lat else 1.6))
    for a in f.get('ru_al') or []:
        t.append((a, 'ru_alias', 3.0 if not is_lat else 1.6))
    for a in f.get('en_al') or []:
        t.append((a, 'en_alias', 2.6 if is_lat else 1.2))
    return t


def name_score(o, f):
    name = o['name']
    is_lat = bool(LATIN.match(name.strip()))
    n = norm(name)
    best, why = 0.0, '—'
    for val, tag, w in name_targets(f, is_lat):
        v = norm(val)
        if not v or len(v) < 2:
            continue
        s = 0.0
        if v == n:
            s = w
        elif len(v) >= 6 and (n.startswith(v) or v.startswith(n)):
            s = w * 0.6
        else:
            j, fz = jac(name, val), fuzzy(name, val)
            s = w * max(0.5 * j / 0.9 if j >= 0.4 else 0.0, 0.62 * (fz - 0.75) / 0.25 if fz >= 0.78 else 0.0)
        for a in o.get('aliases') or []:
            if val and norm(a) == v and len(norm(a)) > 3:
                s = max(s, w * 0.8)
                tag += '+alias'
        if s > best:
            best, why = s, '%s=«%s»' % (tag, val)
    return best, why, is_lat


def src_score(c, is_lat):
    s, why = 0.0, []
    for v in c['votes']:
        src = v.split(':', 1)[0]
        rank = int(v.rsplit('#', 1)[1])
        w = {'wpp_ru': (3.0, 1.2), 'wpp_en': (3.0 if is_lat else 1.6, 1.0),
             'wdft': (2.2, 1.1), 'wsrch': (1.4, 0.7), 'wb_ru': (1.3, 0.65), 'wb_en': (1.3, 0.65)}.get(src, (0, 0))
        got = w[0] if rank == 0 else (w[1] if rank == 1 else 0.25)
        if got > s:
            s = got
        if rank == 0 and got >= 1.3:
            why.append(src)
    return s, ','.join(why) or '—'


def date_span_best(f, a, b, slack):
    """Выбираем наиболее подходящую под наш диапазон дату (у элемента их бывает несколько)."""
    ds = [y for _p, y, _pr in (f.get('dates') or [])]
    es = [y for _p, y, _pr in (f.get('ends') or [])]
    allv = ds + es
    if not allv:
        return None, None, 0.0, 'дат в Wikidata нет'
    st = min(ds) if ds else None
    en = max(es) if es else None
    # если хоть одна дата попадает в наш интервал (со slack) — считаем совместимой
    inside = [y for y in allv if (a - slack) <= y <= (b + slack)]
    if st is not None and en is not None:
        ok = not (en < a - slack or st > b + slack)
        if ok:
            return st, en, 2.0, 'wd %s…%s ⊂ наш %s…%s' % (st, en, a, b)
        if inside:
            return st, en, 0.6, 'wd %s…%s частично (есть %s)' % (st, en, inside[:2])
        return st, en, -3.0, 'wd %s…%s ✗ наш %s…%s' % (st, en, a, b)
    v = inside[0] if inside else min(allv, key=lambda y: min(abs(y - a), abs(y - b)))
    if inside:
        return st, en, 2.0, 'wd %s ∈ наш %s…%s' % (v, a, b)
    near = min(abs(v - a), abs(v - b))
    if near <= 3 * slack:
        return st, en, -0.5, 'wd %s рядом с %s…%s' % (v, a, b)
    return st, en, -2.5, 'wd %s ✗ наш %s…%s' % (v, a, b)


def score(o, c):
    f = FEAT.get(c['qid'])
    if not f:
        return None
    br, flags = [], []
    nm, why_name, is_lat = name_score(o, f)
    br.append(('name', round(nm, 2), why_name))
    s, why_src = src_score(c, is_lat)
    br.append(('src', round(s, 2), why_src))
    sl = min(1.5, 0.8 * math.log10(1 + (f.get('sitelinks') or 0)))
    br.append(('sitelinks', round(sl, 2), str(f.get('sitelinks') or 0)))

    ct = class_text(f)
    grp = expect_group(o)
    hitk = [k for k in EXPECT[grp].split() if k in ct]
    t, why_t = 0.0, ''
    if HUMAN in (f.get('p31') or []):
        t -= 5.0; why_t = 'человек (Q5)'; flags.append('это персона, а не объект базы')
    for b_ in BAD:
        if b_ in ct:
            t -= 6.0; why_t = 'чёрный список: «%s»' % b_; flags.append('похоже на посторонний элемент: ' + b_); break
    if any(x in LANG_CLS for x in (f.get('p31') or [])) and grp in ('people', 'state', 'culture', 'empire', 'polity', 'colony'):
        t -= 2.0; why_t = (why_t + '; ' if why_t else '') + 'это язык'
        flags.append('элемент про язык')
    for dg in DISAMB:
        if dg in ct:
            t -= 8.0; flags.append('страница неоднозначности')
            why_t = (why_t + '; ' if why_t else '') + 'disambig'
    if hitk:
        t += min(2.0, 0.7 * len(hitk))
        why_t = (why_t + '; ' if why_t else '') + 'класс: ' + ','.join(hitk[:3])
    else:
        t -= 1.0
        why_t = (why_t + '; ' if why_t else '') + 'класс не похож на «%s»' % grp
        flags.append('класс элемента не совпадает с типом «%s»' % o['type'])
    br.append(('type', round(t, 2), why_t or '—'))

    a = o['start'] if o['start'] is not None else o['end']
    b = o['end'] if o['end'] is not None else o['start']
    span = abs(b - a) if (a is not None and b is not None) else 0
    slack = max(80.0, 0.18 * span)
    st, en, d, why_d = date_span_best(f, a, b, slack)
    if d < 0:
        flags.append('датировки расходятся')
    br.append(('date', round(d, 2), why_d))

    # квалификаторы: «Западная Хань» != «империя Хань»
    nl = norm(o['name'])
    ours_q = [q for q in QUAL if q in nl]
    lbl = norm((f.get('ru') or '') + ' ' + (f.get('ruwiki') or '') + ' ' + (f.get('en') or ''))
    if ours_q:
        if not any(q in lbl for q in ours_q):
            t2 = -1.4
            flags.append('в названии есть уточнение «%s», а у элемента — нет (возможно, нужен более частный элемент)'
                         % ours_q[0])
        else:
            t2 = 0.6
    else:
        theirs_q = [q for q in QUAL if q in norm(f.get('ru') or '')]
        t2 = -0.7 if theirs_q else 0.0
        if theirs_q:
            flags.append('у элемента есть уточнение «%s», а в нашем названии — нет' % theirs_q[0])
    br.append(('qualifier', round(t2, 2), ','.join(ours_q) or '—'))

    total = round(sum(x[1] for x in br), 2)
    return {'qid': c['qid'], 'score': total, 'br': br, 'flags': flags,
            'ru': f.get('ru'), 'en': f.get('en'), 'ruwiki': f.get('ruwiki'), 'enwiki': f.get('enwiki'),
            'ru_desc': f.get('ru_desc'), 'en_desc': f.get('en_desc'), 'sitelinks': f.get('sitelinks'),
            'p31': f.get('p31'), 'votes': c['votes'][:8], 'is_lat': is_lat}


def main():
    out = []
    for line in open('/home/user/wd/candidates.jsonl', encoding='utf-8'):
        o = json.loads(line)
        scored = [s for s in (score(o, c) for c in o['cands']) if s]
        scored.sort(key=lambda x: -x['score'])
        parts = parts_of(o['name'])
        out.append({'o': o, 'cands': scored[:8], 'parts': parts, 'composite': bool(parts)})
    with open('/home/user/wd/scored.jsonl', 'w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    band = collections.Counter()
    for r in out:
        s = r['cands'][0]['score'] if r['cands'] else -99
        band['>=9' if s >= 9 else ('8-9' if s >= 8 else ('7-8' if s >= 7 else ('6-7' if s >= 6 else ('4-6' if s >= 4 else '<4'))))] += 1
    print('полосы лучшего балла:', band.most_common())
    print('сборных названий:', sum(1 for r in out if r['composite']))
    by = collections.defaultdict(collections.Counter)
    for r in out:
        s = r['cands'][0]['score'] if r['cands'] else -99
        by[r['o']['coll']]['>=8' if s >= 8 else ('6-8' if s >= 6 else ('4-6' if s >= 4 else '<4'))] += 1
    for k, v in by.items():
        print(' ', k, dict(v))


if __name__ == '__main__':
    main()
