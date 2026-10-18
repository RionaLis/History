#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, sys, random
rows=[json.loads(l) for l in open('/home/user/wd/scored.jsonl',encoding='utf-8')]
def band(r):
    return r['cands'][0]['score'] if r['cands'] else -99
def line(r):
    o=r['o']; c=r['cands'][0] if r['cands'] else None
    if not c: return '%-28s | %-34s | НЕТ КАНДИДАТОВ' % (o['id'][:28], o['name'][:34])
    sec = r['cands'][1]['score'] if len(r['cands'])>1 else None
    return '%-28s | %-32s | %-7s %-30s %-34s | 2nd=%s' % (
        o['id'][:28], o['name'][:32], c['qid'], (c['ru'] or c['en'] or '')[:30],
        (c['ru_desc'] or c['en_desc'] or '')[:34], sec)
lo,hi=sys.argv[1],sys.argv[2]
coll=sys.argv[3] if len(sys.argv)>3 else None
n=int(sys.argv[4]) if len(sys.argv)>4 else 30
sel=[r for r in rows if float(lo)<=band(r)<float(hi) and (not coll or r['o']['coll']==coll)]
random.seed(7); random.shuffle(sel)
for r in sel[:n]: print(line(r))
print('--- всего в полосе: %d' % len(sel))
