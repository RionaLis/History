#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Итоговое решение: присваивать ли QID и что делать с русским названием."""
import json, re, collections, difflib

FEAT = {json.loads(l)['id']: json.loads(l) for l in open('/home/user/wd/features.jsonl', encoding='utf-8')}
ROWS = [json.loads(l) for l in open('/home/user/wd/scored.jsonl', encoding='utf-8')]
SEVERE = ('персона', 'посторонний элемент', 'служебный элемент', 'неоднозначности',
          'класс элемента не совпадает', 'датировки расходятся', 'уточнение', 'элемент про язык')
HAS_CYR = re.compile(r'[а-яА-ЯёЁ]')


def norm(s):
    s = str(s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'`.,()\[\]:;!\?—–\-/]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def decide(r):
    o, cs = r['o'], r['cands']
    if not cs:
        return None, ['кандидатов не найдено ни одним из 8 способов поиска']
    top = cs[0]
    reasons = []
    if top['score'] < 8.0:
        reasons.append('уверенность низкая: балл %.1f (порог 8.0)' % top['score'])
    f_top = FEAT[top['qid']]
    fz = max([difflib.SequenceMatcher(None, norm(x), norm(v)).ratio()
              for x in name_forms_local(o['name'])
              for v in [f_top.get('ru') or '', f_top.get('ruwiki') or ''] if v] or [0.0])
    if top.get('name_core', top['br'][0][1]) < 2.0 and fz < 0.75:
        reasons.append('название «%s» почти не совпадает с меткой элемента «%s» (сходство %.0f%%)'
                       % (o['name'], top['ru'] or top['en'], fz * 100))
    if len(cs) > 1 and top['score'] - cs[1]['score'] < 1.5:
        reasons.append('конкурирует элемент %s «%s» (%.1f балла)'
                       % (cs[1]['qid'], cs[1]['ru'] or cs[1]['en'], cs[1]['score']))
    for f in top['flags']:
        if any(s in f for s in SEVERE):
            reasons.append(f)
    if len(cs) > 1:
        d = collections.defaultdict(list)
        for c in cs[:4]:
            if c['score'] >= 6:
                d[norm(c['ru'] or c['ruwiki'])].append(c)
        for k, v in d.items():
            if k and len(v) > 1 and top['score'] - v[1]['score'] < 2.5:
                reasons.append('в Wikidata два равноправных элемента с названием «%s»: %s и %s'
                               % (v[0]['ru'] or v[0]['en'], v[0]['qid'], v[1]['qid']))
                break
    if r['composite'] and not top.get('exact_full'):
        reasons.append('сборное название (%d части: %s)' % (len(r['parts']), ' / '.join(r['parts'])))
    return top, reasons


ACRONYM = re.compile(r'^[А-ЯЁA-Z0-9]{2,}$')


def capitalize(s):
    s = (s or '').strip()
    if not s or ACRONYM.match(s):
        return s
    return s[0].upper() + s[1:]


PAREN_RE = re.compile(r'\(([^)]*)\)')


def cyr_variants(f):
    """Русские варианты названия элемента: сначала метка и заголовок статьи, потом алиасы."""
    out = []
    for v in [f.get('ru'), f.get('ruwiki')] + (f.get('ru_al') or []):
        if v and HAS_CYR.search(v) and v not in out:
            out.append(v)
    return out


def primary_cyr(f):
    """Русское имя только из метки Wikidata / заголовка русской статьи (алиасы — нет)."""
    for v in (f.get('ru'), f.get('ruwiki')):
        if v and HAS_CYR.search(v):
            return v
    return None


PAREN_RE2 = re.compile(r'\(([^)]*)\)')


def name_forms_local(name):
    forms = [name]
    if '(' in name:
        base = PAREN_RE2.sub('', name).strip(' ,;:—-')
        if base:
            forms.append(base)
    return forms


def stems(s):
    return [t[:6] for t in norm(s).split() if t]


def same_stems(a, b):
    """True, если слова совпадают по основам (отличаются только окончаниями)."""
    sa, sb = stems(a), stems(b)
    return len(sa) == len(sb) and all(x == y for x, y in zip(sa, sb))


def base_and_inner(name):
    m = PAREN_RE.search(name)
    inner = m.group(1).strip() if m else ''
    base = PAREN_RE.sub('', name).strip(' ,;:—-')
    return (base or name), inner


def name_action(o, top):
    """keep / replace / propose / no_ru."""
    f = FEAT[top['qid']]
    cur = o['name']
    ncur = norm(cur)
    cyr = cyr_variants(f)

    base, inner = base_and_inner(cur)
    if not HAS_CYR.search(base):
        # основная часть названия не по-русски — обязателен перевод
        best = primary_cyr(f)
        if not best:
            return 'no_ru', cur, 'в Wikidata нет русской метки (только латинская) — название оставлено как есть'
        # у таксонов метка бывает во множественном числе («Кениантропы») — берём единственное
        if best.endswith(('ы', 'и')):
            for v in cyr:
                if len(best) - len(v) <= 2 and best.startswith(v[:4]) and not v.endswith(('ы', 'и')):
                    best = v
                    break
        best = capitalize(best)
        if inner and norm(inner) not in norm(best) and \
                difflib.SequenceMatcher(None, norm(inner), norm(best)).ratio() < 0.75:
            best = '%s (%s)' % (best, inner)
        if norm(best) == ncur:
            return 'keep', cur, 'название совпадает с русским вариантом Wikidata'
        return 'replace', best, 'русского названия не было — взято из Wikidata'

    # название русское: проверяем по всем русским вариантам элемента
    for v in [cur] + [x for x in (o.get('aliases') or [])]:
        if any(norm(v) == norm(x) for x in cyr):
            return 'keep', cur, 'название совпадает с русской меткой/вариантом Wikidata'
    cand = capitalize(cyr[0]) if cyr else (f.get('en') or cur)
    ratio = difflib.SequenceMatcher(None, ncur, norm(cand)).ratio()
    if ratio >= 0.85 and not same_stems(cur, cand):
        return 'replace', cand, 'расхождение только в написании (сходство %.0f%%)' % (ratio * 100)
    if ratio >= 0.85 and same_stems(cur, cand):
        return 'propose', cand, ('отличается только форма слова (число/падеж): «%s» vs «%s» — '
                                 'оставляем ваш вариант' % (cur, cand))
    return 'propose', cand, 'название отличается от метки Wikidata «%s» — решение за вами' % cand


def main():
    out = []
    stat = collections.Counter()
    for r in ROWS:
        top, reasons = decide(r)
        o = r['o']
        rec = {'id': o['id'], 'coll': o['coll'], 'path': o['path'], 'name': o['name'],
               'type': o['type'], 'start': o['start'], 'end': o['end'],
               'aliases': o.get('aliases') or [], 'label': o.get('label'),
               'composite': r['composite'], 'parts': r.get('parts') or [],
               'qid': top['qid'] if top else None,
               'score': top['score'] if top else None,
               'decision': 'авто' if (top and not reasons) else 'проверка',
               'reasons': reasons,
               'cands': [{'qid': c['qid'], 'score': c['score'], 'ru': c['ru'], 'en': c['en'],
                          'ruwiki': c.get('ruwiki'), 'desc': c['ru_desc'] or c['en_desc']}
                         for c in r['cands'][:5]]}
        if top and rec['decision'] == 'авто':
            act, newname, why = name_action(o, top)
            rec['name_action'], rec['new_name'], rec['name_reason'] = act, newname, why
            f = FEAT[top['qid']]
            extra = [v for v in [f.get('ru'), f.get('ruwiki'), f.get('en')] if v]
            rec['add_aliases'] = [v for v in extra if norm(v) != norm(o['name'])
                                  and norm(v) not in {norm(a) for a in (o.get('aliases') or [])}]
            stat['name_' + act] += 1
        else:
            rec['name_action'] = '—'
            rec['new_name'] = None
            rec['name_reason'] = ''
            rec['add_aliases'] = []
        stat[rec['decision'] + '_' + o['coll']] += 1
        out.append(rec)
    with open('/home/user/wd/decisions.jsonl', 'w', encoding='utf-8') as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    for k, v in sorted(stat.items()):
        print('%-22s %d' % (k, v))
    print()
    print('всего присвоено QID автоматически:', sum(1 for r in out if r['decision'] == 'авто'))
    print('на ручную проверку:', sum(1 for r in out if r['decision'] == 'проверка'))


if __name__ == '__main__':
    main()
