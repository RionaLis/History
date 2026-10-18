#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 1: генерация кандидатов Wikidata для каждого объекта базы.

Стратегии:
  wpp_ru  — точный заголовок русской Википедии -> wikibase_item (самый точный сигнал)
  wpp_en  — то же для англ. Википедии (для латинских названий)
  wsrch   — полнотекстовый поиск по русской Википедии -> заголовки -> QID
  wb_ru   — wbsearchentities по-русски
  wb_en   — wbsearchentities по-английски
Результат: candidates.jsonl
"""
import json, re, sys, threading
import concurrent.futures as cf
sys.path.insert(0, '/home/user/wd')
import wapi

OBJS = [json.loads(l) for l in open('/home/user/wd/objects.jsonl', encoding='utf-8')]

GENERIC = ('империя','царство','держава','королевство','государство','ханство','каганат','султанат',
           'халифат','республика','княжество','герцогство','колония','владения','цивилизация',
           'культура','индустрия','технокомплекс','народ','народы','племена','союз','система',
           'конфедерация','протекторат','вице-королевство','общность','традиция','период','эпоха')
LATIN = re.compile(r'^[A-Za-z][A-Za-z .\-]*$')
SEP = re.compile(r'\s*(?:;|/|:|,|\s+и\s+)\s*')


def parts_of(name):
    """Части сборного названия (без пояснений в скобках)."""
    base = re.sub(r'\([^)]*\)', '', name)
    ps = [p.strip(' «»"') for p in SEP.split(base) if len(p.strip()) > 2]
    return ps if len(ps) > 1 else []


def stripped(name):
    """Варианты с отброшенным родовым словом: «Аккадская империя» -> «Аккадская», «Аккад»."""
    out = []
    toks = re.sub(r'\([^)]*\)', '', name).split()
    if len(toks) >= 2 and toks[-1].lower().strip('.,') in GENERIC:
        head = ' '.join(toks[:-1])
        out.append(head)
        m = re.match(r'([А-ЯЁA-Z][а-яёa-z]{2,})', head)
        if m:
            stem = m.group(1)
            for suf in ('ская','цкий','ская','ское','ская','ская','идская','ская'):
                pass
            out.append(stem[:max(4, len(stem) - 4)] if len(stem) > 5 else stem)
    return [o for o in out if o and o.lower() != name.lower()]


def queries(o):
    """(вариант, язык, источник-стратегия) для объекта."""
    name = o['name']
    qs = []
    seen = set()

    def add(q, lang, strat):
        q = (q or '').strip()
        if len(q) < 3 or (q.lower(), lang, strat) in seen:
            return
        seen.add((q.lower(), lang, strat))
        qs.append((q, lang, strat))

    add(name, 'ru', 'wpp_ru')
    add(name, 'ru', 'wsrch')
    if LATIN.match(name) or re.search(r'[A-Za-z]{3}', name):
        add(name, 'en', 'wpp_en')
        add(name, 'en', 'wb_en')
    else:
        add(name, 'ru', 'wb_ru')
    for a in (o.get('aliases') or [])[:3]:
        if a.strip().lower() == name.lower():
            continue
        if LATIN.match(a.strip()):
            add(a, 'en', 'wpp_en')
        else:
            add(a, 'ru', 'wpp_ru')
    for v in stripped(name):
        add(v, 'ru', 'wb_ru')
        add(v, 'ru', 'wsrch')
    for p in parts_of(name):
        add(p, 'ru', 'wpp_ru')
        add(p, 'ru', 'wb_ru')
    return qs


def main():
    # --- 1. собираем все заголовки для пакетных pageprops ---
    titles = {'ru': set(), 'en': set()}
    per_obj = []
    for o in OBJS:
        qs = queries(o)
        per_obj.append((o, qs))
        for q, lang, strat in qs:
            if strat in ('wpp_ru',):
                titles['ru'].add(q)
            elif strat == 'wpp_en':
                titles['en'].add(q)
    print('заголовков ru:%d en:%d' % (len(titles['ru']), len(titles['en'])), flush=True)
    pp = {}
    pp['ru'] = wapi.wiki_pageprops(sorted(titles['ru']), 'ru')
    pp['en'] = wapi.wiki_pageprops(sorted(titles['en']), 'en')
    print('pageprops: ru=%d en=%d' % (len(pp['ru']), len(pp['en'])), flush=True)

    # --- 2. остальное — параллельно ---
    def run(q, lang, strat):
        if strat == 'wpp_ru':
            qid = pp['ru'].get(q) or pp['ru'].get(q[0].upper() + q[1:]) or pp['ru'].get(q[0].lower() + q[1:])
            return [(qid, 0)] if qid else []
        if strat == 'wpp_en':
            qid = pp['en'].get(q)
            return [(qid, 0)] if qid else []
        if strat == 'wb_ru':
            return [(s['id'], i) for i, s in enumerate(wapi.wbsearch(q, 'ru', 8))]
        if strat == 'wb_en':
            return [(s['id'], i) for i, s in enumerate(wapi.wbsearch(q, 'en', 8))]
        if strat == 'wsrch':
            d = wapi.get('https://ru.wikipedia.org/w/api.php',
                         {'action': 'query', 'list': 'search', 'srsearch': q,
                          'srlimit': 3, 'srprop': '', 'srenablerewrites': 1})
            if not d:
                return []
            ts = [r['title'] for r in d.get('query', {}).get('search', [])]
            m = wapi.wiki_pageprops(ts, 'ru')
            return [(m[t], i) for i, t in enumerate(ts) if t in m]
        return []

    jobs = []
    for o, qs in per_obj:
        for q, lang, strat in qs:
            jobs.append((o['id'], q, lang, strat))
    print('запросов фазы 1: %d' % len(jobs), flush=True)

    results = {}
    done = [0]
    lock = threading.Lock()

    def work(j):
        oid, q, lang, strat = j
        try:
            hits = run(q, lang, strat)
        except Exception as e:                      # noqa: BLE001
            print('  [err] %s %s: %s' % (strat, q, e), flush=True)
            hits = []
        with lock:
            done[0] += 1
            if done[0] % 250 == 0:
                print('  ...%d/%d' % (done[0], len(jobs)), flush=True)
            for qid, rank in hits:
                results.setdefault(oid, []).append(
                    {'qid': qid, 'src': strat, 'query': q, 'rank': rank})

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, jobs))

    with open('/home/user/wd/candidates.jsonl', 'w', encoding='utf-8') as f:
        for o, _ in per_obj:
            cands = results.get(o['id'], [])
            # дедуп: считаем голоса
            agg = {}
            for c in cands:
                a = agg.setdefault(c['qid'], {'qid': c['qid'], 'votes': [], 'best_rank': 99})
                a['votes'].append('%s:%s#%d' % (c['src'], c['query'], c['rank']))
                a['best_rank'] = min(a['best_rank'], c['rank'])
            f.write(json.dumps({'id': o['id'], 'coll': o['coll'], 'name': o['name'],
                                'type': o['type'], 'start': o['start'], 'end': o['end'],
                                'path': o['path'], 'aliases': o.get('aliases') or [],
                                'label': o.get('label'), 'summary': o.get('summary', ''),
                                'cands': sorted(agg.values(), key=lambda x: x['best_rank'])[:25]},
                               ensure_ascii=False) + '\n')
    n_hit = sum(1 for o, _ in per_obj if results.get(o['id']))
    print('объектов с хотя бы одним кандидатом: %d / %d' % (n_hit, len(per_obj)), flush=True)


if __name__ == '__main__':
    main()
