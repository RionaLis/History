#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгружает все объекты базы (сущности, события, миграции) в objects.jsonl."""
import json, os, re

ROOT = '/home/user/History'
D = json.load(open(os.path.join(ROOT, 'data/index.json'), encoding='utf-8'))

out = []
for e in D['entities']:
    out.append({
        'coll': 'entity', 'id': e['id'], 'path': e['path'],
        'name': e['name'], 'aliases': e.get('aliases') or [],
        'type': e['type'], 'label': e.get('label'),
        'start': e['start'], 'end': e['end'],
        'region': e['region'], 'summary': e.get('summary', ''),
    })
for e in D['events']:
    out.append({
        'coll': 'event', 'id': e['id'], 'path': e['path'],
        'name': e['name'], 'aliases': [],
        'type': 'event:' + (e.get('icon') or 'event'), 'label': None,
        'start': e['year'], 'end': e.get('yearEnd') or e['year'],
        'region': e['region'], 'summary': e.get('summary', ''),
    })
for m in D['migrations']:
    out.append({
        'coll': 'migration', 'id': m['id'], 'path': m['path'],
        'name': m['name'], 'aliases': [],
        'type': 'migration:' + (m.get('kind') or 'migration'), 'label': None,
        'start': m['start'], 'end': m['end'],
        'region': None, 'summary': m.get('summary', ''),
    })

with open('/home/user/wd/objects.jsonl', 'w', encoding='utf-8') as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')

import collections
print('всего объектов:', len(out))
print(collections.Counter(o['coll'] for o in out).most_common())
print(collections.Counter(o['type'] for o in out).most_common())
