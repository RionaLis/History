#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Первичная генерация markdown-контента из компактных таблиц в tools/seed/.

Запуск:  python3 tools/seed_content.py [--force]

Без --force существующие файлы НЕ перезаписываются: правки, сделанные
в Obsidian, сохраняются. Это «посев» базы, дальше контент живёт в content/.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from seed.common import norm_spans, auto_color, fmt_period, TYPE_NAMES  # noqa: E402
from seed.regions import REGIONS, ERAS, LANE_INDEX  # noqa: E402
from seed import ea, in_, sw, eu, af, am, oc, world  # noqa: E402
from seed import p_ea, p_in, p_sw, p_eu, p_af, p_am, p_oc  # noqa: E402
from seed.events import EVENTS as REGION_EVENTS  # noqa: E402
from seed.migrations import MIGRATIONS  # noqa: E402


ENTITIES = (world.ENTITIES
            + ea.ENTITIES + in_.ENTITIES + sw.ENTITIES + eu.ENTITIES
            + af.ENTITIES + am.ENTITIES + oc.ENTITIES
            + p_ea.ENTITIES + p_in.ENTITIES + p_sw.ENTITIES + p_eu.ENTITIES
            + p_af.ENTITIES + p_am.ENTITIES + p_oc.ENTITIES)

EVENTS = world.EVENTS + REGION_EVENTS

ICON_NAMES = {
    "pottery": "керамика / быт", "metal": "технология", "battle": "битва",
    "revolt": "восстание", "revolution": "революция", "migration": "переселение",
    "invasion": "вторжение", "massive": "событие колоссального масштаба",
    "idea": "идея, религия, наука", "disaster": "катастрофа",
}


def yaml_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ":#[]{}&*!|>%@`\"'\n") or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def frontmatter(d):
    lines = ["---"]
    for k, v in d.items():
        if v is None or v == [] or v == "":
            continue
        if isinstance(v, (list, dict)):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def write(path, text, force):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if os.path.exists(full) and not force:
        return False
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перезаписать существующие файлы")
    args = ap.parse_args()
    n_new = 0

    # --- Регионы ---
    for r in REGIONS:
        fm = frontmatter({
            "id": r["id"], "name": r["name"], "short": r["short"], "kind": "region",
            "order": r["order"], "color": r["color"], "hue": r["hue"],
            "lanes": r["lanes"],
        })
        lanes_md = "\n".join(f"- **{l['name']}** `{l['id']}`" for l in r["lanes"])
        body = (f"\n# {r['name']}\n\n> {r['about']}\n\n## Суб-регионы (дорожки таблицы)\n\n"
                f"{lanes_md}\n\n## Обзор\n\n*Раздел в работе.* Здесь будет укрупнённый очерк "
                f"истории региона со ссылками на страны и события.\n\n## См. также\n\n"
                f"- [[Главная синхронологическая таблица]]\n")
        n_new += write(f"content/regions/{r['id']}.md", fm + body, args.force)

    # --- Эпохи ---
    for e in ERAS:
        fm = frontmatter({"id": e["id"], "name": e["name"], "kind": "era",
                          "start": e["start"], "end": e["end"], "color": e["color"]})
        body = (f"\n# {e['name']}\n\n> {e['about']}\n\n**Рамки:** {fmt_period(e['start'], e['end'])}\n\n"
                f"## Содержание эпохи\n\n*Раздел в работе.*\n")
        n_new += write(f"content/eras/{e['id']}.md", fm + body, args.force)

    # --- Сущности (государства, народы, культуры) ---
    seen = set()
    for ent in ENTITIES:
        if ent.id in seen:
            raise SystemExit(f"Дубликат id: {ent.id}")
        seen.add(ent.id)
        spans = norm_spans(ent.spans)
        for sp in spans:
            if sp["lane"] not in LANE_INDEX:
                raise SystemExit(f"{ent.id}: неизвестная дорожка {sp['lane']}")
        primary_region = LANE_INDEX[spans[0]["lane"]][0]["id"]
        regions = []
        for sp in spans:
            rid = LANE_INDEX[sp["lane"]][0]["id"]
            if rid not in regions:
                regions.append(rid)
        color = ent.color or auto_color(ent.id, LANE_INDEX[spans[0]["lane"]][0]["hue"],
                                        kind=ent.type)
        fm = frontmatter({
            "id": ent.id, "name": ent.name, "kind": "entity", "type": ent.type,
            "start": ent.start, "end": ent.end, "region": primary_region,
            "regions": regions, "color": color, "label": ent.label,
            "aliases": ent.aliases, "tags": ent.tags or [ent.type],
            "summary": ent.summary, "spans": spans,
        })
        lanes_md = ", ".join(LANE_INDEX[sp["lane"]][1]["name"] for sp in spans)
        body_text = ent.body or "*Раздел в работе — дополните его в Obsidian.*"
        body = (f"\n# {ent.name}\n\n> {ent.summary}\n\n"
                f"| | |\n|---|---|\n"
                f"| **Тип** | {TYPE_NAMES.get(ent.type, ent.type)} |\n"
                f"| **Период** | {fmt_period(ent.start, ent.end)} |\n"
                f"| **Регионы** | {lanes_md} |\n\n"
                f"## Подробнее\n\n{body_text}\n\n"
                f"## Хронология\n\n- **{ent.start}** — начало\n- **{ent.end}** — окончание\n\n"
                f"## См. также\n\n- [[{LANE_INDEX[spans[0]['lane']][0]['name']}]]\n\n"
                f"## Источники\n\n*Добавьте ссылки на литературу.*\n")
        n_new += write(f"content/entities/{primary_region}/{ent.id}.md", fm + body, args.force)

    # --- События ---
    for ev in EVENTS:
        if ev.lane not in LANE_INDEX:
            raise SystemExit(f"{ev.id}: неизвестная дорожка {ev.lane}")
        region = LANE_INDEX[ev.lane][0]["id"]
        fm = frontmatter({
            "id": ev.id, "name": ev.name, "kind": "event", "year": ev.year,
            "year_end": ev.year_end, "lane": ev.lane, "region": region,
            "icon": ev.icon, "scale": ev.scale, "tags": ev.tags or [ev.icon],
            "summary": ev.summary,
        })
        period = (fmt_period(ev.year, ev.year_end) if ev.year_end
                  else ("%d до н.э." % abs(ev.year) if ev.year < 0 else "%d н.э." % ev.year))
        body = (f"\n# {ev.name}\n\n> {ev.summary}\n\n"
                f"| | |\n|---|---|\n| **Дата** | {period} |\n"
                f"| **Место** | {LANE_INDEX[ev.lane][1]['name']} |\n"
                f"| **Тип** | {ICON_NAMES.get(ev.icon, ev.icon)} |\n\n"
                f"## Подробнее\n\n{ev.body or '*Раздел в работе.*'}\n\n"
                f"## Последствия\n\n*Раздел в работе.*\n\n## Источники\n\n")
        n_new += write(f"content/events/{ev.id}.md", fm + body, args.force)

    # --- Миграции ---
    for m in MIGRATIONS:
        for _, lane in m.points:
            if lane not in LANE_INDEX:
                raise SystemExit(f"{m.id}: неизвестная дорожка {lane}")
        fm = frontmatter({
            "id": m.id, "name": m.name, "kind": "migration", "migration_kind": m.kind,
            "start": m.points[0][0], "end": m.points[-1][0],
            "points": [[y, l] for y, l in m.points],
            "tags": m.tags or ["migration"], "summary": m.summary,
        })
        path_md = "\n".join(
            f"{i + 1}. **{y}** — {LANE_INDEX[l][1]['name']} ({LANE_INDEX[l][0]['short']})"
            for i, (y, l) in enumerate(m.points))
        body = (f"\n# {m.name}\n\n> {m.summary}\n\n## Маршрут\n\n{path_md}\n\n"
                f"## Подробнее\n\n{m.body or '*Раздел в работе.*'}\n\n## Источники\n\n")
        n_new += write(f"content/migrations/{m.id}.md", fm + body, args.force)

    total = len(REGIONS) + len(ERAS) + len(ENTITIES) + len(EVENTS) + len(MIGRATIONS)
    print(f"Создано файлов: {n_new} из {total} "
          f"(регионов {len(REGIONS)}, эпох {len(ERAS)}, сущностей {len(ENTITIES)}, "
          f"событий {len(EVENTS)}, миграций {len(MIGRATIONS)})")
    if not args.force and n_new < total:
        print("Существующие файлы пропущены. Для полной перезаписи: --force")


if __name__ == "__main__":
    main()
