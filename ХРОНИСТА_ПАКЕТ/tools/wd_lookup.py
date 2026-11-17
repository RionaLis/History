#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wd_lookup.py — подбор и проверка Wikidata ID через живой API.

Wikidata — ключ, которым карта связывается со статьёй. Угадывать Q-номер
нельзя: выдуманный ID выглядит правдоподобно и молча ломает ссылку.
Этот скрипт спрашивает саму Викидату.

    python3 tools/wd_lookup.py "Roman Republic" "Ancient Carthage"
    python3 tools/wd_lookup.py --check maps/eras/bc323/polities.csv
    python3 tools/wd_lookup.py --ru "Римская республика"

ВАЖНО: Wikimedia требует заголовка User-Agent и отвечает 429 при частых
запросах. Скрипт ставит паузу между запросами и повторяет при 429.
Не убирайте задержку — иначе ваш IP временно заблокируют.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = ("https://www.wikidata.org/w/api.php?action=wbsearchentities"
       "&format=json&type=item&limit=5&search=")
# ВНИМАНИЕ: HTTP-заголовки допускают только latin-1. Никакой кириллицы в User-Agent,
# иначе urllib падает с "'latin-1' codec can't encode characters".
HDRS = {"User-Agent": "ChronistaMapDataPrep/1.0 "
                      "(historical education project; github.com/RionaLis/History)",
        "Accept": "application/sparql-results+json"}
DELAY = 1.3          # пауза между запросами, секунды
RETRIES = 4
Q_RE = re.compile(r"^Q\d+$")


def search(term, lang="en"):
    """Возвращает список [(qid, label, description)] или [] при неудаче."""
    url = API + urllib.parse.quote(term) + f"&language={lang}"
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            return [(x["id"], x.get("label", ""), (x.get("description") or ""))
                    for x in d.get("search", [])]
        except Exception as ex:
            if "429" in str(ex):
                wait = DELAY * (2 ** attempt)
                print(f"    429 (слишком часто) — жду {wait:.0f} с и повторяю…",
                      file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    ошибка: {ex}", file=sys.stderr)
                return []
    print("    исчерпаны повторы (429). Сделайте паузу в минуту.", file=sys.stderr)
    return []


def get_claims(qid):
    """
    Проверяет, существует ли Q-id, и забирает метку + даты.
    Идёт через SPARQL, потому что wbsearchentities по самому ID часто
    возвращает пустой список даже для существующего объекта — а нам
    важно отличать «нет такого» от «не нашлось поиском».
    P580 = начало, P582 = конец, P576 = упразднение.
    """
    q = (f"SELECT ?labelRu ?labelEn ?start ?end WHERE {{\n"
         f"  OPTIONAL {{ wd:{qid} rdfs:label ?labelRu FILTER(LANG(?labelRu)='ru') }}\n"
         f"  OPTIONAL {{ wd:{qid} rdfs:label ?labelEn FILTER(LANG(?labelEn)='en') }}\n"
         f"  OPTIONAL {{ wd:{qid} p:P580/psv:P580/wikibase:timeValue ?start }}\n"
         f"  OPTIONAL {{ wd:{qid} p:P582/psv:P582/wikibase:timeValue ?end }}\n"
         f"}} LIMIT 1")
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
            res = d.get("results", {}).get("bindings", [])
            if not res:
                return {}                       # объекта с таким Q-id нет
            b = res[0]
            out = {"exists": True,
                   "label_ru": b.get("labelRu", {}).get("value", ""),
                   "label_en": b.get("labelEn", {}).get("value", "")}
            for k_src, k_dst in (("start", "start"), ("end", "end")):
                v = b.get(k_src, {}).get("value")
                if v:
                    m = re.search(r"(-?\d{3,})", str(v))
                    if m:
                        out[k_dst] = int(m.group(1))
            return out
        except Exception as ex:
            if "429" in str(ex) or "403" in str(ex):
                wait = DELAY * (2 ** attempt)
                print(f"    {ex} — жду {wait:.0f} с", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    ошибка SPARQL: {ex}", file=sys.stderr)
                return {"error": str(ex)}
    return {"error": "429: слишком много запросов, сделайте паузу"}



def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def show(term, lang="en", dates=False):
    hits = search(term, lang)
    time.sleep(DELAY)
    if not hits:
        print(f"  {term:36s} → НИЧЕГО НЕ НАЙДЕНО")
        return None
    print(f"  {term}")
    best = None
    for qid, label, desc in hits:
        mark = ""
        if dates and best is None:
            cl = get_claims(qid)
            time.sleep(DELAY)
            if cl.get("exists"):
                parts = [f"{k}={v}" for k, v in cl.items()
                         if k in ("start", "end") and v is not None]
                if parts:
                    mark = "   [" + ", ".join(parts) + "]"
        print(f"      {qid:11s} {label:32s} {desc[:58]}{mark}")
        if best is None:
            best = qid
    return best


def batch_labels(qids, chunk=40):
    """
    Массовая проверка Q-id ОДНИМ запросом на пакет (API позволяет до 50).
    Возвращает {qid: {"ru":…, "en":…, "missing":bool}}.

    Две важные тонкости, на которые я напоролся при отладке:
      1. query.wikidata.org (SPARQL) во время сбоев WDQS вводит жёсткий лимит
         «1 запрос в минуту». Для массовой проверки он непригоден.
      2. action=wbgetentities ОТКЛОНЯЕТ ВЕСЬ ПАКЕТ, если хотя бы один ID
         не существует (ответ = {"error":{"code":"no-such-entity"}}).
         Поэтому при ошибке пакет бьётся пополам рекурсивно — так мы всё равно
         находим все битые ID за логарифмическое число запросов.
    """
    url = ("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json"
           "&props=labels&ids=")
    out = {}

    def fetch(batch):
        if not batch:
            return
        for attempt in range(RETRIES):
            try:
                req = urllib.request.Request(
                    url + urllib.parse.quote("|".join(batch)), headers=HDRS)
                with urllib.request.urlopen(req, timeout=45) as r:
                    d = json.load(r)
                if "error" in d:
                    code = d["error"].get("code", "")
                    bad = d["error"].get("id")
                    if code == "no-such-entity" and bad and len(batch) > 1:
                        mid = batch.index(bad) if bad in batch else len(batch) // 2
                        fetch(batch[:mid])            # рекурсивно делим пакет
                        fetch(batch[mid + 1:])
                        out[bad] = {"missing": True}
                        return
                    if code == "no-such-entity" and bad:
                        out[bad] = {"missing": True}
                        return
                    raise RuntimeError(code or "неизвестная ошибка API")
                for q, e in (d.get("entities") or {}).items():
                    lab = e.get("labels", {})
                    out[q] = {"missing": "missing" in e,
                              "ru": lab.get("ru", {}).get("value", ""),
                              "en": lab.get("en", {}).get("value", "")}
                return
            except Exception as ex:
                if "429" in str(ex):
                    time.sleep(DELAY * (2 ** attempt))
                else:
                    print(f"    ошибка API: {ex}", file=sys.stderr)
                    for q in batch:
                        out.setdefault(q, {"missing": None, "error": str(ex)})
                    return
        for q in batch:
            out.setdefault(q, {"missing": None, "error": "429: лимит запросов"})

    for k in range(0, len(qids), chunk):
        fetch(list(dict.fromkeys(qids[k:k + chunk])))   # dedup, сохраняя порядок
        time.sleep(DELAY)
    return out


def check_csv(path, cache_path=None):
    """Проверяет все Q-id в таблице эпохи одним-двумя запросами к Викидате."""
    if not os.path.exists(path):
        sys.exit(f"файл не найден: {path}")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh)
                if any((v or "").strip() for v in r.values())]

    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            cache = {}

    todo = sorted({(r.get("wikidata") or "").strip() for r in rows
                   if (r.get("wikidata") or "").strip() and (r.get("wikidata") or "").strip() not in cache})
    print(f"Проверка {len(rows)} строк из {path}")
    if todo:
        print(f"→ {len(todo)} уникальных Q-id, запросов к API: "
              f"{(len(todo) + 39) // 40}\n")
        cache.update(batch_labels(todo))
        if cache_path:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1, sort_keys=True)
    else:
        print("→ все Q-id уже в кэше, запросов к API: 0\n")

    bad, ok = [], 0
    for i, r in enumerate(rows, start=2):
        qid = (r.get("wikidata") or "").strip()
        name = (r.get("name_ru") or r.get("title_ru") or "").strip()
        if not qid:
            bad.append((i, name, "ПУСТО — объект не свяжется со статьёй"))
            continue
        if not Q_RE.match(qid):
            bad.append((i, name, f"«{qid}» — не формат Q-номера (нужно Q12345)"))
            continue
        info = cache.get(qid)
        if info is None:
            bad.append((i, name, f"{qid} — нет данных (проверьте сеть)"))
            continue
        if info.get("error"):
            bad.append((i, name, f"{qid} — {info['error']}"))
            continue
        if info.get("missing"):
            bad.append((i, name, f"{qid} НЕ СУЩЕСТВУЕТ в Викидате"))
            continue
        lab = info.get("ru") or info.get("en") or "?"
        ok += 1
        warn = ""
        # Сверяем РУССКОЕ имя в таблице с русским именем в Викидате.
        # (Сверять колонку match бессмысленно: там имя из чужого GeoJSON-набора,
        #  а не из Викидаты — раньше это давало гору ложных предупреждений.)
        wr = (info.get("ru") or "").strip().lower()
        nr = name.strip().lower()
        if wr and nr and wr not in nr and nr not in wr:
            warn = f"   ⚠ в таблице «{name}», в Викидате «{info.get('ru')}» — сверьте"
        print(f"  ✓ строка {i:3d}  {qid:11s} {name[:26]:26s} = «{lab[:34]}»{warn}")

    print("\n" + "=" * 74)
    print(f"подтверждено: {ok}   проблемных: {len(bad)}")
    for i, name, why in bad:
        print(f"  ✗ строка {i:3d}  {name[:30]:30s} — {why}")
    if bad:
        print("\nКак подобрать верный ID:")
        print('  python3 tools/wd_lookup.py "Ancient Carthage" "Nanda Empire"')
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--check-all":
        import glob as _glob
        cache_path = "wd_cache.json"
        paths = sorted(_glob.glob("maps/eras/*/polities.csv")) + \
                sorted(_glob.glob("maps/eras/*/events.csv")) + \
                sorted(_glob.glob("maps/eras/*/places.csv"))
        paths = [p for p in paths if "_template" not in p]
        if not paths:
            print("в maps/eras/ нет заполненных эпох")
            return 0
        rc = 0
        for p in paths:
            print("\n" + "#" * 74)
            rc |= check_csv(p, cache_path)
        return rc

    if args[0] == "--check":
        return check_csv(args[1] if len(args) > 1 else "maps/eras/_template/polities.csv",
                             args[2] if len(args) > 2 else "wd_cache.json")
    lang = "en"
    terms = []
    i = 0
    while i < len(args):
        if args[i] == "--ru":
            lang = "ru"
        elif args[i] == "--dates":
            terms.append("--dates")
        else:
            terms.append(args[i])
        i += 1
    want_dates = "--dates" in terms
    terms = [t for t in terms if t != "--dates"]
    print(f"Поиск в Wikidata (язык={lang}, задержка {DELAY} с):\n")
    for t in terms:
        show(t, lang, dates=want_dates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
