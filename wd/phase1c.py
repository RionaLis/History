#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 1c: добор кандидатов для названий со скобками («Троецарствие (Вэй, Шу, У)»
   -> ищем и «Троецарствие», и содержимое скобок)."""
import json, re, sys, threading
import concurrent.futures as cf
sys.path.insert(0, '/home/user/wd')
import wapi
from phase1b import wd_ft
from phase1 import LATIN

OBJS = [json.loads(l) for l in open('/home/user/wd/candidates.jsonl', encoding='utf-8')]
PAREN = re.compile(r'\(([^)]*)\)')


def variants(name):
    out = []
    if '(' not in name:
        return out
    base = PAREN.sub('', name).strip(' ,;:')
    inner = ' '.join(m.strip() for m in PAREN.findall(name))
    if base and base.lower() != name.lower():
        out.append(base)
    for piece in re.split(r'[,;]|\s+и\s+', inner):
        piece = piece.strip(' ?.')
        if len(piece) >= 4 and not LATIN.match(piece):
            out.append(piece)
    return out


def main():
    jobs = []
    for o in OBJS:
        for v in variants(o['name']):
            for strat in ('wpp_ru', 'wsrch', 'wb_ru', 'wdft'):
                jobs.append((o['id'], v, strat))
    print('запросов фазы 1c: %d' % len(jobs), flush=True)
    pp_titles = sorted({q[1] for q in jobs if q[2] == 'wpp_ru'})
    pp = wapi.wiki_pageprops(pp_titles, 'ru') if pp_titles else {}
    print('pageprops: %d' % len(pp), flush=True)
    res, done, lock = {}, [0], threading.Lock()

    def work(j):
        oid, q, strat = j
        hits = []
        try:
            if strat == 'wpp_ru':
                qid = pp.get(q) or pp.get(q[0].upper() + q[1:])
                hits = [(qid, 0)] if qid else []
            elif strat == 'wb_ru':
                hits = [(s['id'], i) for i, s in enumerate(wapi.wbsearch(q, 'ru', 6))]
            elif strat == 'wdft':
                hits = [(t, i) for i, t in enumerate(wd_ft(q, 5))]
            else:
                d = wapi.get('https://ru.wikipedia.org/w/api.php',
                             {'action': 'query', 'list': 'search', 'srsearch': q, 'srlimit': 3,
                              'srprop': '', 'srenablerewrites': 1})
                ts = [r['title'] for r in (d or {}).get('query', {}).get('search', [])]
                m = wapi.wiki_pageprops(ts, 'ru') if ts else {}
                hits = [(m[t], i) for i, t in enumerate(ts) if t in m]
        except Exception as e:                      # noqa: BLE001
            print('  [err]', strat, q, e, flush=True)
        with lock:
            done[0] += 1
            if done[0] % 300 == 0:
                print('  ...%d/%d' % (done[0], len(jobs)), flush=True)
            for qid, rank in hits:
                res.setdefault(oid, []).append({'qid': qid, 'src': strat, 'query': q, 'rank': rank})

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, jobs))

    n_new = 0
    with open('/home/user/wd/candidates.jsonl', 'w', encoding='utf-8') as f:
        for o in OBJS:
            agg = {c['qid']: c for c in o['cands']}
            for c in res.get(o['id'], []):
                a = agg.get(c['qid'])
                if a is None:
                    agg[c['qid']] = {'qid': c['qid'], 'votes': ['%s:%s#%d' % (c['src'], c['query'], c['rank'])],
                                     'best_rank': c['rank']}
                    n_new += 1
                else:
                    a['votes'].append('%s:%s#%d' % (c['src'], c['query'], c['rank']))
                    a['best_rank'] = min(a['best_rank'], c['rank'])
            o['cands'] = sorted(agg.values(), key=lambda x: x['best_rank'])[:30]
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    print('новых кандидатов: %d' % n_new, flush=True)


if __name__ == '__main__':
    main()
