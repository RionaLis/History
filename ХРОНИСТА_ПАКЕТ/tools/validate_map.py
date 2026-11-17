#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_map.py — проверка качества данных ПЕРЕД публикацией.

Запускается вручную и автоматически в GitHub Actions. Пишет отчёт по-русски:
что сломано, что подозрительно и что нужно доделать. Ошибки (✗) блокируют
публикацию, предупреждения (!) — нет.

    python3 tools/validate_map.py            # все эпохи
    python3 tools/validate_map.py bc323      # одна эпоха
    python3 tools/validate_map.py --audit    # аудит готовых out/*.geojson

Требует:  pip install pyyaml
"""
import csv
import glob
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERAS = os.path.join(ROOT, "maps", "eras")
OUT = os.path.join(ROOT, "out")
CONTENT = os.path.join(ROOT, "content")

WIKIDATA_RE = re.compile(r"^Q\d+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Допустимые значения поля kind. Государство и археологическая культура —
# принципиально разные объекты: у культуры нет жёсткой границы, только ареал,
# и статья о ней не может быть статьёй о государстве.
# Допустимые значения kind — СВОИ ДЛЯ КАЖДОГО ФАЙЛА.
#
# Один общий список здесь был ошибкой. Я добавлял в extract_era.py новые типы
# (label для крупных единиц, заданных точкой; city; place; water; route),
# а валидатор продолжал сверять со старым списком из десяти значений и на
# мировом срезе 117 года выдал 29 ошибок «kind «label» недопустим» — на
# совершенно корректных данных: регионах Августовой Италии, Дакии, Парфии,
# Теотиуакане. Ошибка была в валидаторе, а не в данных.
#
# Правило простое: в полигональных файлах допустимы типы площадей, в точечных —
# типы точек. Пересечение (culture, tribe, unknown) оставлено в обоих.
POLITY_KINDS = {
    # государства и государственные образования
    "state", "empire", "kingdom", "city_state", "republic",
    # народы и культуры: ареал, а не граница
    "culture", "civilization", "tribe", "nomads", "confederation",
    # крупная единица, заданная в OHM точкой: ареала нет, рисуется подписью.
    # Так в данных лежат Парфия (Q1986139), Дакия (Q971609), регионы
    # Августовой Италии, Теотиуакан (Q172613), Moche (Q208188).
    "label", "place",
    # не определилось — требует ручного решения
    "unknown",
}

PLACE_KINDS = {
    "city", "town", "settlement", "village", "hamlet",
    "monument", "place", "label", "unknown",
}

ROUTE_KINDS = {
    "route", "road", "trade_route", "sea_route", "migration", "unknown",
}

# Словарь иконок событий. Это НЕ то же самое, что типы мест: здесь значения
# задаёте вы сами, под свои статьи. В демо-эпохе bc323 уже лежат русские
# «битва», «персона», «катастрофа» — и это правильно, так и должно быть.
# Валидатор сначала проверял events.csv по PLACE_KINDS и выдавал шесть ошибок
# на совершенно корректном файле.
EVENT_KINDS = {
    # по-русски — как в content/events/
    "битва", "сражение", "персона", "рождение", "смерть", "катастрофа",
    "извержение", "землетрясение", "изобретение", "открытие", "договор",
    "мир", "восстание", "мятеж", "реформа", "коронация", "основание",
    "падение", "поход", "миграция", "эпидемия", "собор", "событие",
    # по-английски — на случай данных из внешних источников
    "battle", "siege", "person", "birth", "death", "disaster", "eruption",
    "earthquake", "invention", "discovery", "treaty", "uprising", "revolt",
    "reform", "coronation", "founding", "fall", "campaign", "migration",
    "epidemic", "council", "event",
}

# Совокупность — для старых вызовов и для мест, где файл неизвестен.
ALLOWED_KINDS = POLITY_KINDS | PLACE_KINDS | ROUTE_KINDS


def read_csv(path):
    """
    Читает CSV в список словарей. Три грабли, на которые я сам наступил:

      1. BOM (utf-8-sig). Excel и Google Таблицы пишут BOM в начало файла,
         и тогда имя первой колонки становится "\ufeffwikidata" вместо
         "wikidata" — lookup молча возвращает пустоту для всех строк.
      2. ЛИШНИЕ КОЛОНКИ. Если в строке больше полей, чем в заголовке,
         DictReader кладёт остаток СПИСКОМ под ключ None. Наивное
         `(v or "").strip()` падает с AttributeError: 'list' object has no
         attribute 'strip'. Именно так падает проверка на CSV, где в значении
         оказалась незаэкранированная запятая.
      3. Строки-комментарии. extract_era.py пишет в заготовки пояснения
         через «#», их надо пропускать, а не считать данными.
      4. Пустые строки — пропускаем.
    """
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh)]
    if not rows:
        return []
    # первая незакомментированная строка = заголовок
    hi = 0
    while hi < len(rows) and (not rows[hi] or str(rows[hi][0]).lstrip().startswith("#")):
        hi += 1
    if hi >= len(rows):
        return []
    hdr = [h.strip() for h in rows[hi]]
    for raw in rows[hi + 1:]:
        if not raw or not any((c or "").strip() for c in raw):
            continue
        if str(raw[0]).lstrip().startswith("#"):
            continue
        if len(raw) > len(hdr):
            # лишние поля: склеиваем их в последнюю колонку и сообщаем,
            # а не падаем. Чаще всего это незаэкранированная запятая в note.
            raw = raw[:len(hdr) - 1] + [",".join(raw[len(hdr) - 1:])]
        elif len(raw) < len(hdr):
            raw = raw + [""] * (len(hdr) - len(raw))
        out.append({h: (v or "").strip() for h, v in zip(hdr, raw)})
    return out



def ring_ok(ring):
    """Кольцо полигона замкнуто и содержит минимум 4 точки."""
    return len(ring) >= 4 and ring[0] == ring[-1]


def geom_report(g):
    """Возвращает (число вершин, список проблем)."""
    n, problems = 0, []
    if not g:
        return 0, ["пустая геометрия"]
    t = g.get("type")
    if t == "Polygon":
        for i, r in enumerate(g.get("coordinates") or []):
            n += len(r)
            if i == 0 and not ring_ok(r):
                problems.append("внешнее кольцо не замкнуто")
    elif t == "MultiPolygon":
        for poly in g.get("coordinates") or []:
            for i, r in enumerate(poly):
                n += len(r)
                if i == 0 and not ring_ok(r):
                    problems.append("одно из внешних колец не замкнуто")
    elif t == "Point":
        c = g.get("coordinates") or []
        n = 1
        if len(c) != 2 or not (-180 <= c[0] <= 180 and -90 <= c[1] <= 90):
            problems.append(f"координаты вне допустимого диапазона: {c}")
    else:
        problems.append(f"неподдерживаемый тип геометрии: {t}")
    return n, problems


def check_era(era_dir):
    name = os.path.basename(era_dir)
    errors, warnings, notes = [], [], []
    yml = os.path.join(era_dir, "era.yml")

    if not os.path.exists(yml):
        return [f"{name}: нет era.yml"], [], []
    meta = (yaml.safe_load(open(yml, encoding="utf-8")) or {}) if yaml else {}
    if not yaml:
        warnings.append("pyyaml не установлен — era.yml не проверен (pip install pyyaml)")

    eid = str(meta.get("id") or name)
    if eid != name:
        errors.append(f"era.yml: id «{eid}» не совпадает с именем папки «{name}»")
    year = meta.get("year")
    if year is None:
        errors.append("era.yml: не указан year")
    vf, vt = meta.get("valid_from"), meta.get("valid_to")
    if None not in (vf, vt, year) and not (vf <= year <= vt):
        errors.append(f"era.yml: year {year} вне диапазона valid_from..valid_to ({vf}..{vt})")
    if meta.get("maxzoom") and not (0 <= int(meta["maxzoom"]) <= 14):
        warnings.append(f"era.yml: maxzoom={meta['maxzoom']} — обычно нужно 6..10")
    if not meta.get("sources"):
        errors.append("era.yml: не заполнен sources — лицензионная неопределённость")
    else:
        for s in meta["sources"]:
            lic = str(s.get("license") or "")
            if not lic.strip():
                errors.append(f"era.yml: у источника «{s.get('name')}» не указана license")
            elif "GPL" in lic.upper():
                warnings.append(f"источник «{s.get('name')}» под GPL — см. раздел 8 плана, "
                                "риск copyleft на весь проект")
            elif "NC" in lic.upper() or "NONCOMMERCIAL" in lic.upper():
                warnings.append(f"источник «{s.get('name')}» под NonCommercial-лицензией — "
                                "блокирует любую будущую монетизацию")

    # ---- polities.csv -----------------------------------------------------
    rows = read_csv(os.path.join(era_dir, "polities.csv"))
    # свой набор допустимых kind для каждого файла — см. POLITY_KINDS
    allowed_kinds = POLITY_KINDS
    if not rows:
        errors.append("polities.csv пуст или отсутствует — на карте не будет границ")
    seen_wd, seen_names, no_geom, unnamed = {}, {}, [], []
    no_wd = []
    no_name = []
    for i, r in enumerate(rows, start=2):  # start=2: строка 1 — заголовки
        wd = (r.get("wikidata") or "").strip()
        nm = (r.get("name_ru") or "").strip()
        tag = f"polities.csv:{i}"
        if not wd:
            # ПРЕДУПРЕЖДЕНИЕ, а не ошибка: сборка без wikidata работает,
            # build_map.py подставит запасной id. Но объект нельзя связать
            # со статьёй и нельзя проверить по внешним источникам, поэтому
            # для платного продукта это всё равно надо закрыть.
            # В данных OHM wikidata нет у очень многих объектов: на срезе
            # −2400 г. из 6 государств его не было у 3 (Inebu-hedj, Khepesh,
            # Kemet/Древнее царство). Блокировать на этом сборку — значит
            # не собрать вообще ничего.
            no_wd.append((i, nm or "(без имени)"))
        elif not WIKIDATA_RE.match(wd):
            errors.append(f"{tag} — wikidata «{wd}» не похож на Q-номер")
        elif wd in seen_wd:
            errors.append(f"{tag} — wikidata {wd} повторяется (уже в строке {seen_wd[wd]})")
        else:
            seen_wd[wd] = i
        if not nm:
            # тоже предупреждение: build_map.py возьмёт name_local, и подпись
            # на карте будет — просто не по-русски
            no_name.append((i, wd or r.get("name_local") or r.get("geom") or "?"))
        elif nm in seen_names:
            warnings.append(f"{tag} — name_ru «{nm}» повторяется (строка {seen_names[nm]})")
        else:
            seen_names[nm] = i

        st, en = r.get("start"), r.get("end")
        try:
            if st and en and float(st) > float(en):
                errors.append(f"{tag} — start ({st}) больше end ({en}); "
                              "проверьте знаки: до н.э. — отрицательные")
        except ValueError:
            errors.append(f"{tag} — start/end не числа: «{st}» / «{en}»")

        c = (r.get("color") or "").strip()
        if c and not COLOR_RE.match(c):
            errors.append(f"{tag} — color «{c}» не в формате #rrggbb")

        kind = (r.get("kind") or "").strip().lower()
        if not kind:
            warnings.append(f"{tag} ({nm}) — пустой kind: государство и археологическая "
                            "культура рисуются по-разному, укажите явно")
        elif kind not in allowed_kinds:
            # Тоже предупреждение, по той же причине: сборка проходит, сайт
            # берёт запасной способ отрисовки. Но посмотреть список стоит —
            # обычно за неизвестным kind скрывается опечатка.
            warnings.append(f"{tag} — kind «{kind}» не из известного списка для "
                            "polities.csv; сайт нарисует его как unknown. Можно: "
                            + ", ".join(sorted(allowed_kinds)))
        elif kind in ("culture", "tribe", "nomads") and (r.get("article") or "").strip():
            notes.append(f"{tag} ({nm}) — kind={kind}: это не государство, "
                         "проверьте, что статья именно о культуре/народе")

        # геометрия
        key = (r.get("geom") or wd or (r.get("match") or "")).strip()
        own = os.path.join(era_dir, "geom", f"{key}.geojson")
        comb = os.path.join(era_dir, "geom", "all.geojson")
        if not os.path.exists(own) and not os.path.exists(comb):
            no_geom.append(f"{tag} ({nm or wd}) — нет ни geom/{key}.geojson, ни geom/all.geojson")

        art = (r.get("article") or "").strip()
        if not art:
            warnings.append(f"{tag} ({nm}) — пустой article: клик по карте никуда не поведёт")
        elif not os.path.exists(os.path.join(ROOT, art)):
            notes.append(f"{tag} — статья {art} не найдена (будет создана?)")
        if not (r.get("source") or "").strip():
            warnings.append(f"{tag} ({nm}) — пустой source: неизвестно, откуда граница")

    errors.extend(no_geom)

    # ---- geom/all.geojson: аудит «сырого» набора --------------------------
    comb = os.path.join(era_dir, "geom", "all.geojson")
    if os.path.exists(comb):
        d = json.load(open(comb, encoding="utf-8"))
        feats = d.get("features", [])
        total_v = 0
        n_unnamed = 0
        name_count = {}
        for f in feats:
            v, probs = geom_report(f.get("geometry"))
            total_v += v
            for p in probs:
                warnings.append(f"geom/all.geojson — {p}")
            nm = str((f.get("properties") or {}).get("NAME") or "").strip()
            if not nm:
                n_unnamed += 1
            else:
                name_count[nm] = name_count.get(nm, 0) + 1
        covered = len(rows)
        notes.append(f"geom/all.geojson: {len(feats)} полигонов, {total_v:,} вершин "
                     f"({total_v/1024:,.0f} К вершин)")
        if n_unnamed:
            pct = round(100 * n_unnamed / max(len(feats), 1))
            warnings.append(f"geom/all.geojson: {n_unnamed} из {len(feats)} полигонов ({pct}%) "
                            "БЕЗ названия — их нельзя связать со статьёй. "
                            "Это типично для открытых наборов и есть главная причина "
                            "жалобы «отображаются не те названия»")
        dups = {k: v for k, v in name_count.items() if v > 1}
        if dups:
            warnings.append(f"geom/all.geojson: повторяющиеся названия "
                            f"({len(dups)}): " + ", ".join(f"«{k}»×{v}" for k, v in list(dups.items())[:5])
                            + " — сопоставление по имени склеит их в один объект")
        if covered and len(feats):
            notes.append(f"атрибутировано в polities.csv: {covered} из {len(feats)} "
                         f"({round(100*covered/len(feats))}%)")
        if total_v > 400_000:
            warnings.append(f"geom/all.geojson: {total_v:,} вершин — много. "
                            "Прогоните через mapshaper.org (simplify 20-40%), "
                            "иначе тайлы будут тяжёлыми")

    # ---- места и события ---------------------------------------------------
    KINDS_BY_FILE = {"places.csv": PLACE_KINDS, "events.csv": EVENT_KINDS,
                     "routes.csv": ROUTE_KINDS, "cultures.csv": POLITY_KINDS}
    for fn, req in (("places.csv", ("lon", "lat")), ("events.csv", ("lon", "lat", "year")),
                    ("routes.csv", ()), ("cultures.csv", ())):
        rr = read_csv(os.path.join(era_dir, fn))
        for i, r in enumerate(rr, start=2):
            tag = f"{fn}:{i}"
            for k in req:
                v = (r.get(k) or "").strip()
                if not v:
                    errors.append(f"{tag} — пусто обязательное поле {k}")
                    continue
                try:
                    float(v)
                except ValueError:
                    errors.append(f"{tag} — {k} «{v}» не число")
            wd = (r.get("wikidata") or "").strip()
            if wd and not WIKIDATA_RE.match(wd):
                errors.append(f"{tag} — wikidata «{wd}» не похож на Q-номер")
            kd = (r.get("kind") or "").strip().lower()
            allowed = KINDS_BY_FILE.get(fn, ALLOWED_KINDS)
            if kd and kd not in allowed:
                # ПРЕДУПРЕЖДЕНИЕ, а не ошибка. Неизвестный kind не ломает
                # сборку: сайт берёт иконку или способ отрисовки по kind,
                # а при неизвестном значении использует запасную. Значит
                # объект нарисуется, просто не тем значком. Блокировать
                # публикацию из-за этого неправильно — особенно в events.csv,
                # где словарь задаёте вы сами под свои статьи.
                warnings.append(f"{tag} — kind «{kd}» не из известного списка; "
                                "сайт возьмёт запасную иконку. Известные: "
                                + ", ".join(sorted(allowed)))
            lon = num(r.get("lon"))
            lat = num(r.get("lat"))
            if lon is not None and lat is not None and not (-180 <= lon <= 180 and -90 <= lat <= 90):
                errors.append(f"{tag} — координаты ({lon}, {lat}) вне диапазона; "
                              "не перепутаны ли широта с долготой")
            if fn == "events.csv" and not (r.get("article") or "").strip():
                warnings.append(f"{tag} ({r.get('title_ru')}) — пустой article")

    if no_wd:
        warnings.append(f"polities.csv: у {len(no_wd)} из {len(rows)} государств пустой "
                        f"wikidata — их нельзя связать со статьёй")
    if no_name:
        warnings.append(f"polities.csv: у {len(no_name)} из {len(rows)} нет name_ru")

    return errors, warnings, notes


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def audit_compiled():
    """Аудит уже собранных out/*.geojson — то, что реально уйдёт на сайт."""
    print("\n" + "=" * 74)
    print("АУДИТ СОБРАННЫХ СЛОЁВ  (out/*.geojson)")
    print("=" * 74)
    files = sorted(glob.glob(os.path.join(OUT, "*.geojson")))
    if not files:
        print("  пусто — сначала запустите build_map.py")
        return
    for p in files:
        d = json.load(open(p, encoding="utf-8"))
        feats = d.get("features", [])
        kb = os.path.getsize(p) / 1024
        by_layer = {}
        unnamed = no_article = no_wd = 0
        verts = 0
        for f in feats:
            pr = f.get("properties") or {}
            L = pr.get("_layer", "?")
            by_layer[L] = by_layer.get(L, 0) + 1
            if pr.get("status") == "unnamed":
                unnamed += 1
            if L in ("borders", "places", "events") and not pr.get("article"):
                no_article += 1
            if L == "borders" and not pr.get("wikidata"):
                no_wd += 1
            verts += geom_report(f.get("geometry"))[0]
        gz = None
        try:
            import gzip
            gz = len(gzip.compress(json.dumps(d, ensure_ascii=False,
                                              separators=(",", ":")).encode())) / 1024
        except Exception:
            pass
        print(f"\n  {os.path.basename(p)}")
        print(f"    вес: {kb:,.0f} КБ" + (f"   (gzip: {gz:,.0f} КБ)" if gz else ""))
        print(f"    объектов: {len(feats)}   вершин: {verts:,}")
        print(f"    по слоям: " + ", ".join(f"{k}={v}" for k, v in sorted(by_layer.items())))
        flag = "✗" if unnamed > len(feats) * 0.5 else ("!" if unnamed else "✓")
        print(f"    {flag} без имени (серые пятна): {unnamed}")
        print(f"    {'!' if no_article else '✓'} без ссылки на статью: {no_article}")
        print(f"    {'!' if no_wd else '✓'} границ без wikidata: {no_wd}")
        if gz:
            # Оценка по РЕАЛЬНОМУ замеру, а не по догадке.
            # Прежняя формула «gzip × 0,85» обещала ~100 КБ там, где настоящая
            # сборка дала 692 КБ — занижение в 7 раз. Замерено на демо-эпохе
            # (88 объектов, 13 916 вершин, GeoJSON 321 КБ, gzip 117 КБ):
            #     z0–4 → 175 КБ   z0–5 → 335 КБ   z0–6 → 692 КБ
            #     z0–7 → 1486 КБ  z0–8 → 3325 КБ
            # Отношение к gzip стабильно: 1,5 / 2,9 / 5,9 / 12,7 / 28,4 —
            # то есть КАЖДЫЙ лишний зум удваивает вес. Упрощение геометрии
            # почти не помогает: pixelTolerance 1.0→4.0 даёт всего −11%.
            est = {4: 1.5, 5: 2.9, 6: 5.9, 7: 12.7, 8: 28.4}
            mz = 6
            try:
                import yaml as _y
                cfg = _y.safe_load(open(os.path.join(era_dir, "era.yml"), encoding="utf-8")) or {}
                mz = int(cfg.get("maxzoom") or 6)
            except Exception:
                pass
            k = est.get(mz)
            if k is None:
                k = 5.9 * (2 ** (mz - 6))
            print(f"    оценка PMTiles при maxzoom={mz}: ~{gz * k / 1024:,.2f} МБ "
                  f"(замерено: каждый лишний зум удваивает вес)")


def main():
    args = sys.argv[1:]
    if "--audit" in args:
        audit_compiled()
        return 0

    if args and not args[0].startswith("-"):
        dirs = [os.path.join(ERAS, args[0])]
    else:
        dirs = sorted(d for d in glob.glob(os.path.join(ERAS, "*"))
                      if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    total_err = 0
    for d in dirs:
        if not os.path.isdir(d):
            print(f"✗ папка не найдена: {d}")
            total_err += 1
            continue
        e, w, n = check_era(d)
        name = os.path.basename(d)
        print("\n" + "=" * 74)
        print(f"ЭПОХА: {name}" + ("   ✗ ЕСТЬ ОШИБКИ" if e else "   ✓ ошибок нет"))
        print("=" * 74)
        for x in e:
            print(f"  ✗ {x}")
        for x in w:
            print(f"  ! {x}")
        for x in n:
            print(f"  · {x}")
        if not (e or w or n):
            print("  (пусто)")
        total_err += len(e)
    audit_compiled()
    print("\n" + "=" * 74)
    if total_err:
        print(f"ИТОГ: {total_err} ошибок (✗). Публикацию нужно заблокировать.")
    else:
        print("ИТОГ: ошибок нет. Предупреждения (!) — это список дел, не блокировка.")
    print("=" * 74)
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
