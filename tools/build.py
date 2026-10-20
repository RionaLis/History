#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка сайта: content/**/*.md  ->  data/index.json

Запуск:  python3 tools/build.py

Скрипт читает YAML-фронтматтер каждого md-файла, проверяет ссылки на дорожки
и собирает единый индекс, который грузит главная страница. Тексты статей
на сайт не копируются — страница подтягивает сам .md по требованию.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from seed.regions import SCALE_ANCHORS, ICONS, DEFAULT_VISIBLE_RANGE  # noqa: E402

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:  # pragma: no cover
    HAVE_YAML = False


def parse_frontmatter(text):
    """Возвращает (dict, body). Поддерживает YAML; без PyYAML — упрощённый разбор."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    if HAVE_YAML:
        data = yaml.safe_load(raw) or {}
        return data, body
    data = {}
    for line in raw.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            data[key] = None
            continue
        try:
            data[key] = json.loads(val)
        except Exception:
            if re.fullmatch(r"-?\d+", val):
                data[key] = int(val)
            elif val in ("true", "false"):
                data[key] = val == "true"
            else:
                data[key] = val.strip("'\"")
    return data, body


def read_md(path):
    with open(path, "r", encoding="utf-8") as f:
        return parse_frontmatter(f.read())


def walk(subdir):
    base = os.path.join(ROOT, "content", subdir)
    for dirpath, _dirs, files in os.walk(base):
        for fn in sorted(files):
            if fn.endswith(".md"):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                yield full, rel


def main():
    errors, warnings = [], []

    regions = []
    for full, rel in walk("regions"):
        fm, _ = read_md(full)
        if not fm.get("id"):
            errors.append(f"{rel}: нет id")
            continue
        regions.append({
            "id": fm["id"], "name": fm.get("name", fm["id"]),
            "short": fm.get("short", fm.get("name", fm["id"])),
            "order": fm.get("order", 99), "color": fm.get("color", "#cccccc"),
            "hue": fm.get("hue", 0), "lanes": fm.get("lanes", []), "path": rel,
        })
    regions.sort(key=lambda r: r["order"])
    lane_ids = {l["id"]: r["id"] for r in regions for l in r["lanes"]}
    year_min, year_max = SCALE_ANCHORS[0][0], SCALE_ANCHORS[-1][0]

    def clip_points(points):
        """Clip a piecewise-linear thickness series to the visible calendar."""
        if points[-1][0] <= year_min or points[0][0] >= year_max:
            return []
        def at(year):
            for j in range(1, len(points)):
                y0, v0 = points[j - 1]; y1, v1 = points[j]
                if y0 <= year <= y1:
                    if y1 == y0: return v1
                    return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
            return points[0][1] if year < points[0][0] else points[-1][1]
        clipped = [[year_min, at(year_min)]] if points[0][0] < year_min else []
        clipped += [p for p in points if year_min <= p[0] <= year_max]
        if points[-1][0] > year_max:
            clipped.append([year_max, at(year_max)])
        # Remove duplicate boundary points while retaining two endpoints.
        out = []
        for point in clipped:
            if not out or point[0] != out[-1][0]: out.append(point)
        return out

    eras = []
    for full, rel in walk("eras"):
        fm, _ = read_md(full)
        eras.append({"id": fm["id"], "name": fm.get("name"), "start": fm.get("start"),
                     "end": fm.get("end"), "color": fm.get("color", "#ddd"), "path": rel})
    eras.sort(key=lambda e: e["start"])

    entities = []
    for full, rel in walk("entities"):
        fm, _ = read_md(full)
        if not fm.get("id"):
            errors.append(f"{rel}: нет id")
            continue
        spans = fm.get("spans") or []
        clean = []
        had_valid_span = False
        for sp in spans:
            lane = sp.get("lane")
            if lane not in lane_ids:
                errors.append(f"{rel}: неизвестная дорожка '{lane}'")
                continue
            pts = [[int(p[0]), float(p[1])] for p in sp.get("points", [])]
            pts.sort(key=lambda p: p[0])
            if len(pts) < 2:
                errors.append(f"{rel}: у дорожки '{lane}' меньше двух точек")
                continue
            had_valid_span = True
            clipped = clip_points(pts)
            if len(clipped) >= 2:
                clean.append({"lane": lane, "points": clipped})
        if not had_valid_span:
            errors.append(f"{rel}: нет корректных spans")
            continue
        if not clean:
            continue  # объект вне диапазона -4000…2000
        start_year = int(fm.get("start", min(sp["points"][0][0] for sp in clean)))
        end_year = int(fm.get("end", max(sp["points"][-1][0] for sp in clean)))
        entities.append({
            "id": fm["id"], "name": fm.get("name", fm["id"]), "type": fm.get("type", "state"),
            "start": max(year_min, start_year),
            "end": min(year_max, end_year),
            "region": fm.get("region") or lane_ids[clean[0]["lane"]],
            "regions": fm.get("regions") or sorted({lane_ids[s["lane"]] for s in clean}),
            "color": fm.get("color", "#bbbbbb"),
            "label": (fm.get("name") if fm.get("ohm_id") else (fm.get("label") or fm.get("name"))),
            "summary": fm.get("summary", ""), "tags": fm.get("tags") or [],
            "aliases": fm.get("aliases") or [], "spans": clean, "path": rel,
            "areaSeries": fm.get("area_series") or [], "areaSource": fm.get("area_source"),
            "ohmId": fm.get("ohm_id"), "nameOhm": fm.get("name_ohm"),
            "wikidata": fm.get("wikidata"),
        })
    entities.sort(key=lambda e: (e["start"], e["id"]))

    events = []
    for full, rel in walk("events"):
        fm, _ = read_md(full)
        event_year = int(fm.get("year"))
        if event_year < year_min or event_year > year_max:
            continue
        if fm.get("lane") not in lane_ids:
            errors.append(f"{rel}: неизвестная дорожка '{fm.get('lane')}'")
            continue
        events.append({
            "id": fm["id"], "name": fm.get("name"), "year": int(fm.get("year")),
            "yearEnd": fm.get("year_end"), "lane": fm["lane"],
            "region": fm.get("region") or lane_ids[fm["lane"]],
            "icon": fm.get("icon", "massive"), "scale": int(fm.get("scale", 2)),
            "summary": fm.get("summary", ""), "tags": fm.get("tags") or [], "path": rel,
            # необязательные координаты [широта, долгота] — точка появится на карте
            "coords": fm.get("coords"),
        })
    events.sort(key=lambda e: e["year"])

    migrations = []
    for full, rel in walk("migrations"):
        fm, _ = read_md(full)
        pts = []
        for p in fm.get("points", []):
            if p[1] not in lane_ids:
                errors.append(f"{rel}: неизвестная дорожка '{p[1]}'")
                continue
            pts.append([int(p[0]), p[1]])
        if len(pts) < 2:
            errors.append(f"{rel}: маршрут короче двух точек")
            continue
        migrations.append({
            "id": fm["id"], "name": fm.get("name"), "kind": fm.get("migration_kind", "migration"),
            "start": pts[0][0], "end": pts[-1][0], "points": pts,
            "summary": fm.get("summary", ""), "tags": fm.get("tags") or [], "path": rel,
        })
    migrations.sort(key=lambda m: m["start"])

    # Автоматические/ручные связи преемственности государств, подготовленные
    # tools/build_state_flows.py. Отдельно от миграций: это смена политических лент.
    state_flows = []
    flow_path = os.path.join(ROOT, "data", "state-flows.json")
    if os.path.exists(flow_path):
        try:
            flow_doc = json.load(open(flow_path, encoding="utf8"))
            flow_edges = {f["id"]: f for f in flow_doc.get("edges", [])
                           if f.get("kind") != "manual"}
            override_path = os.path.join(ROOT, "data", "state-flow-overrides.json")
            if os.path.exists(override_path):
                overrides = json.load(open(override_path, encoding="utf8"))
                for eid in overrides.get("exclude", []): flow_edges.pop(eid, None)
                manual = overrides.get("include", [])
                manual_pairs = {(f.get("source"), f.get("target")) for f in manual}
                flow_edges = {eid: f for eid, f in flow_edges.items()
                              if f.get("kind") == "manual" or (f.get("source"), f.get("target")) not in manual_pairs}
                for f in manual: flow_edges[f["id"]] = f
            entity_ids = {e["id"] for e in entities}
            state_flows = [f for f in flow_edges.values()
                           if f.get("source") in entity_ids and f.get("target") in entity_ids]
        except (OSError, ValueError):
            warnings.append("data/state-flows.json не удалось разобрать")

    articles = []
    for full, rel in walk("articles"): 
        fm, _ = read_md(full)
        articles.append({"id": fm.get("id", os.path.basename(rel)[:-3]),
                         "name": fm.get("name", ""), "summary": fm.get("summary", ""),
                         "tags": fm.get("tags") or [], "path": rel})

    # --- проверки качества ---
    for e in entities:
        if e["end"] < e["start"]:
            warnings.append(f"{e['id']}: конец раньше начала")
        for sp in e["spans"]:
            for _, share in sp["points"]:
                if not (0 <= share <= 1.0001):
                    warnings.append(f"{e['id']}: доля {share} вне диапазона (0..1]")

    out = {
        "meta": {
            "title": "Синхронологическая таблица всемирной истории",
            "yearMin": SCALE_ANCHORS[0][0], "yearMax": SCALE_ANCHORS[-1][0],
            "defaultRange": DEFAULT_VISIBLE_RANGE,
            "counts": {"regions": len(regions), "lanes": len(lane_ids),
                       "entities": len(entities), "events": len(events),
                       "migrations": len(migrations), "stateFlows": len(state_flows), "eras": len(eras)},
        },
        "scaleAnchors": SCALE_ANCHORS,
        "icons": ICONS,
        "regions": regions, "eras": eras, "entities": entities,
        "events": events, "migrations": migrations, "stateFlows": state_flows, "articles": articles,
    }

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    dest = os.path.join(ROOT, "data", "index.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # Точки событий на карте: сохраняем базовые точки карты и добавляем
    # события с координатами из content/**.md (поле coords: [широта, долгота]).
    geo_dest = os.path.join(ROOT, "assets", "map", "data", "events.geojson")
    try:
        with open(geo_dest, encoding="utf-8") as f:
            geo = json.load(f)
    except (OSError, ValueError):
        geo = {"type": "FeatureCollection", "features": []}
    features = [ft for ft in geo.get("features", [])
                if not ft.get("properties", {}).get("content")]
    n_dots = 0
    for e in events:
        c = e.get("coords")
        if not c or len(c) != 2:
            continue
        try:
            lat, lon = float(c[0]), float(c[1])
        except (TypeError, ValueError):
            warnings.append(f"{e['path']}: coords не числа — точка пропущена")
            continue
        features.append({
            "type": "Feature",
            "properties": {"year": e["year"], "title": e.get("name"),
                           "kind": e.get("icon", "событие"),
                           "text": e.get("summary", ""),
                           "content": e.get("path", "")},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
        n_dots += 1
    with open(geo_dest, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features},
                  f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(dest) / 1024
    print(f"data/index.json — {size:.0f} КБ")
    if n_dots:
        print(f"  точек событий на карте (с coords): {n_dots}")
    print("  регионы: %d, дорожки: %d, сущности: %d, события: %d, миграции: %d"
          % (len(regions), len(lane_ids), len(entities), len(events), len(migrations)))
    for w in warnings:
        print("  [!] " + w)
    if errors:
        print("ОШИБКИ:")
        for e in errors:
            print("  [x] " + e)
        sys.exit(1)


if __name__ == "__main__":
    main()
