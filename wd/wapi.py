#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тонкая обёртка над MediaWiki/Wikidata API: кэш на диске, ретраи, rate-limit."""
import hashlib, json, os, time, threading
import requests

CACHE = '/home/user/wd/cache'
os.makedirs(CACHE, exist_ok=True)
_lock = threading.Lock()
_last = [0.0]
MIN_INTERVAL = 0.12          # ~8 запросов/с суммарно
UA = {'User-Agent': 'HistorySiteCurator/1.0 (https://github.com/RionaLis/History; data curation script)'}
S = requests.Session()
S.headers.update(UA)


def _throttle():
    with _lock:
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def _key(url, params):
    h = hashlib.sha1((url + json.dumps(params, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
    return os.path.join(CACHE, h + '.json')


def get(url, params, tries=4, timeout=45):
    """GET с кэшем. Возвращает dict или None."""
    p = dict(params)
    p['format'] = 'json'
    path = _key(url, p)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    last = None
    for i in range(tries):
        _throttle()
        try:
            r = S.get(url, params=p, timeout=timeout)
            if r.status_code == 429:
                time.sleep(2 + i * 3)
                continue
            r.raise_for_status()
            data = r.json()
            if data.get('error'):
                code = data['error'].get('code', '')
                if code in ('maxlag', 'internal_api_error_MWException', 'ratelimited'):
                    time.sleep(3 + i * 2)
                    continue
                return None
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            return data
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1 + i * 2)
    if last:
        print('  [net] %s: %s' % (url, last))
    return None


WD = 'https://www.wikidata.org/w/api.php'


def wbsearch(query, lang='ru', limit=8):
    d = get(WD, {'action': 'wbsearchentities', 'search': query, 'language': lang,
                 'uselang': lang, 'type': 'item', 'limit': limit})
    if not d:
        return []
    return [{'id': s['id'], 'label': s.get('label'), 'description': s.get('description'),
             'aliases': s.get('aliases') or [], 'concepturl': s.get('concepturl')}
            for s in d.get('search', [])]


def wbget(ids, props='labels|descriptions|claims|sitelinks', langs='ru|en'):
    """Пакетная выдача элементов (до 50 за раз)."""
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        d = get(WD, {'action': 'wbgetentities', 'ids': '|'.join(chunk),
                     'props': props, 'languages': langs})
        if d and d.get('entities'):
            for q, e in d['entities'].items():
                if 'missing' not in e:
                    out[q] = e
    return out


def wiki_pageprops(titles, lang='ru'):
    """title -> Qxxx через pageprops (пакетами по 40)."""
    res = {}
    titles = list(dict.fromkeys(t for t in titles if t))
    url = 'https://%s.wikipedia.org/w/api.php' % lang
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        d = get(url, {'action': 'query', 'titles': '|'.join(chunk),
                      'prop': 'pageprops', 'ppprop': 'wikibase_item',
                      'redirects': 1, 'converttitles': 1})
        if not d or 'query' not in d:
            continue
        norm = {}
        for n in d['query'].get('normalized', []):
            norm[n['to']] = n['from']
        redir = {}
        for r in d['query'].get('redirects', []):
            redir[r['to']] = r['from']
        for pg in d['query'].get('pages', {}).values():
            q = (pg.get('pageprops') or {}).get('wikibase_item')
            if not q:
                continue
            t = pg.get('title')
            for src in (t, norm.get(t), redir.get(t)):
                if src:
                    res.setdefault(src, q)
    return res
