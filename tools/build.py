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
            clean.append({"lane": lane, "points": pts})
        if not clean:
            errors.append(f"{rel}: нет корректных spans")
            continue
        entities.append({
            "id": fm["id"], "name": fm.get("name", fm["id"]), "type": fm.get("type", "state"),
            "start": int(fm.get("start", clean[0]["points"][0][0])),
            "end": int(fm.get("end", clean[0]["points"][-1][0])),
            "region": fm.get("region") or lane_ids[clean[0]["lane"]],
            "regions": fm.get("regions") or sorted({lane_ids[s["lane"]] for s in clean}),
            "color": fm.get("color", "#bbbbbb"), "label": fm.get("label") or fm.get("name"),
            "summary": fm.get("summary", ""), "tags": fm.get("tags") or [],
            "aliases": fm.get("aliases") or [], "spans": clean, "path": rel,
        })
    entities.sort(key=lambda e: (e["start"], e["id"]))

    events = []
    for full, rel in walk("events"):
        fm, _ = read_md(full)
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
                       "migrations": len(migrations), "eras": len(eras)},
        },
        "scaleAnchors": SCALE_ANCHORS,
        "icons": ICONS,
        "regions": regions, "eras": eras, "entities": entities,
        "events": events, "migrations": migrations, "articles": articles,
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
