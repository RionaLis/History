#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prep_base.py — подготовка современной подложки из Natural Earth (public domain).

Что делает:
  1. Читает shapefile Natural Earth (без GDAL/QGIS — только pyshp, ставится через pip).
  2. Оставляет ТОЛЬКО нужные поля: русское и английское название, wikidata id,
     точку для подписи, минимальный зум подписи, готовую палитру MAPCOLOR13.
  3. Округляет координаты до 5 знаков (~1 метр) — это минус 30-40% веса.
  4. Пишет компактный GeoJSON в maps/base/.

Запуск:
    pip install pyshp
    python3 tools/prep_base.py

Natural Earth — общественное достояние, указание авторства не обязательно.
"""
import json
import os
import sys

try:
    import shapefile  # pip install pyshp
except ImportError:
    sys.exit("Нужен pyshp:  pip install pyshp")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ne")
DST = os.path.join(ROOT, "maps", "base")
os.makedirs(DST, exist_ok=True)

# Какие поля Natural Earth берём и как их переименовываем для нашего сайта.
KEEP = {
    "NAME":        "name_en",      # английское название
    "NAME_RU":     "name_ru",      # русское название  <-- главное для подписей
    "NAME_LONG":   "name_long",
    "WIKIDATAID":  "wikidata",     # ключ связи со статьёй
    "ISO_A2":      "iso_a2",
    "ISO_A3":      "iso_a3",
    "CONTINENT":   "continent",
    "SUBREGION":   "subregion",
    "POP_EST":     "pop",
    "LABEL_X":     "label_lon",    # куда ставить подпись
    "LABEL_Y":     "label_lat",
    "MIN_LABEL":   "label_z_min",  # с какого зума показывать
    "MAPCOLOR13":  "color_idx",    # готовая палитра: соседи не сливаются

    # ---------------------------------------------------------------
    # ГИДРОГРАФИЯ: те же самые по смыслу поля, но В НИЖНЕМ РЕГИСТРЕ.
    # Это не моя прихоть, а устройство Natural Earth: у культурных слоёв
    # (страны) поля называются NAME / NAME_RU / WIKIDATAID / MIN_LABEL,
    # а у физических (реки, озёра) — name / name_ru / wikidataid / min_label.
    # Если этого не учесть, реки конвертируются БЕЗ НАЗВАНИЙ и без Wikidata,
    # и на карте получаются безымянные синие линии. Проверено на
    # ne_50m_rivers_lake_centerlines: поля именно строчные.
    # ---------------------------------------------------------------
    "name":        "name_en",      # местное/английское название реки
    "name_ru":     "name_ru",      # русское название  <-- главное для подписей
    "name_en":     "name_en",
    "name_alt":    "name_alt",     # альтернативные названия (в т.ч. античные!)
    "wikidataid":  "wikidata",     # ключ связи со статьёй
    "min_label":   "label_z_min",  # с какого зума показывать подпись
    "min_zoom":    "z_min",        # с какого зума рисовать сам объект
    "featurecla":  "ne_class",     # River, Lake, Playas… — тип объекта NE
    "scalerank":   "ne_rank",      # 1 = крупнейшая река, дальше мельче
}


def rnd(x, n=5):
    return round(x, n) if isinstance(x, (int, float)) else x


def clean_coords(g):
    """Рекурсивно округляет координаты и выбрасывает пустые кольца."""
    if g is None:
        return None
    t = g["type"]
    c = g["coordinates"]
    if t == "Point":
        return {"type": t, "coordinates": [rnd(c[0]), rnd(c[1])]}
    if t in ("MultiPoint", "LineString"):
        return {"type": t, "coordinates": [[rnd(p[0]), rnd(p[1])] for p in c]}
    if t == "MultiLineString":
        # КРИТИЧНО ДЛЯ ГИДРОГРАФИИ. Река в Natural Earth часто состоит из
        # нескольких частей (у ne_50m_rivers_lake_centerlines таких 182 из 478),
        # и pyshp отдаёт их как MultiLineString. Без этой ветки функция
        # доходила до `return None` в конце и молча выбрасывала реку целиком.
        # Именно так пропали 183 объекта, включая Ганг, Тибр, Иордан и
        # Оронт — то есть ровно те реки, ради которых историческая карта
        # и делается. Симптом тихий: скрипт печатает «✓ 295 объектов»
        # и не сообщает, что должно было быть 478.
        lines = []
        for part in c:
            if not part:
                continue
            line = [[rnd(p[0]), rnd(p[1])] for p in part]
            if len(line) >= 2:
                lines.append(line)
        return {"type": t, "coordinates": lines} if lines else None
    if t == "GeometryCollection":
        geoms = [clean_coords(x) for x in g.get("geometries", [])]
        geoms = [x for x in geoms if x is not None]
        return {"type": t, "geometries": geoms} if geoms else None
    if t == "Polygon":
        # Внешнее кольцо ОБЯЗАТЕЛЬНО, внутренние (дыры) — по возможности.
        # Прежняя версия брала только c[0] и теряла дыры: у озера с островом
        # остров становился частью воды.
        if not c:
            return None
        rings = []
        for ring in c:
            r2 = [[rnd(p[0]), rnd(p[1])] for p in ring]
            if len(r2) >= 4:
                rings.append(r2)
        return {"type": t, "coordinates": rings} if rings else None
    if t == "MultiPolygon":
        out = []
        for poly in c:
            if not poly:
                continue
            keep = []
            for ring in poly:
                r2 = [[rnd(p[0]), rnd(p[1])] for p in ring]
                if len(r2) >= 4:
                    keep.append(r2)
            if keep:
                out.append(keep)
        return {"type": t, "coordinates": out} if out else None
    return None


def convert(src_name, dst_name, layer_note, verbose=False):
    path = os.path.join(SRC, src_name + ".shp")
    if not os.path.exists(path):
        print(f"  ! {src_name} не найден — пропущено")
        return 0, 0
    sf = shapefile.Reader(path)
    fields = [f[0] for f in sf.fields[1:]]
    feats = []
    dropped = 0
    nulls = 0
    for sr in sf.iterShapeRecords():
        rec = dict(zip(fields, list(sr.record)))
        # ---------------------------------------------------------------
        # В ne_50m_rivers_lake_centerlines есть записи с типом геометрии
        # NULL (shapeType 0). pyshp на них НЕ возвращает пустоту, а бросает
        # shapefile.GeoJSON_Error: 'Shape type "NULL" cannot be represented
        # as GeoJSON' — и весь слой не конвертируется. Проверяем тип до
        # обращения к __geo_interface__.
        # ---------------------------------------------------------------
        shp = sr.shape
        if getattr(shp, "shapeType", 0) in (0, None):
            nulls += 1
            dropped += 1
            continue
        try:
            geom = clean_coords(shp.__geo_interface__)
        except Exception as e:
            dropped += 1
            if verbose:
                print(f"      ! геометрия не читается ({type(e).__name__}) — объект пропущен")
            continue
        if geom is None:
            dropped += 1
            continue
        props = {"_src": layer_note}
        for k, alias in KEEP.items():
            if k in rec:
                v = rec[k]
                if v not in (None, "", -99, "-99"):
                    props[alias] = v
        feats.append({"type": "Feature", "properties": props, "geometry": geom})

    out = os.path.join(DST, dst_name)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats},
                  fh, ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(out) / 1024
    print(f"  ✓ {dst_name}: {len(feats)} объектов, {kb:,.0f} КБ"
          + (f" (отброшено: {dropped}"
             + (f", из них с NULL-геометрией {nulls}" if nulls else "") + ")"
             if dropped else ""))
    return len(feats), kb


if __name__ == "__main__":
    print("Natural Earth → maps/base/")
    tot_kb = 0
    # -----------------------------------------------------------------
    # Гидрография берётся из Natural Earth, а НЕ из OHM, и вот почему.
    # Замерено на живом OHM 22.10.2026:
    #     waterway=river, путей всего          579 250
    #     из них СО start_date                  10 297   (1,8%)
    #     ИМЕНОВАННЫХ и датированных, активных в −2400
    #       во всём Ближнем Востоке (20,5,78,42):      5
    #       во всей Римской империи (−12,30,60,60):    2
    # То есть датированной гидрографии в OHM практически нет, а недоатированную
    # (568 953 пути) нельзя ни отобрать по эпохе, ни скачать — только рамкой,
    # и это сотни мегабайт. Natural Earth — общественное достояние, там
    # 478 рек на масштабе 1:50 млн с name_ru и wikidataid, и этого хватает
    # для мировой карты. Редкие датированные реки OHM идут отдельным слоем.
    # -----------------------------------------------------------------
    for src, dst, note in [
        ("ne_110m_admin_0_countries",       "modern-borders.geojson", "ne110m-admin0"),
        ("ne_110m_lakes",                   "lakes.geojson",          "ne110m-lakes"),
        ("ne_110m_rivers_lake_centerlines", "rivers-110m.geojson",    "ne110m-rivers"),
        ("ne_50m_rivers_lake_centerlines",  "rivers-50m.geojson",     "ne50m-rivers"),
        ("ne_50m_lakes",                    "lakes-50m.geojson",      "ne50m-lakes"),
    ]:
        _, kb = convert(src, dst, note)
        tot_kb += kb
    print(f"\nИтого подложка: {tot_kb:,.0f} КБ")
    print()
    print("Какой масштаб рек брать:")
    print("  rivers-110m  — 13 крупнейших рек мира. Для зумов 0–3, вес копейки.")
    print("  rivers-50m   — 478 рек. Для зумов 4–7, это основной рабочий слой.")
    print("  Для Тигра, Евфрата, Нила, Инда, Ганга, Дуная, Рейна, Тибра")
    print("  НУЖЕН 50m: в 110m их просто нет.")
    print()
    print("Дальше: python3 tools/build_map.py era bc323")
