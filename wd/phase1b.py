#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 1b: полнотекстовый поиск по самому Wikidata (ловит то, что wbsearchentities misses)
   + точечный поиск по частям сборных названий. Дополняет candidates.jsonl."""
import json, re, sys, threading
import concurrent.futures as cf
sys.path.insert(0, '/home/user/wd')
import wapi
from phase1 import parts_of, stripped, LATIN

OBJS = [json.loads(l) for l in open('/home/user/wd/candidates.jsonl', encoding='utf-8')]


def wd_ft(q, limit=5):
    d = wapi.get(wapi.WD, {'action': 'query', 'list': 'search', 'srsearch': q,
                           'srlimit': limit, 'srnamespace': 0, 'srprop': ''})
    if not d:
        return []
    return [r['title'] for r in d.get('query', {}).get('search', []) if re.fullmatch(r'Q\d+', r['title'])]


def jobs_for(o):
    name = o['name']
    out = []
    seen = set()

    def add(q, tag):
        q = (q or '').strip()
        if len(q) < 4 or q.lower() in seen:
            return
        seen.add(q.lower())
        out.append((q, tag))

    add(name, 'wdft')
    for v in stripped(name):
        add(v, 'wdft')
    for a in (o.get('aliases') or [])[:3]:
        if not LATIN.match(a.strip()):
            add(a, 'wdft')
    return out


def main():
    jobs = []
    for o in OBJS:
        for q, tag in jobs_for(o):
            jobs.append((o['id'], q, tag))
    print('запросов фазы 1b: %d' % len(jobs), flush=True)
    res = {}
    done = [0]
    lock = threading.Lock()

    def work(j):
        oid, q, tag = j
        try:
            hits = wd_ft(q)
        except Exception as e:                      # noqa: BLE001
            print('  [err]', q, e, flush=True)
            hits = []
        with lock:
            done[0] += 1
            if done[0] % 200 == 0:
                print('  ...%d/%d' % (done[0], len(jobs)), flush=True)
            for i, qid in enumerate(hits):
                res.setdefault(oid, []).append({'qid': qid, 'src': tag, 'query': q, 'rank': i})

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, jobs))

    n_new = 0
    with open('/home/user/wd/candidates.jsonl', 'w', encoding='utf-8') as f:
        for o in OBJS:
            agg = {c['qid']: c for c in o['cands']}
            for c in res.get(o['id'], []):
                a = agg.get(c['qid'])
                if a is None:
                    agg[c['qid']] = {'qid': c['qid'], 'votes': [c['src'] + ':' + c['query'] + '#' + str(c['rank'])],
                                     'best_rank': c['rank']}
                    n_new += 1
                else:
                    a['votes'].append(c['src'] + ':' + c['query'] + '#' + str(c['rank']))
            o['cands'] = sorted(agg.values(), key=lambda x: x['best_rank'])[:30]
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    print('новых кандидатов: %d' % n_new, flush=True)
    print('объектов без кандидатов: %d' % sum(1 for o in OBJS if not o['cands']), flush=True)


if __name__ == '__main__':
    main()
