#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Применяет решения: wikidata ID + русские названия во фронтматтер content/**/*.md"""
import json, os, re, sys

ROOT = '/home/user/History'
DEC = [json.loads(l) for l in open('/home/user/wd/decisions.jsonl', encoding='utf-8')]
FEAT = {json.loads(l)['id']: json.loads(l) for l in open('/home/user/wd/features.jsonl', encoding='utf-8')}
APPLY = '--apply' in sys.argv

# короткие подписи на диаграмме для переименованных гоминин
LABEL_FIX = {
    'culture_aurignacian': 'Ориньяк',
}


def yq(s, quote):
    """Строка для YAML: quote=True -> в двойных кавычках."""
    s = str(s)
    if quote:
        return json.dumps(s, ensure_ascii=False)
    if re.search(r'[:#\[\]{}"\'&*!|>%@`]|^\s|\s$', s):
        return json.dumps(s, ensure_ascii=False)
    return s


def abbr_ru(name):
    """«Австралопитек анамский» -> «А. анамский»."""
    ws = name.split()
    return name if len(ws) < 2 else '%s. %s' % (ws[0][0], ' '.join(ws[1:]))


def edit_file(path, rec):
    full = os.path.join(ROOT, path)
    text = open(full, encoding='utf-8').read()
    end = text.find('\n---', 3)
    fm, body = text[3:end].strip('\n'), text[end + 4:]
    lines = fm.split('\n')
    changes = []

    def find(key):
        for i, l in enumerate(lines):
            if re.match(r'^%s\s*:' % key, l):
                return i
        return -1

    def quoted(key):
        i = find(key)
        if i < 0:
            return False
        v = lines[i].split(':', 1)[1].strip()
        return v.startswith('"') or v.startswith("'")

    def setv(key, val):
        i = find(key)
        q = quoted(key) if i >= 0 else (rec['coll'] == 'entity')
        new = '%s: %s' % (key, yq(val, q))
        if i < 0:
            return False
        if lines[i] != new:
            changes.append('%s: %s -> %s' % (key, lines[i].split(':', 1)[1].strip(), yq(val, q)))
            lines[i] = new
        return True

    # 1) wikidata
    i = find('wikidata')
    if i >= 0:
        lines[i] = 'wikidata: %s' % yq(rec['qid'], True)
    else:
        anchor = find('name')
        if anchor < 0:
            anchor = find('id')
        lines.insert(anchor + 1, 'wikidata: %s' % yq(rec['qid'], True))
        changes.append('добавлено wikidata: %s' % rec['qid'])

    # 2) имя
    old_name = rec['name']
    if rec['name_action'] == 'replace' and rec['new_name'] and rec['new_name'] != old_name:
        setv('name', rec['new_name'])
    # 3) подпись на диаграмме
    if rec['coll'] == 'entity':
        if rec['id'] in LABEL_FIX:
            setv('label', LABEL_FIX[rec['id']])
        elif rec['name_action'] == 'replace' and rec.get('label') and \
                not re.search(r'[а-яА-ЯёЁ]', rec['label']):
            setv('label', abbr_ru(rec['new_name']))

    # 4) алиасы (только у сущностей)
    if rec['coll'] == 'entity':
        cur = []
        i = find('aliases')
        if i >= 0:
            raw = lines[i].split(':', 1)[1].strip()
            try:
                cur = json.loads(raw) if raw.startswith('[') else [x.strip() for x in raw.split(',')]
            except Exception:
                cur = []
        have = {re.sub(r'\s+', ' ', str(x)).strip().lower().replace('ё', 'е') for x in cur}
        add = []
        if rec['name_action'] == 'replace':
            for v in [old_name, rec.get('label')]:
                if v and v.lower().replace('ё', 'е') not in have:
                    add.append(v); have.add(v.lower().replace('ё', 'е'))
        for v in rec.get('add_aliases') or []:
            if v and re.sub(r'\s+', ' ', v).strip().lower().replace('ё', 'е') not in have:
                add.append(v); have.add(v.lower().replace('ё', 'е'))
        add = add[:4]
        if add:
            newl = cur + add
            line = 'aliases: %s' % json.dumps(newl, ensure_ascii=False, separators=(',', ':'))
            if i >= 0:
                if lines[i] != line:
                    changes.append('aliases +%s' % ', '.join(add))
                    lines[i] = line
            else:
                anchor = find('wikidata')
                if anchor < 0:
                    anchor = find('name')
                lines.insert(anchor + 1, line)
                changes.append('aliases +%s' % ', '.join(add))

    new_text = '---\n' + '\n'.join(lines) + '\n---' + body
    if new_text != text:
        if APPLY:
            open(full, 'w', encoding='utf-8').write(new_text)
        return changes
    return []


def main():
    n_files = n_qid = n_name = n_alias = 0
    for rec in DEC:
        if rec['decision'] != 'авто':
            continue
        ch = edit_file(rec['path'], rec)
        if ch:
            n_files += 1
            n_qid += any(c.startswith('добавлено wikidata') or c.startswith('wikidata') for c in ch)
            n_name += any(c.startswith('name:') for c in ch)
            n_alias += any(c.startswith('aliases') for c in ch)
    print('%s: файлов изменено %d (wikidata: %d, имя: %d, алиасы: %d)'
          % ('ПРИМЕНЕНО' if APPLY else 'ПРОГОН', n_files, n_qid, n_name, n_alias))


if __name__ == '__main__':
    main()
