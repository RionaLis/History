#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_map.py — собирает эпоху из таблиц и геометрии в один GeoJSON.

    ВАШИ ТАБЛИЦЫ (CSV/YML)  +  ГЕОМЕТРИЯ (GeoJSON)  →  compiled.geojson

Это единственный шаг, где «данные» превращаются в «слой карты».
Дальше compiled.geojson либо подключается к MapLibre напрямую (простой путь),
либо прогоняется через make_tiles.py и становится .pmtiles (быстрый путь).

Запуск:
    python3 tools/build_map.py era bc323      # одна эпоха
    python3 tools/build_map.py era --all      # все эпохи из maps/eras/
    python3 tools/build_map.py places-slim    # ужать places.geojson

Требует:  pip install pyyaml
"""
import csv
import glob
import json
import os
import sys

try:
    import yaml
except ImportError:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERAS = os.path.join(ROOT, "maps", "eras")
OUT = os.path.join(ROOT, "out")

# ---------------------------------------------------------------- палитра ----
# 12 приглушённых «пергаментных» цветов в тон вашему theme.css.
# Если в polities.csv колонка color пустая — цвет назначается отсюда так,
# чтобы соседние по списку государства не получали одинаковый.
PALETTE = [
    "#c9a227", "#8fa9c9", "#7bb08a", "#c98a6b", "#a98bc0",
    "#6fb3b0", "#d4a5a5", "#9caf88", "#b5a642", "#8b9dc3",
    "#c4a484", "#7d9b76",
]

# Слои, которые умеет собирать эта программа. Порядок = порядок отрисовки
# на карте: что ниже в списке, то рисуется поверх.
#
# Раньше здесь стоял кортеж из четырёх имён, и он НИГДЕ не использовался —
# сборка перечисляет слои явными ветками ниже. Из-за этого в метаданных тайла
# `vector_layers` оказывался неполным: у эпохи bc323 культуры попали внутрь
# слоя borders, потому что отдельного слоя в описании не было. Список ниже
# держим в синхроне с ветками сборки и с make_tiles.py.
LAYERS = ("hydro", "borders", "cultures", "routes", "places",
          "battles", "epidemics", "events")


def rnd5(g):
    """Округляет координаты до 5 знаков (~1 м) — минус 30-40% веса файла."""
    if g is None:
        return None
    t, c = g.get("type"), g.get("coordinates")
    if t == "Point":
        return {"type": t, "coordinates": [round(c[0], 5), round(c[1], 5)]}
    if t in ("MultiPoint", "LineString"):
        return {"type": t, "coordinates": [[round(p[0], 5), round(p[1], 5)] for p in c]}
    if t == "Polygon":
        return {"type": t, "coordinates": [
            [[round(p[0], 5), round(p[1], 5)] for p in ring] for ring in c]}
    if t == "MultiPolygon":
        return {"type": t, "coordinates": [
            [[[round(p[0], 5), round(p[1], 5)] for p in ring] for ring in poly]
            for poly in c]}
    return g


def centroid(g):
    """Грубый центр полигона — для авто-расстановки подписей."""
    pts = []

    def walk(x):
        if not x:
            return
        if isinstance(x[0], (int, float)):
            pts.append(x)
        else:
            for y in x:
                walk(y)
    walk(g.get("coordinates"))
    if not pts:
        return None, None
    return round(sum(p[0] for p in pts) / len(pts), 4), round(sum(p[1] for p in pts) / len(pts), 4)


def num(v, default=None):
    if v in (None, "", "null", "None"):
        return default
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


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



def load_geom_for_polity(era_dir, row):
    """
    Находит геометрию объекта из строки таблицы.

    Порядок поиска — ровно тот, что описан в инструкции (§VII.1):

      1. geom/<wikidata>.geojson  — ЛИЧНЫЙ ФАЙЛ на государство.
         Надёжный способ: ключ — Wikidata ID, а не название, поэтому
         переименование объекта или опечатка в названии геометрию не ломают.
         Именно так работает tools/extract_era.py: он кладёт каждый найденный
         полигон в geom/Q128904.geojson и пишет «Q128904» в колонку geom.
      2. geom/<значение колонки geom>.geojson — то же, но имя задаёте вы.
         Нужно, когда Wikidata ID ещё не найден, а работать уже хочется
         (extract_era.py в этом случае пишет relation_2859881 — по OHM id).
      3. Ничего не найдено → (None, None), и вызывающий код пробует
         общий файл geom/all.geojson по колонке match.

    Возвращает (geometry, источник) — источник нужен для отладки и для
    поля source в отчёте.
    """
    gdir = os.path.join(era_dir, "geom")
    wd = (row.get("wikidata") or "").strip()
    if wd:
        p1 = os.path.join(gdir, wd + ".geojson")
        g = _read_geom_file(p1)
        if g:
            return g, f"geom/{wd}.geojson"
    gname = (row.get("geom") or "").strip()
    if gname:
        name = gname if gname.endswith(".geojson") else gname + ".geojson"
        p2 = os.path.join(gdir, name)
        g = _read_geom_file(p2)
        if g:
            return g, f"geom/{name}"
    return None, None


def _read_geom_file(path):
    """
    Читает геометрию из GeoJSON. Принимает и FeatureCollection, и одиночный
    Feature, и голый объект геометрии — потому что разные источники
    (QGIS, geojson.io, extract_era.py) сохраняют по-разному, и падать на
    этом неудобно.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"    ! {os.path.basename(path)} не читается: {e}")
        return None
    if isinstance(d, dict):
        if d.get("type") == "FeatureCollection":
            for f in d.get("features", []):
                g = (f or {}).get("geometry")
                if g and g.get("coordinates"):
                    return g
            return None
        if d.get("type") == "Feature":
            g = d.get("geometry")
            return g if g and g.get("coordinates") else None
        if d.get("type") in ("Polygon", "MultiPolygon", "LineString",
                             "MultiLineString", "Point", "MultiPoint"):
            return d if d.get("coordinates") else None
    return None


def build_combined(era_dir, row, name_key="NAME"):
    """
    Режим «общий файл»: геометрия всей эпохи лежит в geom/all.geojson,
    а polities.csv хранит только атрибуты. Сопоставление — по названию.
    Именно так устроены готовые открытые наборы (historical-basemaps, OHM-экспорт).
    """
    p = os.path.join(era_dir, "geom", "all.geojson")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    feats = d.get("features", [])
    alias = {
        (row.get("name_ru") or "").strip(),
        (row.get("name_en") or "").strip(),
        (row.get("geom") or "").strip(),
        (row.get("match") or "").strip(),
    }
    alias.discard("")
    hits = [f for f in feats
            if str(f.get("properties", {}).get(name_key, "")).strip() in alias]
    if not hits:
        return None
    # Если названию соответствует несколько полигонов — склеиваем в MultiPolygon
    polys = [f["geometry"] for f in hits if f.get("geometry")]
    if len(polys) == 1:
        return polys[0]
    parts = []
    for g in polys:
        if g["type"] == "Polygon":
            parts.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            parts.extend(g["coordinates"])
    return {"type": "MultiPolygon", "coordinates": parts}


def emit_polygon_rows(era_dir, rows, feats, stats, eid, year, layer,
                      default_kind, verbose=True, stat_key="matched"):
    """
    Общий цикл для полигональных таблиц. Один и тот же код читает и
    polities.csv (государства), и cultures.csv (археологические культуры и
    народы), и routes.csv (пути) — различаются только имя слоя в тайлах,
    вид по умолчанию и статистика.

    Разделение по слоям принципиально: культуру нельзя рисовать как
    государство. У культуры нет жёсткой границы, только ареал, и статья о ней
    не может быть статьёй о государстве. Поэтому в тайлах это отдельные
    source-layer, и сайт красит их по-разному (государство — плотная заливка
    с контуром, культура — полупрозрачная штриховка без контура).
    """
    used_idx = 0
    n = 0
    for i, r in enumerate(rows):
        geom, geom_src = load_geom_for_polity(era_dir, r)
        if geom is None:
            geom = build_combined(era_dir, r)
            geom_src = "geom/all.geojson" if geom else None
        if geom is None:
            stats["orphan"] += 1
            if verbose:
                print(f"    ! {layer}: {r.get('wikidata') or r.get('name_ru')}: геометрия не найдена")
            continue
        geom = rnd5(geom)
        lon, lat = centroid(geom)
        color = (r.get("color") or "").strip()
        if not color:
            color = PALETTE[used_idx % len(PALETTE)]
            used_idx += 1
        feats.append({
            "type": "Feature",
            "properties": {
                "_layer": layer,
                "id": (r.get("wikidata") or f"{eid}_{layer}_{i}").strip(),
                "wikidata": (r.get("wikidata") or "").strip(),
                "name_ru": (r.get("name_ru") or "").strip(),
                "name_local": (r.get("name_local") or "").strip(),
                "kind": (r.get("kind") or default_kind).strip().lower(),
                "start": num(r.get("start")),
                "end": num(r.get("end")),
                "color": color,
                "label_lon": num(r.get("label_lon"), lon),
                "label_lat": num(r.get("label_lat"), lat),
                "label_z_min": num(r.get("label_z_min"), 3),
                "article": (r.get("article") or "").strip(),
                "source": (r.get("source") or "").strip(),
                "note": (r.get("note") or "").strip(),
                "era": eid,
                "era_year": year,
                "status": "ok",
            },
            "geometry": geom,
        })
        stats[stat_key] = stats.get(stat_key, 0) + 1
        n += 1
    return n


def build_era(era_dir, verbose=True):
    name = os.path.basename(era_dir)
    yml = os.path.join(era_dir, "era.yml")
    if not os.path.exists(yml):
        print(f"  ! {name}: нет era.yml — пропущено")
        return None
    if yaml:
        meta = yaml.safe_load(open(yml, encoding="utf-8")) or {}
    else:
        meta = {"id": name}
        if verbose:
            print("  ! pyyaml не установлен — era.yml прочитан частично (pip install pyyaml)")

    eid = str(meta.get("id") or name)
    year = num(meta.get("year"), 0)
    vfrom = num(meta.get("valid_from"), year)
    vto = num(meta.get("valid_to"), year)
    feats = []
    stats = {"matched": 0, "orphan": 0, "unnamed": 0, "places": 0,
             "events": 0, "battles": 0, "epidemics": 0}

    # ---- 1. ГРАНИЦЫ ГОСУДАРСТВ -------------------------------------------
    emit_polygon_rows(era_dir, read_csv(os.path.join(era_dir, "polities.csv")),
                      feats, stats, eid, year, "borders", "state", verbose)

    # ---- 1а. АРХЕОЛОГИЧЕСКИЕ КУЛЬТУРЫ И НАРОДЫ ---------------------------
    #      Отдельный файл и отдельный слой в тайлах. В OHM для культур нет
    #      своего тега — «Bell Beaker culture» лежит как boundary=administrative
    #      с admin_level=2, то есть по тегам неотличима от государства.
    #      Поэтому разделяем их здесь, а не полагаемся на данные источника.
    stats["cultures"] = emit_polygon_rows(
        era_dir, read_csv(os.path.join(era_dir, "cultures.csv")),
        feats, stats, eid, year, "cultures", "culture", verbose, "cultures")

    # ---- 1в. ДОРОГИ И ТОРГОВЫЕ ПУТИ --------------------------------------
    #      Линейные объекты. В OHM их практически нет (на всю базу 14 отношений
    #      boundary=political и почти ноль датированных route=*), так что этот
    #      слой почти всегда заполняется вручную по атласам.
    stats["routes"] = emit_polygon_rows(
        era_dir, read_csv(os.path.join(era_dir, "routes.csv")),
        feats, stats, eid, year, "routes", "route", verbose, "routes")

    # ---- 1б. полигоны из общего файла, которых НЕТ в таблице --------------
    #      Рисуем их нейтральным серым как «не опознано» — честнее, чем дыра.
    allg = os.path.join(era_dir, "geom", "all.geojson")
    if os.path.exists(allg):
        known = {f["properties"]["name_local"] or f["properties"]["name_ru"]
                 for f in feats if f["properties"].get("_layer") in ("borders", "cultures")}
        d = json.load(open(allg, encoding="utf-8"))
        for f in d.get("features", []):
            nm = str(f.get("properties", {}).get("NAME", "") or "").strip()
            if not nm or nm in known or not f.get("geometry"):
                continue
            if any(nm in (k or "") or (k or "") in nm for k in known if k):
                continue
            lon, lat = centroid(f["geometry"])
            feats.append({
                "type": "Feature",
                "properties": {
                    "_layer": "borders", "id": "", "wikidata": "",
                    "name_ru": "", "name_local": nm, "kind": "unknown",
                    "start": vfrom, "end": vto,
                    "color": "#c8c2b4", "label_lon": lon, "label_lat": lat,
                    "label_z_min": 7, "article": "", "source": "geom/all.geojson",
                    "note": "не опознано — требуется атрибуция",
                    "era": eid, "era_year": year, "status": "unnamed",
                },
                "geometry": rnd5(f["geometry"]),
            })
            stats["unnamed"] += 1

    # ---- 2. ГИДРОГРАФИЯ ЭПОХИ --------------------------------------------
    hyd = os.path.join(era_dir, "geom", "hydro.geojson")
    if os.path.exists(hyd):
        d = json.load(open(hyd, encoding="utf-8"))
        for f in d.get("features", []):
            if not f.get("geometry"):
                continue
            p = dict(f.get("properties") or {})
            # Поля, которые нужны для ПРОВЕРКИ в QGIS, но не на карте.
            #
            # Замерено: если оставить их в тайле, era-rome117.pmtiles весит
            # 3,85 МБ вместо 1,79 МБ — больше, чем все остальные слои вместе.
            # Причина в том, что hist_names_all хранит до 24 вариантов названия
            # у каждого из 900+ объектов гидрографии («mer Noire | Black Sea |
            # mar Nero | Амшын Еиқәа | Swartsee | …»), и этот мусор повторяется
            # в каждом тайле, где объект виден.
            #
            # hist_candidates урезается до четырёх: этого хватает на подпись
            # или всплывающий текст, а полный список остаётся в
            # geom/hydro.geojson и в отчёте qgis/названия_водоёмов.md.
            p.pop("hist_names_all", None)
            p.pop("hist_modern_ru", None)
            p.pop("hist_note", None)
            cand = p.get("hist_candidates") or ""
            if cand:
                p["hist_candidates"] = " | ".join(cand.split(" | ")[:4])
            p.update({"_layer": "hydro", "era": eid, "era_year": year})
            feats.append({"type": "Feature", "properties": p, "geometry": rnd5(f["geometry"])})

    # ---- 3. ГОРОДА И ОБЪЕКТЫ ЭПОХИ ---------------------------------------
    for r in read_csv(os.path.join(era_dir, "places.csv")):
        lon, lat = num(r.get("lon")), num(r.get("lat"))
        if lon is None or lat is None:
            continue
        st, en = num(r.get("start")), num(r.get("end"))
        # Для населённых пунктов start/end означают «основан» и «покинут»,
        # а не «существовал только в эти годы». Поэтому место попадает
        # на снимок, если оно основано не позже года эпохи и ещё не покинуто.
        if str(meta.get("places_mode") or "snapshot") == "snapshot":
            if st is not None and st > year:
                continue
            if en is not None and en < year:
                continue
        else:  # режим "window" — как у событий
            if st is not None and st > vto:
                continue
            if en is not None and en < vfrom:
                continue
        feats.append({
            "type": "Feature",
            "properties": {
                "_layer": "places",
                "id": (r.get("wikidata") or "").strip(),
                "wikidata": (r.get("wikidata") or "").strip(),
                "name_ru": (r.get("name_ru") or "").strip(),
                "name_local": (r.get("name_local") or "").strip(),
                "kind": (r.get("kind") or "city").strip(),
                "z_min": num(r.get("z_min"), 4),
                "start": st, "end": en,
                "article": (r.get("article") or "").strip(),
                "source": (r.get("source") or "").strip(),
                "note": (r.get("note") or "").strip(),
                "era": eid, "era_year": year,
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })
        stats["places"] += 1

    # ---- 3а. МОРСКИЕ СРАЖЕНИЯ ---------------------------------------------
    # Отдельный слой, а не kind внутри events, потому что у морского боя
    # другая иконка, другая подпись и другая семантика: он привязан к
    # акватории, а не к суше, и его хочется показывать/скрывать независимо
    # от сухопутных битв.
    #
    # Файл sea_battles.csv создаёт tools/extract_era.py sea <эпоха>.
    # Колонки те же, что у events.csv, плюс fleets_ru и outcome_ru.
    for r in read_csv(os.path.join(era_dir, "sea_battles.csv")):
        lon, lat = num(r.get("lon")), num(r.get("lat"))
        y = num(r.get("year"))
        if lon is None or lat is None or y is None:
            continue
        if not (vfrom - 200 <= y <= vto + 200):
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "_layer": "battles",
                "id": (r.get("wikidata") or "").strip(),
                "wikidata": (r.get("wikidata") or "").strip(),
                "year": y, "month": num(r.get("month")), "day": num(r.get("day")),
                # всегда «морское сражение»: слой сам по себе это означает,
                # но поле оставляем, чтобы слой можно было слить с events
                "kind": (r.get("kind") or "морское сражение").strip(),
                "title": (r.get("title_ru") or "").strip(),
                "z_min": num(r.get("z_min"), 3),
                "article": (r.get("article") or "").strip(),
                "icon": (r.get("icon") or "anchor").strip(),
                "fleets": (r.get("fleets_ru") or "").strip(),
                "outcome": (r.get("outcome_ru") or "").strip(),
                "note": (r.get("note") or "").strip(),
                "era": eid, "era_year": year,
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })
        stats["battles"] += 1

    # ---- 3б. ЭПИДЕМИИ ------------------------------------------------------
    # Эпидемия — НЕ точка, а ареал и период: чума расползалась по регионам
    # годами. Поэтому источник — GeoJSON с полигонами, а не CSV.
    #
    # Файл geom/epidemics.geojson создаёт tools/extract_era.py epidemics <эпоха>.
    # Свойства каждого полигона: name_ru, start, end, wikidata, article,
    # deaths_est, spread_km_year, note, source, status.
    epi = os.path.join(era_dir, "geom", "epidemics.geojson")
    if os.path.exists(epi):
        d = json.load(open(epi, encoding="utf-8"))
        for f in d.get("features", []):
            if not f.get("geometry"):
                continue
            p = dict(f.get("properties") or {})
            p.update({"_layer": "epidemics", "era": eid, "era_year": year})
            feats.append({"type": "Feature", "properties": p,
                          "geometry": rnd5(f["geometry"])})
            stats["epidemics"] += 1

    # ---- 4. СОБЫТИЯ -------------------------------------------------------
    for r in read_csv(os.path.join(era_dir, "events.csv")):
        lon, lat = num(r.get("lon")), num(r.get("lat"))
        y = num(r.get("year"))
        if lon is None or lat is None or y is None:
            continue
        if not (vfrom - 200 <= y <= vto + 200):
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "_layer": "events",
                "id": (r.get("wikidata") or "").strip(),
                "wikidata": (r.get("wikidata") or "").strip(),
                "year": y, "month": num(r.get("month")), "day": num(r.get("day")),
                "kind": (r.get("kind") or "другое").strip(),
                "title": (r.get("title_ru") or "").strip(),
                "z_min": num(r.get("z_min"), 3),
                "article": (r.get("article") or "").strip(),
                "icon": (r.get("icon") or "dot").strip(),
                "note": (r.get("note") or "").strip(),
                "era": eid, "era_year": year,
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })
        stats["events"] += 1

    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"era-{eid}.geojson")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats},
                  fh, ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(dst) / 1024
    if verbose:
        print(f"  ✓ {eid}: {kb:,.0f} КБ → out/era-{eid}.geojson")
        print(f"      границы по таблице: {stats['matched']}   "
              f"не опознано (серым): {stats['unnamed']}   "
              f"без геометрии: {stats['orphan']}")
        extra = []
        if stats["battles"]:
            extra.append(f"морские бои: {stats['battles']}")
        if stats["epidemics"]:
            extra.append(f"эпидемии: {stats['epidemics']}")
        tail = ("   " + "   ".join(extra)) if extra else ""
        print(f"      города: {stats['places']}   события: {stats['events']}{tail}")
    return dst


# ============================================== УЖАТИЕ places.geojson ======
def places_slim(src, dst, year_from=None, year_to=None):
    """
    Открытый набор places.geojson весит 4,8 МБ и несёт 110 колонок
    (имена на 30 языках, mapillary, website…). Сайту нужно 8 колонок.
    Эта функция ужимает файл в 5–15 раз и отбирает места по датам.
    """
    KEEP = ["name", "name.ru", "name_local", "wikidata", "wikipedia",
            "inhabitedSince", "inhabitedUntil", "civilizations", "site_type"]
    d = json.load(open(src, encoding="utf-8"))
    out, skipped = [], 0
    for f in d.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry")
        if not g or g.get("type") != "Point":
            continue
        s = num(p.get("inhabitedSince"))
        u = num(p.get("inhabitedUntil"))
        if year_from is not None and u is not None and u < year_from:
            skipped += 1
            continue
        if year_to is not None and s is not None and s > year_to:
            skipped += 1
            continue
        if not (p.get("name") or p.get("name.ru") or p.get("wikidata")):
            skipped += 1
            continue
        slim = {k: p[k] for k in KEEP if p.get(k)}
        out.append({"type": "Feature",
                    "properties": slim,
                    "geometry": {"type": "Point",
                                 "coordinates": [round(g["coordinates"][0], 5),
                                                 round(g["coordinates"][1], 5)]}})
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": out},
                  fh, ensure_ascii=False, separators=(",", ":"))
    a = os.path.getsize(src) / 1024
    b = os.path.getsize(dst) / 1024
    print(f"  ✓ {os.path.basename(dst)}: {len(out)} мест "
          f"(отброшено {skipped})   {a:,.0f} КБ → {b:,.0f} КБ  "
          f"(в {a/max(b,0.1):.1f} раза меньше)")
    return dst


# ================================================================== CLI ======
def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]

    if cmd == "places-slim":
        src = args[1] if len(args) > 1 else os.path.join(ROOT, "hb_places.geojson")
        dst = args[2] if len(args) > 2 else os.path.join(ROOT, "maps", "base", "places-historical.geojson")
        yf = num(args[3]) if len(args) > 3 else None
        yt = num(args[4]) if len(args) > 4 else None
        if not os.path.exists(src):
            sys.exit(f"Файл не найден: {src}")
        places_slim(src, dst, yf, yt)
        return 0

    if cmd == "era":
        target = args[1] if len(args) > 1 else "--all"
        if target == "--all":
            dirs = sorted(d for d in glob.glob(os.path.join(ERAS, "*"))
                          if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
        else:
            dirs = [os.path.join(ERAS, target)]
        print("Сборка эпох:")
        for d in dirs:
            build_era(d)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
