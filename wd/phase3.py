#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 3: скоринг кандидатов и выбор Wikidata ID."""
import json, math, re, sys
sys.path.insert(0, '/home/user/wd')

FEAT = {json.loads(l)['id']: json.loads(l) for l in open('/home/user/wd/features.jsonl', encoding='utf-8')}
CLS = json.load(open('/home/user/wd/classes.json', encoding='utf-8'))

LATIN = re.compile(r'^[A-Za-z][A-Za-z .\'\-]*$')


def norm(s):
    s = str(s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'`.,()\[\]:;!\?—–\-/]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def toks(s):
    return set(t for t in norm(s).split() if len(t) > 2)


STOP = {'империя','царство','государство','держава','королевство','народ','народы','культура',
        'период','эпоха','древний','древняя','ранний','ранняя','новый','новая','старый','союз',
        'республика','ханство','каганат','султанат','халифат','колония','владения','история',
        'the','of','and','empire','kingdom','state','period','ancient'}


def jac(a, b):
    A, B = toks(a) - STOP, toks(b) - STOP
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def class_text(f):
    """Текст классов (P31/P279 + родители) + описания."""
    parts = [f.get('ru_desc') or '', f.get('en_desc') or '', f.get('ru') or '', f.get('en') or '']
    seen = set()
    for c in (f.get('p31') or []) + (f.get('p279') or []):
        for q in [c] + (CLS.get(c, {}).get('par') or []):
            if q in seen:
                continue
            seen.add(q)
            info = CLS.get(q, {})
            parts += [info.get('ru') or '', info.get('en') or '']
    return ' '.join(p for p in parts if p).lower()


EXPECT = {
    'state': 'государств state country царств kingdom династи dynasty истори историческ historical республик republic княжеств principality вождеств chiefdom город-государство city-state ханств khanate султанат sultanate халифат caliphate зависимая территория dependent territory протекторат protectorate уния union федер монарх monarch realm держава polity state polity конфедерац',
    'empire': 'государств state country импери empire царств kingdom истори историческ historical династи dynasty монарх сверхдержава realm держава',
    'polity': 'государств state country истори историческ historical система system путь route торгов trade союз alliance league сеть network лига концепц concept экономика economy процесс process война war период period эпоха организация organization',
    'colony': 'колон colon зависимая территория dependent territory владени possess владение импери empire государ state провинц province вице-королевств viceroyalty территор territory',
    'culture': 'археолог archaeolog культур culture индустри industry технокомплекс комплекс complex период period цивилизац civilization традиц tradition неолит neolithic палеолит paleolithic бронзов bronze желез iron век age horizon общность',
    'people': 'народ ethnic этнос этническ people племя tribe indigenous коренн нация nation группа group диаспор diaspora языковая семья language family population население',
    'hominin': 'вид species таксон taxon род genus hominin гомин ископаем fossil human человек австралопитек australopithecus paranthropus homo',
    'nature': 'климат climate период period событи event похолодан потеплен warming cooling засух drought стадиал epoch эпоха геологич geologic явлен phenomenon колебан oscillation оптимум optimum голоцен holocene',
}
EXPECT['event'] = ('битв battle сражен войн war осад siege восстан revolt революц revolution договор treaty '
                   'завоеван conquest вторжен invasion событи event эпидеми epidemic plague пандеми pandemic '
                   'изобретен invention технолог technology процесс process эпох period явлен phenomenon кризис crisis '
                   'голод famine катастроф disaster коллапс collapse падение fall миграц migration расселен '
                   'основание founding реформ reform раскол schism собор council экспедиц expedition плаван voyage '
                   'открыт discovery резн massacre геноцид genocide восстание uprising революция revolution '
                   'конференц conference мир peace договор contract религи religion философ philosophy наук science '
                   'письменност writing металлурги metallurgy земледелие agriculture производств production')
EXPECT['migration'] = ('миграц migration расселен dispersal завоеван conquest вторжен invasion экспанси expansion '
                       'исход exodus движени movement торгов trade путь route диаспор diaspora колонизац colonization '
                       'войн war переселен resettlement扩散 diffusion распространение spread поход campaign')

BAD = ('компьютерная игра', 'видеоигра', 'video game', 'фильм', 'film', 'теле', 'album', 'альбом', 'песня',
       'song', 'книга', 'novel', 'роман', 'фамилия', 'surname', 'given name', 'имя ', 'компания', 'company',
       'бренд', 'brand', 'автомобиль', 'корабль', 'ship', 'самолёт', 'aircraft', 'журнал', 'magazine',
       'газета', 'newspaper', 'премия', 'award', 'валюта', 'currency', 'улица', 'street', 'музыка',
       'music', 'порода', 'породы животных', 'сорт ', 'операционная система', 'software', 'программное',
       'напиток', 'блюдо', 'dish', 'beverage', 'станция метро', 'футбольн', 'football club', 'хоккейн')
HUMAN = 'Q5'
LANG_CLS = ('Q34770', 'Q315', 'Q4917106', 'Q1970428')      # language, natural language…


def expect_group(o):
    t = o['type']
    if t.startswith('event:'):
        return 'event'
    if t.startswith('migration:'):
        return 'migration'
    return t if t in EXPECT else 'state'


def date_span(f):
    ds = [y for _p, y, _pr in (f.get('dates') or [])]
    es = [y for _p, y, _pr in (f.get('ends') or [])]
    return (min(ds) if ds else None), (max(es) if es else None)


def score(o, c):
    f = FEAT.get(c['qid'])
    if not f:
        return None
    name = o['name']
    is_lat = bool(LATIN.match(name.strip()))
    br = []            # разбор баллов

    # --- имя ---
    n = norm(name)
    best_name = 0.0
    tgt = [(f.get('ru'), 'ru_label', 4.0 if not is_lat else 2.0)]
    tgt.append((f.get('en'), 'en_label', 4.0 if is_lat else 1.8))
    for a in f.get('ru_al') or []:
        tgt.append((a, 'ru_alias', 3.0 if not is_lat else 1.6))
    for a in f.get('en_al') or []:
        tgt.append((a, 'en_alias', 2.4 if is_lat else 1.2))
    for val, tag, w in tgt:
        v = norm(val)
        if not v or len(v) < 2:
            continue
        s = 0.0
        if v == n:
            s = w
        elif len(v) >= 6 and (n.startswith(v) or v.startswith(n)):
            s = w * 0.55
        else:
            j = jac(name, val)
            if j >= 0.4:
                s = w * 0.45 * j / 0.9
        if s > best_name:
            best_name, why_name = s, '%s=%s' % (tag, val)
    # алиасы объекта
    for a in o.get('aliases') or []:
        for val, tag, w in [(f.get('ru'), 'ru_label', 2.0), (f.get('en'), 'en_label', 2.0 if is_lat else 1.2)]:
            if val and norm(val) == norm(a):
                if w > best_name * 0.6:
                    best_name = max(best_name, w)
                    why_name = 'alias %s=%s' % (tag, val)
    br.append(('name', round(best_name, 2), why_name if best_name else '—'))

    # --- источник кандидата ---
    src = 0.0
    why_src = []
    for v in c['votes']:
        s, q, r = v.split(':', 1)[0], v.split(':', 1)[1].rsplit('#', 1)[0], int(v.rsplit('#', 1)[1])
        if s == 'wpp_ru' and r == 0:
            src = max(src, 2.5); why_src.append('ru-wiki точный заголовок')
        elif s == 'wpp_en' and r == 0:
            src = max(src, 2.5 if is_lat else 1.5); why_src.append('en-wiki точный заголовок')
        elif s == 'wsrch' and r == 0:
            src = max(src, 1.2); why_src.append('ru-wiki поиск №1')
        elif s == 'wsrch' and r == 1:
            src = max(src, 0.6)
        elif s in ('wb_ru', 'wb_en') and r == 0:
            src = max(src, 1.2); why_src.append('wdsearch №1')
        elif s in ('wb_ru', 'wb_en') and r == 1:
            src = max(src, 0.6)
    br.append(('src', round(src, 2), ','.join(why_src) or '—'))

    # --- ссылки (популярность) ---
    sl = min(1.5, 0.8 * math.log10(1 + (f.get('sitelinks') or 0)))
    br.append(('sitelinks', round(sl, 2), '%d' % (f.get('sitelinks') or 0)))

    # --- тип ---
    ct = class_text(f)
    grp = expect_group(o)
    kws = [k for k in EXPECT[grp].split() if k]
    hitk = [k for k in kws if k in ct]
    p31 = f.get('p31') or []
    t = 0.0
    why_t = ''
    if HUMAN in p31:
        t -= 5.0; why_t = 'это человек (Q5)'
    for b in BAD:
        if b in ct:
            t -= 6.0; why_t = 'чёрный список: «%s»' % b; break
    if any(c in LANG_CLS for c in p31) and grp in ('people', 'state', 'culture', 'empire', 'polity', 'colony'):
        t -= 2.0; why_t = (why_t + '; ' if why_t else '') + 'это язык'
    if hitk:
        t += min(2.0, 0.7 * len(hitk)); why_t = (why_t + '; ' if why_t else '') + 'класс: ' + ','.join(hitk[:3])
    else:
        t -= 1.0
        why_t = (why_t + '; ' if why_t else '') + 'класс не похож на «%s»' % grp
    br.append(('type', round(t, 2), why_t or '—'))

    # --- даты ---
    st, en = date_span(f)
    a, b = o['start'], o['end'] if o['end'] else o['start']
    if a is None:
        a = b
    span = abs(b - a)
    slack = max(80.0, 0.18 * span)
    d = 0.0
    why_d = 'дат в Wikidata нет'
    if st is not None and en is not None:
        ok = not (en < a - slack or st > b + slack)
        d = 2.0 if ok else -3.0
        why_d = 'wd %s…%s %s наш %s…%s' % (st, en, 'OK' if ok else '✗', a, b)
    elif st is not None:
        ok = (a - slack) <= st <= (b + slack)
        d = 2.0 if ok else (-2.0 if min(abs(st - a), abs(st - b)) > 3 * slack else -0.5)
        why_d = 'wd начало %s %s наш %s…%s' % (st, 'OK' if ok else '✗', a, b)
    elif en is not None:
        ok = (a - slack) <= en <= (b + slack)
        d = 2.0 if ok else (-2.0 if min(abs(en - a), abs(en - b)) > 3 * slack else -0.5)
        why_d = 'wd конец %s %s наш %s…%s' % (en, 'OK' if ok else '✗', a, b)
    br.append(('date', round(d, 2), why_d))

    total = round(sum(x[1] for x in br), 2)
    return {'qid': c['qid'], 'score': total, 'br': br,
            'ru': f.get('ru'), 'en': f.get('en'), 'ru_desc': f.get('ru_desc'),
            'en_desc': f.get('en_desc'), 'sitelinks': f.get('sitelinks'),
            'p31': p31, 'dates': f.get('dates'), 'ends': f.get('ends'), 'is_lat': is_lat}


def main():
    out = []
    for line in open('/home/user/wd/candidates.jsonl', encoding='utf-8'):
        o = json.loads(line)
        scored = [s for s in (score(o, c) for c in o['cands']) if s]
        scored.sort(key=lambda x: -x['score'])
        out.append({'o': o, 'cands': scored[:8]})
    with open('/home/user/wd/scored.jsonl', 'w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    tops = [(r['o'], r['cands'][0] if r['cands'] else None,
             r['cands'][1]['score'] if len(r['cands']) > 1 else None) for r in out]
    import collections
    band = collections.Counter()
    for o, top, second in tops:
        s = top['score'] if top else -99
        if s >= 8:
            band['>=8'] += 1
        elif s >= 6:
            band['6-8'] += 1
        elif s >= 4:
            band['4-6'] += 1
        elif s >= 2:
            band['2-4'] += 1
        else:
            band['<2'] += 1
    print('распределение лучшего балла:', band.most_common())
    by_coll = collections.defaultdict(collections.Counter)
    for o, top, second in tops:
        s = top['score'] if top else -99
        by_coll[o['coll']]['>=8' if s >= 8 else ('6-8' if s >= 6 else ('4-6' if s >= 4 else '<4'))] += 1
    for k, v in by_coll.items():
        print(' ', k, dict(v))


if __name__ == '__main__':
    main()
