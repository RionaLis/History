#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_era.py — автоматический срез эпохи из всех источников разом.

Одна команда вместо десятка: берёт год эпохи, вытаскивает максимум доступных
данных, раскладывает по слоям, открывает в QGIS и печатает отчёт «чего не хватает».

    python3 tools/extract_era.py ohm bc2400                  # срез из дампа OHM
    python3 tools/extract_era.py ohm bc2400 --overpass       # то же, но через API
    python3 tools/extract_era.py pleiades bc2400             # античные места
    python3 tools/extract_era.py all bc2400                  # всё разом
    python3 tools/extract_era.py open bc2400                 # открыть в QGIS
    python3 tools/extract_era.py doctor                      # проверка окружения

Главное отличие от «просто скачать GeoJSON»: инструмент НЕ молчит о проблемах.
Он сам находит и докладывает:

  • объекты без wikidata            → их нельзя связать со статьёй
  • объекты без name:ru             → подпись придётся вводить руками
  • fixme:* из OHM                  → сами картографы OHM помечают недоделки
  • даты с «~» (EDTF)               → «примерно», границу надо сверять с атласом
  • подозрительно длинные периоды   → обычно ошибка датировки
  • перекрывающиеся даты соседей    → два государства на одном месте в один год
  • государства без культуры/народа и наоборот
  • кого из ожидаемого списка нет   → сверяет с expected в era.yml

Результат — maps/eras/<эпоха>/qgis/ (слои) + gaps.md (отчёт) + polities.auto.csv
(заготовка таблицы, уже заполненная тем, что нашлось).

Зависимости: osmium-tool (для дампа), python3-yaml. Никакого GDAL не нужно.
"""

import csv
import glob
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

# -----------------------------------------------------------------------------
# Настройки
# -----------------------------------------------------------------------------

UA = "ChronoMapa/1.0 (historical map project; contact: set-your-email-in-extract_era.py)"

OHM_OVERPASS = "https://overpass-api.openhistoricalmap.org/api/interpreter"
OHM_STATE_TXT = "https://planet.openhistoricalmap.org/planet/state.txt"
OHM_WWW = "https://www.openhistoricalmap.org"

PLEIADES_JSON = "https://atlantides.org/downloads/pleiades/json/pleiades-places-latest.json.gz"
PLEIADES_GIS = "https://atlantides.org/downloads/pleiades/gis/pleiades_gis_data.zip"

# Слои, которые создаёт инструмент. Имя слоя = имя файла = source-layer в тайлах.
LAYERS = ["borders", "cultures", "places", "routes", "migrations", "hydro"]

# ---------------------------------------------------------------------
# ТЕСТОВЫЕ ДАННЫЕ OHM. В базе есть объекты с тегом testbed=yes — это
# учебный полигон, а не история. Замерено 22.10.2026: 277 штук на всю базу
# (56 узлов, 220 путей, 1 отношение).
#
# Выглядят они безобидно и потому опасны: `boundary=administrative`,
# `admin_level=9`, `start_date=0020-02-28`, `name=«Admin 9 9999999 Admin 9»`.
# Фильтр по дате их честно пропускает — 20 год н. э. попадает в срез 117 года.
# В моём мировом срезе 117 года их оказалось 34 из 2324 элементов (1,5%),
# и они заняли верх таблицы государств, вытеснив настоящие провинции.
#
# Отдельный объект того же полигона — заставка «OHM содержит исторические
# данные» (way/198794253): у неё более двухсот тегов name:* с переводом этой
# фразы на все языки раздела, включая name:ru. Она тоже проходит фильтр.
#
# ВАЖНО: именно этот тег, а НЕ географическая рамка, защищает срез от мусора.
# Рамка для мировой эпохи не нужна и даже вредна — см. §IV.4 инструкции.
TESTBED_FILTER = '["testbed"!~"."]'


def is_testbed(tags):
    """True, если объект — учебный полигон OHM, а не исторические данные."""
    if not tags:
        return False
    v = str(tags.get("testbed", "")).strip().lower()
    return bool(v) and v not in ("no", "none", "")

# Поля, которые уходят в каждый полигон/точку. Ровно этот набор потом запекается
# в PMTiles и читается картой через ["get","…"].
FIELDS = [
    "id", "wikidata", "name_ru", "name_local", "name_en", "kind", "status",
    "start", "end", "start_raw", "end_raw", "edtf", "color",
    "label_lon", "label_lat", "label_z_min", "article", "source", "note",
    "ohm_id", "ohm_url", "admin_level", "gap",
]

# Маркеры археологической культуры в названии. OHM НЕ имеет отдельного тега для
# культур — «Bell Beaker culture» висит как boundary=administrative, admin_level=2,
# то есть по тегам неотличим от государства. Поэтому определяем по названию.
# Проверено на реальных данных OHM за 22.10.2026.
CULTURE_WORDS = [
    "culture", "civilisation", "civilization", "kultura", "kultur", "cultura",
    "культура", "культур", "цивилизаци", "цывілізац", "horizon",
]
# Маркеры народа/племени/кочевников — это НЕ государство (нет жёсткой границы)
# и НЕ археологическая культура (это люди, а не материальные остатки).
PEOPLE_WORDS = [
    "people", "tribe", "tribes", "confederacy", "confederation", "nomad",
    "народ", "племя", "племён", "племен", "кочевн", "союз племён", "эллин",
]

# Значения boundary=*, которые вообще встречаются в OHM (замер 22.10.2026,
# 82 539 отношений). Нам нужны те, где может лежать государство, культура или народ.
USEFUL_BOUNDARIES = {
    "administrative": 78757, "political": 14, "indigenous_administration": 62,
    "place": 59, "aboriginal_lands": 2, "civil": 4, "disputed": 3,
}

# Порог «подозрительно долго»: объект, который якобы просуществовал дольше,
# обычно означает ошибку в start_date или end_date.
SUSPICIOUS_SPAN_YEARS = 900

# Цвета по типу объекта — чтобы в QGIS и на сайте государства не сливались
# с культурами и народами.
PALETTE = {
    "state":        "#c8a46b", "empire":       "#b8763f",
    "kingdom":      "#c9a86a", "republic":     "#8fa9c9",
    "city_state":   "#a8c08a", "culture":      "#b9a6c9",
    "civilization": "#9f8fb8", "tribe":        "#c9b79a",
    "nomads":       "#d0c4a8", "confederation": "#a9bfa0",
    "unknown":      "#c8c2b4",
}


# -----------------------------------------------------------------------------
# Мелкие помощники
# -----------------------------------------------------------------------------

def log(msg=""):
    print(msg, flush=True)


def die(msg, code=1):
    print(f"\n✗ {msg}\n", file=sys.stderr, flush=True)
    sys.exit(code)


def warn(msg):
    print(f"  ! {msg}", flush=True)


def have(cmd):
    return shutil.which(cmd) is not None


def load_yaml(path):
    """Читает era.yml. pyyaml если есть, иначе очень простой разбор."""
    if not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8").read()
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass
    # запасной путь: только «ключ: значение» верхнего уровня, без вложенности
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":                      # вложенные блоки пропускаем
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        if v in ("", "null", "~"):
            out[k.strip()] = None
        elif re.fullmatch(r"-?\d+", v):
            out[k.strip()] = int(v)
        elif re.fullmatch(r"-?\d+\.\d+", v):
            out[k.strip()] = float(v)
        else:
            out[k.strip()] = v
    return out


# -----------------------------------------------------------------------------
# Даты. Самая коварная часть: годы до нашей эры и формат EDTF.
# -----------------------------------------------------------------------------

def parse_year(raw):
    """
    «-2400» → -2400,  «117» → 117,  «-0752-04-21» → -752,  «-2499~» → -2499.
    Возвращает (год:int, метка:str) или (None, причина).

    Почему нельзя сравнивать даты строками, как предлагает вики OHM:
    строковое сравнение ломается на смешанной длине. «1945-12-31» > «1945»
    лексикографически — именно поэтому в их примерах пишут t["start_date"] < "1946",
    беря год с запасом. Для дат до нашей эры тот же приём даёт неверный результат:
    «-2400-06-01» < «-2400» как строка, то есть объект, начавшийся в середине
    2400 года до н.э., в срез 2400 года не попадёт. Поэтому сравниваем числами.
    """
    if raw is None:
        return None, "нет"
    s = str(raw).strip()
    if not s:
        return None, "пусто"

    # EDTF-уточнение живёт отдельно; здесь только базовый ISO-год
    s = s.rstrip("~?%").strip()
    if not s:
        return None, "только «~»"

    # «-3200/-3000» — диапазон EDTF: берём раннюю границу, факт диапазона пишем в edtf
    if "/" in s:
        s = s.split("/")[0].strip().rstrip("~?%")

    m = re.match(r"^(-?\d{1,6})", s)
    if not m:
        return None, f"нечитаемо: «{raw}»"
    try:
        year = int(m.group(1))
    except ValueError:
        return None, f"нечитаемо: «{raw}»"

    # OHM допускает ведущий ноль у года до н.э.: «-0752-04-21» = 752 г. до н.э.
    if year == 0:
        return None, "нулевой год (в ISO 8601 его нет)"
    return year, "ok"


def edtf_flags(tags):
    """Собирает оговорки из EDTF-тегов: «примерно», «не позднее чем», диапазон."""
    out = []
    for key in ("start_date:edtf", "end_date:edtf"):
        v = str(tags.get(key, "")).strip()
        if not v:
            continue
        if "~" in v:
            out.append(f"{key}=«{v}» — дата приблизительная")
        if "?" in v:
            out.append(f"{key}=«{v}» — дата под вопросом")
        if "/" in v:
            out.append(f"{key}=«{v}» — это диапазон, а не точка")
        if "%" in v:
            out.append(f"{key}=«{v}» — неуточнённый диапазон")
    return out


def active_at(tags, year):
    """
    Жил ли объект в указанном году.

    Правило OHM: отсутствие start_date = «с начала времён», отсутствие end_date
    = «существует до сих пор». Но по факту в OHM все admin_level=2 имеют
    start_date (проверено: 0 отношений без него), так что «без даты» почти
    всегда означает «не государство», а дорогу или здание.

    Возвращает (да:bool, причина:str, start:int|None, end:int|None).
    """
    s_raw = tags.get("start_date")
    e_raw = tags.get("end_date")
    s, s_note = parse_year(s_raw)
    e, e_note = parse_year(e_raw)

    if s is None and e is None:
        return False, f"дат нет ({s_note})", None, None
    if s is not None and s > year:
        return False, "возник позже", s, e
    if e is not None and e < year:
        return False, "исчез раньше", s, e
    if s is None:
        return True, f"нет start_date ({s_note}) — считаем «с начала времён»", s, e
    return True, "ok", s, e


# -----------------------------------------------------------------------------
# Классификация: государство / культура / народ
# -----------------------------------------------------------------------------

def classify(tags):
    """
    Определяет, ЧТО это за объект. Возвращает (kind, почему).

    Это ключевое место всего инструмента. В OHM нет отдельного тега для
    археологической культуры: «Bell Beaker culture», «Arzachena culture»,
    «Kulli culture», «小珠山文化» висят как boundary=administrative +
    admin_level=2 — ровно так же, как «Elam» или «Древнее царство» (Kemet).
    По тегам государство от культуры неотличимо. Отличать можно только:
      1. по словам в названии (работает для большинства, но не для всех);
      2. по border_type=* (в OHM заполнен у единицы объектов);
      3. вручную — это и есть главная работа в QGIS.
    Инструмент делает 1 и 2 и ЧЕСТНО пишет в отчёт, что решал по названию,
    чтобы вы проверили именно эти строки.
    """
    name = " ".join(str(tags.get(k, "")) for k in ("name", "name:en", "name:ru")).lower()
    bt = str(tags.get("border_type", "")).strip().lower()
    al = str(tags.get("admin_level", "")).strip()
    country = str(tags.get("country", "")).strip().lower()

    # 1. явная подсказка от картографа OHM
    if bt in ("kingdom", "empire", "republic", "state", "city_state"):
        return {"kingdom": "kingdom", "empire": "empire", "republic": "republic",
                "state": "state", "city_state": "city_state"}[bt], f"border_type={bt}"
    if bt in ("culture", "tribe", "people", "nomadic"):
        return bt if bt != "people" else "tribe", f"border_type={bt}"

    # 2. OHM иногда помечает племенные образования тегом country=部落 («племя»)
    if country in ("部落", "tribe", "племя"):
        return "tribe", f"country={country!r}"

    # 3. по словам в названии
    for w in CULTURE_WORDS:
        if w in name:
            # «civilization» может быть и культурой, и государством — помечаем мягче
            kind = "civilization" if w.startswith(("civil", "цивилиз", "цывіл")) else "culture"
            return kind, f"в названии «{w}»"
    for w in PEOPLE_WORDS:
        if w in name:
            return "nomads" if ("nomad" in w or "кочевн" in w) else "tribe", f"в названии «{w}»"

    # 4. точки: города, поселения, памятники. Отдельный тип обязателен —
    #    иначе у Лагаша kind=unknown, и в отчёте его не отличить от мусора.
    place = str(tags.get("place", "")).strip().lower()
    if place:
        if place in ("city", "town"):
            return "city", f"place={place}"
        if place in ("village", "hamlet", "settlement", "neighbourhood"):
            return "settlement", f"place={place}"
        if place in ("country", "state", "region", "county"):
            # Крупная единица, но задана ТОЧКОЙ: ареала нет, значит на карте это
            # может быть только подпись, а не государство. Называем честно.
            return "label", f"place={place}, но это точка — ареала нет, только подпись"
        return "place", f"place={place}"
    hist = str(tags.get("historic", "")).strip().lower()
    if hist:
        if hist in ("archaeological_site", "ruins", "fort", "castle", "citywalls"):
            return "monument", f"historic={hist}"
        return "monument", f"historic={hist}"
    # Дороги и торговые пути. В OHM они лежат как route=road БЕЗ исторической
    # разметки: Via Appia — это просто route=road со start_date=-311. Значений
    # roman_road / trade_route / silk_road / amber_road в базе по нулям
    # (замерено 22.10.2026), поэтому опираться на них нельзя.
    route = str(tags.get("route", "")).strip().lower()
    if route:
        if route == "river":
            return "route", "route=river — водный путь, а не сама река"
        if route in ("tram", "railway", "bus", "train", "subway", "trolleybus",
                     "light_rail", "monorail", "bicycle"):
            return "route", f"route={route} — ВНИМАНИЕ: похоже на современный транспорт"
        return "route", f"route={route}"
    # Реки, озёра, болота, береговая линия
    waterway = str(tags.get("waterway", "")).strip().lower()
    natural = str(tags.get("natural", "")).strip().lower()
    if waterway:
        return "water", f"waterway={waterway}"
    if natural in ("water", "wetland", "coastline", "bay", "glacier", "spring"):
        return "water", f"natural={natural}"

    if str(tags.get("building", "")).strip():
        return "monument", "building=* — постройка, не государство"

    # 5. ничего не подошло — считаем государством, но пишем, что это догадка
    if al == "2":
        return "state", "admin_level=2, маркеров культуры/народа нет"
    if al == "4":
        return "state", "admin_level=4 (провинция/ном)"
    return "unknown", f"тип не определён: admin_level={al or 'нет'}, place/historic пусты"


def ru_name(tags):
    """Русское имя из тегов OHM. name:ru заполнен далеко не у всех."""
    for k in ("name:ru", "name:ru-Latn", "name"):
        v = str(tags.get(k, "")).strip()
        if v:
            return v, ("ohm" if k == "name:ru" else "не переведено")
    return "", "нет имени"


# -----------------------------------------------------------------------------
# Загрузка: планетарный дамп OHM (основной путь)
# -----------------------------------------------------------------------------

def planet_url_latest():
    """Свежая ссылка на дамп. Важно: читать её нужно по https и с домена
    planet.openhistoricalmap.org — вариант s3.amazonaws.com отдаёт 403."""
    req = urllib.request.Request(OHM_STATE_TXT, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        url = r.read().decode("utf-8", "replace").strip()
    if url.startswith("http://"):
        # state.txt отдаёт http-ссылку, а по http S3 отвечает 403 Forbidden
        url = "https://" + url[len("http://"):]
    return url


def run_osmium(args, what):
    log(f"    $ osmium {' '.join(args)}")
    t0 = time.time()
    p = subprocess.run(["osmium"] + args, capture_output=True, text=True)
    dt = time.time() - t0
    if p.returncode != 0:
        die(f"osmium {what} завершился с кодом {p.returncode}:\n{p.stderr.strip()}")
    if p.stderr.strip():
        for line in p.stderr.strip().splitlines()[:6]:
            log(f"      {line}")
    log(f"      готово за {dt:.0f} с")
    return dt


def fetch_from_planet(planet, workdir):
    """
    Один проход по дампу → GeoJSON.

    Почему фильтр именно по start_date, а не по boundary/place/route:
    в OHM датирован примерно каждый объект, который нас интересует, и почти
    никакой лишний. Фильтр по start_date за один проход вытаскивает сразу
    государства, культуры, народы, города, дороги и всё остальное датированное,
    а дальше мы разбираем это в Python по тегам. Три прохода по дампу ради
    трёх наборов тегов заняли бы втрое больше времени и всё равно пропустили бы
    те типы объектов, о которых мы не догадались.

    Осознанная потеря: объекты БЕЗ start_date не попадут вовсе. Для OHM это
    почти всегда «современная» подложка (дороги, здания без дат) — она нам
    не нужна, для неё есть Natural Earth. Все admin_level=2 в OHM имеют
    start_date (проверено запросом: 0 отношений без него), так что государства
    и культуры мы не теряем.
    """
    os.makedirs(workdir, exist_ok=True)
    filt = os.path.join(workdir, "dated.osm.pbf")
    gpoly = os.path.join(workdir, "ohm_polygons.geojson")
    gline = os.path.join(workdir, "ohm_linestrings.geojson")

    if not os.path.exists(planet):
        die(f"дамп OHM не найден: {planet}\n"
            f"  Свежая ссылка: {planet_url_latest()}\n"
            f"  Скачать:  wget -c \"{planet_url_latest()}\" -O ~/ohm/planet.osm.pbf")

    size = os.path.getsize(planet) / 1e9
    log(f"  дамп: {planet} ({size:.2f} ГБ)")

    # -R: не тащить отношения верхнего уровня (chronology) — они без геометрии
    # -r/-w: нужны и отношения-мультиполигоны, и линии (дороги, пути)
    # -n: узлы нужны, чтобы собрать геометрию way'ов
    if os.path.exists(filt):
        log(f"    пропускаю tags-filter: {filt} уже есть (--force чтобы переделать)")
    else:
        log("  [1/3] один проход по дампу: оставляю всё датированное")
        # --omit-referenced: не тянуть все узлы каждого way и все отношения
        # каждого узла. Без этого флага osmium вытаскивает из планеты лишние
        # гигабайты и минуты; с ним остаются ровно те объекты, что нужны.
        run_osmium(["tags-filter", planet, "r/start_date", "w/start_date",
                    "--omit-referenced", "-o", filt, "--overwrite"], "tags-filter")

    log("  [2/3] polygons → GeoJSON (границы, культуры, ареалы)")
    run_osmium(["export", filt, "-f", "geojson", "-o", gpoly, "--overwrite",
                "--geometry-types=polygon", "--add-unique-id=type_and_id"], "export polygon")

    log("  [3/3] linestrings → GeoJSON (дороги, торговые пути)")
    run_osmium(["export", filt, "-f", "geojson", "-o", gline, "--overwrite",
                "--geometry-types=linestring", "--add-unique-id=type_and_id"], "export linestring")

    feats = []
    for p in (gpoly, gline):
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            feats.extend(d.get("features", []))
            log(f"      {os.path.basename(p)}: {len(d.get('features', []))} объектов")
    return feats


# -----------------------------------------------------------------------------
# Загрузка: Overpass OHM (проверка, резерв и работа без дампа)
# -----------------------------------------------------------------------------

def overpass(query, timeout=600, tries=6, cache=None, dump_dir=None):
    """
    Запрос к OHM Overpass. Три особенности, из-за которых наивный клиент падает.

    1. ЛИМИТ 2 ПАРАЛЛЕЛЬНЫХ ЗАПРОСА на сервер. Отсюда «Rate limit: 2» в /api/status.
       Важное следствие: если наш timeout обрывает ожидание, СЕРВЕР ПРОДОЛЖАЕТ
       считать запрос. Следующая попытка тут же упирается в лимит, потому что
       слот занят нашим же предыдущим запросом. Поэтому ждать надо долго
       (60/120/180 с), а не 20 — короткие повторы только усугубляют.

    2. OHM ЗА CLOUDFLARE. Когда сервер перегружен, Cloudflare отдаёт
       HTML-страницу при HTTP 200 и Content-Type: application/json.
       json.load() падает с невнятным «Expecting value: line 1 column 1 (char 0)»,
       и непонятно, то ли запрос кривой, то ли сервер занят. Поэтому тело
       ответа сохраняем на диск и показываем его начало.

    3. Ответ КЭШИРУЕТСЯ. Повторный прогон той же эпохи не дёргает API вообще:
       это и быстрее, и не мешает другим людям, и переживает сбои сервера.
    """
    if cache and os.path.exists(cache):
        log(f"    беру из кэша: {os.path.basename(cache)} "
            f"({os.path.getsize(cache)/1024:.0f} КБ) — API не трогаю")
        with open(cache, encoding="utf-8") as f:
            return json.load(f)

    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(OHM_OVERPASS, data=data,
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            text = body.decode("utf-8", "replace")
            try:
                out = json.loads(text)
            except json.JSONDecodeError:
                _dump(dump_dir, text, f"не-JSON на попытке {i+1}")
                raise RuntimeError(
                    "ответ не JSON (сервер перегружен, Cloudflare отдал страницу). "
                    f"Начало: {text.strip()[:160]!r}")
            if cache:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(text)
            return out
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace").strip()[:300]
            except Exception:
                pass
            _dump(dump_dir, detail, f"HTTP {e.code} на попытке {i+1}")
            last = f"HTTP {e.code} {e.reason}" + (f" — {detail[:160]}" if detail else "")
            if e.code in (429, 504, 502, 503):
                wait = 60 * (i + 1)
                warn(f"Overpass: {last} — жду {wait} с")
                time.sleep(wait)
                continue
            die(f"Overpass вернул {last}\n  Запрос:\n{textwrap.indent(query.strip(), '    ')}")
        except Exception as e:
            last = str(e)
            if i < tries - 1:
                wait = 60 * (i + 1)
                warn(f"Overpass: {last[:150]}")
                warn(f"жду {wait} с и пробую снова (лимит 2 запроса; наш же "
                     "прошлый запрос может ещё считаться на сервере)")
                time.sleep(wait)
    die(f"Overpass не ответил после {tries} попыток: {last}\n"
        f"  Что делать: подождать 5–10 минут и повторить — кэш сохранит уже "
        f"полученные части, повторятся только неудавшиеся запросы.")


def _dump(dump_dir, text, label):
    """Сохраняет мусорный ответ сервера на диск, чтобы его можно было показать."""
    if not dump_dir or not text:
        return
    try:
        os.makedirs(dump_dir, exist_ok=True)
        p = os.path.join(dump_dir, f"overpass_error_{int(time.time())}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# {label}\n\n{text[:20000]}")
        warn(f"тело ответа сохранено: {p}")
    except Exception:
        pass


def bbox_of(feats):
    """Габариты набора объектов — пригодится для bbox-запроса и для отчёта."""
    lons, lats = [], []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) == 2 and all(isinstance(x, (int, float)) for x in c):
                lons.append(c[0]); lats.append(c[1])
            else:
                for x in c:
                    walk(x)
    for f in feats:
        g = (f.get("geometry") or {})
        walk(g.get("coordinates"))
    if not lons:
        return None
    return min(lons), min(lats), max(lons), max(lats)


DATE_FILTER = ('number(t["start_date"]) <= {Y} && '
               '(!is_tag("end_date") || number(t["end_date"]) >= {Y})')


def _ring(pts):
    """Список {"lat","lon"} от Overpass → кольцо GeoJSON [[lon,lat], …].
    Кольцо полигона должно быть замкнуто — Overpass этого не гарантирует."""
    r = [[p["lon"], p["lat"]] for p in pts if "lat" in p and "lon" in p]
    if len(r) >= 3 and r[0] != r[-1]:
        r.append(r[0])
    return r if len(r) >= 4 else None


def relation_to_geometry(e):
    """
    Собирает мультиполигон из members отношения.

    Это нужно потому, что Overpass `out geom` НЕ отдаёт геометрию отношения
    на верхнем уровне — в ответе есть только `members`, у каждого своя
    `geometry`. Наивный разбор теряет ВСЕ границы: именно так в первом прогоне
    43 полигона превратились в 0.

    Правила сборки — те же, что в OSM:
      • way с role="outer"  → внешние кольца
      • way с role="inner"  → дырки (озёра, анклавы)
      • role="" считается как outer
      • члены-узлы (admin_centre, label) в геометрию не входят
    Полноценная сборка требует связывать кольца по общим узлам; здесь кольца
    берутся как есть — для просмотра в QGIS и для отчёта этого достаточно,
    а боевую геометрию вы всё равно обводите сами.
    """
    outers, inners, pts = [], [], []
    for m in e.get("members", []):
        g = m.get("geometry")
        if m.get("type") == "node":
            if m.get("lat") is not None:
                pts.append([m["lon"], m["lat"]])
            continue
        if not isinstance(g, list) or len(g) < 2:
            continue
        ring = _ring(g)
        if not ring:
            continue
        role = (m.get("role") or "").lower()
        (inners if role == "inner" else outers).append(ring)

    if not outers:
        return None
    # дырки распределяем по внешним кольцам грубо: все в первое.
    # Для просмотра и отчёта годится; точность даёт обводка в QGIS.
    polys = [[outers[0]] + inners] + [[o] for o in outers[1:]]
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def normalize_geometry(e, node_index=None):
    """
    Приводит ответ Overpass к GeoJSON-геометрии. Четыре разные формы:

      • way + `out geom`   → e["geometry"] = СПИСОК {"lat","lon"}. Это Overpass QL,
                             не GeoJSON: наивная проверка g.get("coordinates") падает
                             с AttributeError: 'list' object has no attribute 'get'.
                             Замкнутый список = Polygon, иначе LineString.
      • relation + `out geom` → геометрии на верхнем уровне НЕТ, только members.
                             Собираем мультиполигон (см. relation_to_geometry).
      • node               → geometry нет вовсе, есть lat/lon на верхнем уровне.
                             Если брать только e["geometry"], теряются все города.
      • ничего не подошло  → центр из bounds, чтобы объект хотя бы было видно.
    """
    # 1. way
    g = e.get("geometry")
    if isinstance(g, list) and g and isinstance(g[0], dict):
        ring = _ring(g)
        if ring and len(g) >= 4 and _closed(g):
            return {"type": "Polygon", "coordinates": [ring]}
        line = [[p["lon"], p["lat"]] for p in g if "lat" in p and "lon" in p]
        if len(line) >= 2:
            return {"type": "LineString", "coordinates": line}

    # 2. уже готовый GeoJSON (например, после osmium export)
    if isinstance(g, dict) and g.get("type") and g.get("coordinates"):
        return g

    # 3. relation — сборка из members
    if e.get("type") == "relation":
        r = relation_to_geometry(e)
        if r:
            return r

    # 4. node
    if e.get("lat") is not None and e.get("lon") is not None:
        return {"type": "Point", "coordinates": [e["lon"], e["lat"]]}
    if node_index:
        hit = node_index.get(e.get("id"))
        if hit:
            return {"type": "Point", "coordinates": hit}

    # 5. крайний случай — центр габаритов
    b = e.get("bounds") or e.get("center")
    if isinstance(b, dict):
        if "minlat" in b:
            lon = (b["minlon"] + b["maxlon"]) / 2
            lat = (b["minlat"] + b["maxlat"]) / 2
        else:
            lon, lat = b.get("lon"), b.get("lat")
        if lon is not None and lat is not None:
            return {"type": "Point", "coordinates": [lon, lat], "_center_only": True}
    return None


def _closed(pts):
    """Замкнут ли список точек Overpass (первая = последняя)."""
    if len(pts) < 4:
        return False
    a, b = pts[0], pts[-1]
    return abs(a.get("lat", 0) - b.get("lat", 1)) < 1e-9 and \
           abs(a.get("lon", 0) - b.get("lon", 1)) < 1e-9


def fetch_from_overpass(year, bbox=None):
    """
    Срез эпохи через API. Тот же результат, что из дампа, но:
      + не нужен файл на 1,3 ГБ и osmium
      − лимит 2 параллельных запроса у сервера

    ДВЕ НЕОЧЕВИДНЫЕ ВЕЩИ, из-за которых наивный запрос даёт неверный ответ.
    Обе проверены на живом OHM 22.10.2026, срез −2400 г., регион 20–78 в.д.:

    1. РАМКА НЕ РАБОТАЕТ ДЛЯ ОТНОШЕНИЙ. Замер:
           relation["admin_level"="2"] … -2400           → 10 отношений
           relation(20,5,78,42)["admin_level"="2"] … -2400 →  2 отношения
       Пропали Kulli, Indus Valley, Elam, Dilmun, Magan — хотя их центры
       lon 49–70, lat 24–30 лежат ВНУТРИ рамки. Зато Arzachena (центр lon 9.2,
       ВНЕ рамки) осталась. Причина: для отношения Overpass учитывает только
       те узлы-участники, что попали в рамку, а у OHM-отношений узлы разбросаны
       по миру. Рамка для узлов при этом работает честно:
           node["place"] … -2400  без рамки → 197, с рамкой → 43.
       Поэтому: отношения берём ВСЕГДА глобально, рамку применяем к узлам и
       линиям, а отношения фильтруем по геометрии уже в Python.

    2. СТРОКОВОЕ СРАВНЕНИЕ ДАТ ЛОМАЕТСЯ НА ГОДАХ ДО НАШЕЙ ЭРЫ. Вики OHM
       рекомендует t["start_date"] < "1946" — строкой. Для нашей эры это
       работает, для до нашей — нет: "-2598" лексикографически БОЛЬШЕ "-2399",
       поэтому Индская цивилизация (-2598…-1899) в срез -2400 строковым
       фильтром не попадает. Используем number() — числовое сравнение, оно
       держит отрицательные годы. Проверено: 0 отношений с непарсящейся датой.

    И третье, мелкое: узлы Overpass отдаёт БЕЗ поля geometry, только lat/lon
    на верхнем уровне. Если брать только e["geometry"], все города теряются.
    """
    filt = DATE_FILTER.replace("{Y}", str(year))
    pts = f"({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]})" if bbox else ""

    # Запрос 1: отношения и линии — ВСЕГДА глобально (см. причину 1)
    q_areas = f"""
[out:json][timeout:600];
(
  relation["boundary"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["boundary"]["start_date"]{TESTBED_FILTER}(if: {filt});
  relation["place"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["place"]["start_date"]{TESTBED_FILTER}(if: {filt});
  relation["route"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["route"]["start_date"]{TESTBED_FILTER}(if: {filt});
  relation["historic"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["historic"]["start_date"]{TESTBED_FILTER}(if: {filt});
);
out geom;
"""
    # Запрос 2: ГИДРОГРАФИЯ ЭПОХИ. Отдельный запрос и обязательно с ["name"]:
    # без имени это 579 250 путей на весь мир (замер), с именем и датой —
    # всего 140 на 117 год. Без имени скачивать нельзя: упрёмся в память,
    # как уперлись с наивным `out geom` по рамке (код возврата 137).
    # Рамку к путям не применяем по той же причине, что и к отношениям.
    q_hydro = f"""
[out:json][timeout:600];
(
  way["waterway"]["name"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["natural"="water"]["name"]["start_date"]{TESTBED_FILTER}(if: {filt});
  relation["natural"="water"]["name"]["start_date"]{TESTBED_FILTER}(if: {filt});
  way["water"]["name"]["start_date"]{TESTBED_FILTER}(if: {filt});
);
out geom;
"""

    # Запрос 3: точечные объекты — рамку применяем здесь, для узлов она честная
    q_points = f"""
[out:json][timeout:600];
(
  node{pts}["place"]["start_date"]{TESTBED_FILTER}(if: {filt});
  node{pts}["historic"]["start_date"]{TESTBED_FILTER}(if: {filt});
);
out center;
"""
    feats = []
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "maps", "_cache", "overpass")
    tag = re.sub(r"\W+", "_", f"{year}_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}") if bbox else str(year)
    for label, q, cname in (
            ("полигоны и линии (глобально)", q_areas, f"areas_{tag}.json"),
            ("точки" + (" (в рамке)" if bbox else " (глобально)"), q_points, f"points_{tag}.json"),
            ("реки и озёра эпохи (только именованные)", q_hydro, f"hydro_{tag}.json")):
        log(f"  Overpass: {label}…")
        d = overpass(q, timeout=900, cache=os.path.normpath(os.path.join(cache_dir, cname)),
             dump_dir=os.path.normpath(cache_dir))
        els = d.get("elements", [])
        got = 0
        skipped = 0
        for e in els:
            t = dict(e.get("tags", {}))
            t["osm_type"] = e.get("type")
            t["osm_id"] = e.get("id")
            g = normalize_geometry(e)
            if g is None:
                skipped += 1
                continue
            feats.append({"type": "Feature", "properties": t, "geometry": g})
            got += 1
        log(f"    элементов пришло {len(els)}, с геометрией {got}"
            + (f", без геометрии отброшено {skipped}" if skipped else ""))
    return feats


def in_bbox(geom, bbox):
    """Своя проверка попадания в рамку — потому что рамке Overpass для отношений
    доверять нельзя (см. fetch_from_overpass, причина 1)."""
    if not bbox:
        return True
    w, s, e, n = bbox
    pts = []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) == 2 and all(isinstance(x, (int, float)) for x in c):
                pts.append(c)
            else:
                for x in c:
                    walk(x)
    walk((geom or {}).get("coordinates"))
    if not pts:
        return False
    # объект в рамке, если в неё попала хотя бы одна вершина ИЛИ его центр.
    # Только вершины недостаточно: культура колоколовидных кубков имеет центр
    # в Испании (lon −5), а её ареал заходит в регион — по вершинам она
    # проходила, но государства вроде Catawba (lon −80) тоже тянули свои
    # вершины в рамку. Центр решает обе проблемы.
    if any(w <= p[0] <= e and s <= p[1] <= n for p in pts):
        return True
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return w <= cx <= e and s <= cy <= n


# -----------------------------------------------------------------------------
# Разбор: сырые объекты OHM → слои эпохи
# -----------------------------------------------------------------------------

def is_line(geom):
    return (geom or {}).get("type") in ("LineString", "MultiLineString")


def centroid(geom):
    """Грубый центроид для точки подписи. Точнее считается в QGIS,
    но для подписи государства этого хватает."""
    pts = []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) == 2 and all(isinstance(x, (int, float)) for x in c):
                pts.append(c)
            else:
                for x in c:
                    walk(x)
    walk((geom or {}).get("coordinates"))
    if not pts:
        return None, None
    return round(sum(p[0] for p in pts) / len(pts), 5), round(sum(p[1] for p in pts) / len(pts), 5)


# start_date=0 в OHM — это НЕ «нулевой год».
#
# Нулевого года не существует: по астрономической нумерации, которой следует
# OHM, за 1 годом н. э. идёт 0 = 1 год до н. э., и дата «0» означала бы ровно
# его. Но в данных «0» массово используется как заглушка «начало неизвестно».
# Замерено 22.10.2026 на срезе 117 года: у ВСЕХ 44 объектов «Canal de la Deûle»
# и «Leie» стоит start_date=0 при end_date 1617…1994. Это бельгийские и
# французские каналы Нового времени, и фильтр «start_date <= 117» пропускал их
# все — карта Римской империи заполнилась современными каналами.
#
# Признак заглушки: start_date=0 И end_date в наше время (>1500). Тогда объект
# отбрасывается. Если end_date древний или отсутствует — объект сохраняется,
# но помечается: например, Aral Sea (start_date=0, end_date=1960) в 117 году
# существовал, и отбрасывать его было бы ошибкой.
SENTINEL_START = 0
SENTINEL_END_AFTER = 1500


def is_sentinel_start(s_raw, e_val):
    """start_date=0 при современном end_date = заглушка «начало неизвестно»."""
    try:
        s_val = int(str(s_raw).strip()[:5])
    except (TypeError, ValueError):
        return False
    if s_val != SENTINEL_START:
        return False
    return e_val is not None and e_val > SENTINEL_END_AFTER


def geom_class(geom):
    """
    Класс геометрии: point / line / poly. Нужен для группировки хронологий.

    Почему нельзя группировать по одному имени: в OHM рядом живут УЗЕЛ города
    и ПОЛИГОН его границы под одним названием. Реальный пример, найденный при
    отладке: «Micia» — node/2083197115 (106…275) и way/198283407 (106…450).
    Это точка-метка и ареал, оба нужны на карте. Первая версия группировки
    склеила их, оставив только узел.
    """
    t = (geom or {}).get("type", "")
    if t in ("Point", "MultiPoint"):
        return "point"
    if t in ("LineString", "MultiLineString"):
        return "line"
    if t in ("Polygon", "MultiPolygon"):
        return "poly"
    return "?"


def approx_deg(lon1, lat1, lon2, lat2):
    """
    Расстояние между двумя точками в градусах (эквидистантная проекция).
    Точность для наших целей достаточная: мы различаем «тот же объект»
    и «другой объект за 300 км», а не измеряем километры.

    Один градус широты ≈ 111 км, один градус долготы ≈ 111·cos(широты) км.
    """
    import math
    try:
        dlat = float(lat2) - float(lat1)
        dlon = (float(lon2) - float(lon1)) * math.cos(math.radians((float(lat1) + float(lat2)) / 2))
    except (TypeError, ValueError):
        return 1e9
    return math.hypot(dlon, dlat)


# Насколько близко должны лежать два объекта, чтобы считаться стадиями ОДНОГО.
# 0.5° ≈ 55 км: достаточно, чтобы разные отрезки одной длинной реки НЕ
# склеивались, но шесть полигонов одного города — склеивались.
CHRONO_TOL_DEG = 0.5


def build_records(feats, year, window):
    """
    Превращает сырые объекты в записи эпохи и попутно собирает проблемы.

    window — запас по годам вокруг точки эпохи. Срез «в году -2400» почти
    бесполезен: границы менялись постоянно, и хочется видеть, что было рядом
    по времени. Поэтому берём всё, что жило в [year-window, year+window],
    а сам год эпохи отмечаем отдельно в status.
    """
    y0, y1 = year - window, year + window
    # Верхняя граница эпохи. Объект, который ВОЗНИК позже неё, на карте эпохи
    # появиться не может, даже если формально «активен»: дорога N90 с
    # start_date=0 и end_date=1970 проходит фильтр «активен в 117 году»,
    # но это французское шоссе XX века. Без отсечения такие объекты
    # заполняют слой routes мусором — на Римской империи их оказалось
    # больше половины из 41.
    exclude_after = y1
    out = []
    dropped_modern = []
    chronologies = []      # объекты, у которых в OHM несколько стадий геометрии
    seen_chrono = {}       # (имя, admin_level, kind) → данные лучшей стадии
    seen_wd = {}          # wikidata → (start, end, тип объекта, индекс в out)
    dupes = []
    for f in feats:
        t = f.get("properties") or {}
        geom = f.get("geometry") or {}
        if not geom.get("coordinates"):
            continue

        ok, why, s, e = active_at(t, year)
        if not ok:
            # объект не жил в этом году — но мог жить рядом по времени;
            # такие отбрасываем, они и есть «шум» в срезе
            continue

        kind, kind_why = classify(t)
        name, name_state = ru_name(t)
        wd = str(t.get("wikidata", "")).strip()
        if wd and not re.fullmatch(r"Q\d+", wd):
            wd = ""                                  # битый формат — не пускаем дальше

        osm_type = t.get("osm_type", "")
        osm_id = t.get("osm_id", "")
        ohm_id = f"{osm_type}/{osm_id}" if osm_type and osm_id else ""
        ohm_url = f"{OHM_WWW}/{osm_type}/{osm_id}" if osm_type and osm_id else ""

        gaps = []
        # --- 1. что не даёт связать объект со статьёй
        if not wd:
            gaps.append("нет wikidata — объект не свяжется со статьёй")
        if name_state != "ohm":
            gaps.append("нет name:ru — подпись придётся ввести руками")
        if not name and not str(t.get("name", "")).strip():
            gaps.append("нет имени вообще")

        # --- 2. что OHM сам помечает как недоделку
        for k in sorted(t):
            if k.startswith("fixme"):
                gaps.append(f"OHM fixme: {k}=«{t[k]}»")

        # --- 3. ненадёжные даты
        for g in edtf_flags(t):
            gaps.append(g)
        if s is not None and e is not None and abs(e - s) > SUSPICIOUS_SPAN_YEARS:
            gaps.append(f"подозрительно долгий период: {s}…{e} "
                        f"({abs(e - s)} лет) — проверьте датировку")
        if s is None:
            gaps.append("нет start_date — объект показан «с начала времён»")
        elif str(t.get("start_date", "")).strip() in ("0", "0000", "-0000"):
            gaps.append("start_date=0 — в OHM это обычно заглушка «начало "
                        "неизвестно», а не нулевой год. Объект оставлен, потому "
                        "что end_date древний или отсутствует, но начало надо "
                        "проверить по источнику")

        # --- 4. классификация была догадкой
        if kind_why.startswith(("admin_level", "в названии")):
            gaps.append(f"тип «{kind}» определён по {kind_why} — проверьте")

        # --- 5. проверки, найденные на реальных данных OHM (города, письмена, даты)
        gaps.extend(object_gap_flags(t, kind, s, e))

        # --- 0. дубль того же объекта под другим id?
        osm_type = t.get("osm_type", "")
        # ХРОНОЛОГИЯ OHM: у одного объекта бывает несколько геометрий,
        # по одной на стадию существования. Реальный пример — Кёльн:
        #   way/198587370  Colonia Claudia Ara Agrippinensium  50…1106
        #   way/198587372  Colonia Claudia Ara Agrippinensium  50…0947
        #   way/198587373  Colonia Claudia Ara Agrippinensium  50…1179
        #   way/198587374  Colonia Claudia Ara Agrippinensium  50…1106
        #   …всего шесть путей с одним названием.
        # Это не дубли: даты конца разные. Но на карте они нарисуются шестью
        # наложенными полигонами одного цвета. Для эпохи нужна ОДНА геометрия,
        # поэтому выбираем стадию, покрывающую опорный год, и группируем
        # остальные в отчёт — а не молча выбрасываем.
        if is_sentinel_start(t.get("start_date"), e):
            dropped_modern.append(
                f"{ohm_id} «{name}»: start_date=0 при end_date={e}. "
                f"Ноль в OHM — это заглушка «начало неизвестно», а не нулевой год: "
                f"объект с концом в {e} г. возник явно позже {year} года")
            continue
        # Учебный полигон OHM. На пути через Overpass такие объекты отсекаются
        # ещё в запросе, но из планетарного дампа они приходят все, поэтому
        # проверяем и здесь.
        if is_testbed(t):
            dropped_modern.append(
                f"{ohm_id} «{name}»: testbed={t.get('testbed')} — учебный "
                f"полигон OHM, а не исторические данные")
            continue

        # Безымянный объект без wikidata на карте нечитаем: ни подписи, ни
        # ссылки на статью. На срезе 117 года таких в слое routes оказалось
        # 8 из 19 — все с датами вида 90…1940 и пустым name. Это не данные,
        # это мусор, и он вытеснял настоящие дороги вроде Via Appia.
        if not name and not wd and not str(t.get("name", "")).strip():
            dropped_modern.append(
                f"{ohm_id}: нет ни имени, ни wikidata — на карте это было бы "
                f"безымянная линия или пятно. Отброшен")
            continue

        if s is not None and s > exclude_after:
            dropped_modern.append(
                f"{ohm_id} «{name}» возник в {s} г., "
                f"то есть ПОСЛЕ конца эпохи ({exclude_after}) — на карте эпохи ему не место")
            continue
        lon0, lat0 = centroid(geom)

        # --- ХРОНОЛОГИЯ: одно имя + admin_level + тип + класс геометрии
        #     + близость = стадии одного объекта.
        al = str(t.get("admin_level", ""))
        gcls = geom_class(geom)
        ck = (str(t.get("name", "")).strip().lower(), al, kind, gcls)
        if ck[0] and not wd and gcls in ("line", "poly"):
            # Точки НЕ группируем: два узла с одним именем в одном месте — это
            # дубль данных OHM (реальный пример: «Sucidava», node/2083244055 и
            # node/2083197347, оба 106…275), а не стадии. Пусть оба останутся
            # и попадут в раздел «полные дубли», где их видно.
            # Группируем только когда нет wikidata: с ним надёжнее ключ wd,
            # и он уже обработан ниже. Здесь же ловим случай Кёльна, у которого
            # шесть путей «Colonia Claudia Ara Agrippinensium» без единого Q-номера.
            prev = seen_chrono.get(ck)
            if prev and approx_deg(prev["lon"], prev["lat"], lon0, lat0) > CHRONO_TOL_DEG:
                # Одно имя, но разные места: это НЕ стадии одного объекта.
                # Именно так устроена длинная река — Нил, Дунай, Рейн лежат
                # несколькими отрезками с общим именем, и склеивать их нельзя.
                # Первая версия группировки их склеила, и слой гидрографии
                # схлопнулся со 183 рек до 60.
                prev = None
            if prev:
                p_span = abs((prev["e"] if prev["e"] is not None else y1)
                             - (prev["s"] if prev["s"] is not None else y0))
                c_span = abs((e if e is not None else y1) - (s if s is not None else y0))
                if c_span < p_span:
                    # текущая стадия точнее описывает именно эту эпоху — меняем
                    out[prev["idx"]] = None
                    chronologies.append(
                        f"«{name}» (admin_level={al or '—'}): в OHM несколько стадий. "
                        f"Отброшена {prev['id']} с датами {prev['s']}…{prev['e']}, "
                        f"оставлена {ohm_id} с датами {s}…{e} — она ближе к {year} году")
                    seen_chrono[ck] = {"s": s, "e": e, "id": ohm_id, "idx": len(out),
                                   "lon": lon0, "lat": lat0}
                else:
                    chronologies.append(
                        f"«{name}» (admin_level={al or '—'}): в OHM несколько стадий. "
                        f"Отброшена {ohm_id} с датами {s}…{e}, оставлена {prev['id']} "
                        f"с датами {prev['s']}…{prev['e']}")
                    continue
            else:
                seen_chrono[ck] = {"s": s, "e": e, "id": ohm_id, "idx": len(out),
                                   "lon": lon0, "lat": lat0}

        if wd:
            prev = seen_wd.get(wd)
            if prev and prev[0] == s and prev[1] == e:
                # даты совпадают полностью — это один объект, продублированный
                # в OHM как way и как relation. Оставляем отношение.
                if osm_type == "relation" and prev[2] != "relation":
                    dupes.append(f"{wd}: оставлен {ohm_id} вместо "
                                 f"{prev[2]}/{prev[3]} (полный дубль дат {s}…{e})")
                    out[prev[4]] = None
                else:
                    dupes.append(f"{wd}: отброшен дубль {ohm_id} "
                                 f"(тот же объект и те же даты {s}…{e}, "
                                 f"уже есть {prev[2]}/{prev[3]})")
                    continue
            elif prev:
                dupes.append(f"{wd}: «{name}» встречается "
                             f"с РАЗНЫМИ датами ({prev[0]}…{prev[1]} и {s}…{e}) — "
                             f"это либо хронология OHM, либо противоречие в данных")
            seen_wd[wd] = (s, e, osm_type, osm_id, len(out))

        lon, lat = lon0, lat0
        rec = {k: "" for k in FIELDS}
        nm_orig = str(t.get("name", "")).strip()
        nm_en = str(t.get("name:en", "")).strip()
        if not nm_en and nm_orig and not re.search(r"[\u0400-\u04ff\u0600-\u06ff\u4e00-\u9fff]", nm_orig):
            nm_en = nm_orig        # имя уже латиницей — используем как английское
        rec.update({
            "id": wd or ohm_id or f"{kind}_{len(out)}",
            "wikidata": wd,
            "name_ru": name,
            "name_local": nm_orig,
            "name_en": nm_en,
            "kind": kind,
            "status": "ok" if not gaps else "needs-review",
            "start": s if s is not None else "",
            "end": e if e is not None else "",
            "start_raw": str(t.get("start_date", "")),
            "end_raw": str(t.get("end_date", "")),
            "edtf": " | ".join(edtf_flags(t)),
            "color": PALETTE.get(kind, PALETTE["unknown"]),
            "label_lon": lon if lon is not None else "",
            "label_lat": lat if lat is not None else "",
            "label_z_min": 3 if kind in ("empire", "civilization", "culture") else 4,
            "source": f"OpenHistoricalMap {ohm_id} (CC0)" if ohm_id
                      else "OpenHistoricalMap (CC0)",
            "note": kind_why,
            "ohm_id": ohm_id,
            "ohm_url": ohm_url,
            "admin_level": str(t.get("admin_level", "")),
            # маркеры для раскладки по слоям: у точки place=* это город,
            # а не государство, даже если kind вышел «unknown»
            "_place": str(t.get("place", "")),
            "_historic": str(t.get("historic", "")),
            "_natural": str(t.get("natural", "")),
            "_waterway": str(t.get("waterway", "")),
            "_boundary": str(t.get("boundary", "")),
            "gap": "; ".join(gaps),
        })
        out.append((rec, geom, is_line(geom)))
    out = [x for x in out if x is not None]
    build_records.last_dupes = dupes
    build_records.last_dropped_modern = dropped_modern
    build_records.last_chronologies = chronologies
    return out


def mixed_script(s):
    """«Konya كونيا» — два языка в одном поле name. Так в OHM бывает,
    и подпись на карте получится кашей: имя надо разнести на name и name:ar."""
    if not s:
        return False
    has_latin = bool(re.search(r"[A-Za-z]", s))
    has_other = bool(re.search(r"[\u0600-\u06ff\u0400-\u04ff\u4e00-\u9fff\u0590-\u05ff]", s))
    return has_latin and has_other


# ---------------------------------------------------------------------
# КАЧЕСТВО ДАТИРОВКИ. OHM сам признаётся, что дата проставлена наугад, —
# и это надо показывать, иначе вы будете дорисовывать в QGIS то, чему
# нельзя верить.
#
# Замерено 22.10.2026 на мировом срезе 117 года н. э., кэш Overpass:
#
#   hydro_117.json  (210 именованных водоёмов с датой):
#       start_date:fixme = arbitrary ....... 120  (57%!)
#       fixme = arbitrary end_date .........  43
#       end_date:fixme = arbitrary .........   3
#       testbed = yes ......................   5
#   areas_117.json:
#       start_date:fixme = arbitrary .......  34
#       fixme = arbitrary end_date;arbitrary start_date ... 4
#       fixme = «These boundaries are at Baekje's peak in 375, not 42-562»  1
#   points_117.json:
#       fixme = «Exact start and end dates»  122
#       fixme = «Location is estimation and dates are also estimations…
#                …Ohlone…» ................  57
#       fixme = то же про Coast Miwok ......  37
#
# Слово `arbitrary` в OHM означает буквально «произвольно»: дату поставили,
# чтобы объект попадал в срезы, а не потому, что она известна. Такие объекты
# на карте выглядят как точные данные, и это главная ловушка источника.
DATE_SUSPECT_KEYS = ("start_date:fixme", "end_date:fixme",
                     "start_date:source", "end_date:source")


def date_flags(tags):
    """
    Пометки о недостоверности ДАТЫ объекта. Возвращает список строк.
    Работает для всех типов: границ, культур, городов, рек, путей.
    """
    out = []
    if not tags:
        return out

    # 1. OHM прямо пишет, что дата произвольная
    for key in DATE_SUSPECT_KEYS:
        v = str(tags.get(key, "") or "").strip().lower()
        if not v:
            continue
        if "arbitrary" in v or "arbitrar" in v:
            out.append(f"дата проставлена ПРОИЗВОЛЬНО ({key}=arbitrary): "
                       "объект попадает в срезы, но его возраст не установлен. "
                       "Не опирайтесь на эту дату — найдите источник")
        elif v and key.endswith(":fixme"):
            out.append(f"{key}: {v[:120]}")

    # 2. Общие fixme, где говорится именно про даты или про оценку
    for key in ("fixme", "fixme:e", "fixme:s", "note", "note:dates"):
        v = str(tags.get(key, "") or "").strip()
        if not v:
            continue
        low = v.lower()
        if "arbitrary" in low and ("start_date" in low or "end_date" in low):
            out.append(f"{key}: {v[:140]} — OHM сам помечает дату как произвольную")
        elif "estimation" in low or "approximate" in low or "dates are" in low:
            out.append(f"{key}: {v[:140]} — датировка и/или положение оценочные, "
                       "автор данных сам в этом признаётся")
        elif ("exact start" in low or "exact date" in low
              or "start and end dates" in low or "needs date" in low
              or "check date" in low or "date?" in low):
            out.append(f"{key}: {v[:140]} — точные даты не установлены")
        elif "peak" in low and "not" in low:
            # Реальный пример из данных: «These boundaries are at Baekje's peak
            # in 375, not 42-562». Ареал дан на момент наибольшего расширения,
            # а не на дату объекта — для среза по году это подмена.
            out.append(f"{key}: {v[:140]} — ВАЖНО: границы даны на момент "
                       "наибольшего расширения, а не на дату объекта")

    return out


def object_gap_flags(tags, kind, s, e):
    """
    Проверки для ТОЧЕК (города, памятники) — отдельные от проверок границ.
    Все три правила найдены на реальных данных OHM, срез −2400, регион Нила
    и Месопотамии. Примеры оттуда же:

      n2083883034 village Hügelsheim  start_date=-10000, end_date нет
                  → современная немецкая деревня, «жива с 10000 г. до н.э.»
      n2087565384 city    Ἀθῆναι      start_date=-2999,  end_date нет
                  → Афины без даты конца = «существуют сейчас»
      n2101129189 village Nagar       start_date=-6499,  end_date=0750
                  → 8250 лет существования, почти наверняка ошибка датировки
      n2088104579 city    Konya كونيا → два языка в одном поле
    """
    out = []
    is_place = not str(tags.get("boundary", "")).strip()

    if is_place:
        if e is None:
            out.append("нет end_date: по правилам OHM объект считается живым "
                       "до сих пор — проверьте, что это не современный населённый пункт")
        if s is not None and s < -12000:
            out.append(f"start_date={s} — раньше неолита; для поселения это "
                       "почти наверняка заглушка «с начала времён», а не дата")
        if s is not None and e is not None and (e - s) > 4000:
            out.append(f"период {e - s} лет — для города неправдоподобно долго, "
                       "проверьте обе даты")

    nm = str(tags.get("name", "")).strip()
    if mixed_script(nm):
        out.append(f"в name смешаны письменности: «{nm}» — разнесите на name "
                   "и name:<язык>, иначе подпись на карте будет кашей")

    if kind == "culture" and not tags.get("wikipedia") and not tags.get("wikidata"):
        out.append("культура без wikipedia/wikidata — нечем подтвердить ареал")

    # Качество датировки — для всех типов объектов, не только для городов.
    out.extend(date_flags(tags))

    return out


def find_overlaps(records):
    """
    Пересекающиеся годы у объектов одного типа = подозрение на ошибку.
    Проверяем только по датам, без геометрии (геометрию видно в QGIS).
    """
    problems = []
    by_kind = {}
    for rec, geom, line in records:
        if line:
            continue
        by_kind.setdefault(rec["kind"], []).append(rec)
    for kind, items in by_kind.items():
        items.sort(key=lambda r: (r["start"] if isinstance(r["start"], int) else -10**9))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if not isinstance(a["start"], int) or not isinstance(b["start"], int):
                    continue
                a_end = a["end"] if isinstance(a["end"], int) else 10**9
                b_end = b["end"] if isinstance(b["end"], int) else 10**9
                if a["start"] <= b_end and b["start"] <= a_end:
                    problems.append(
                        f"{kind}: «{a['name_ru'] or a['name_en'] or a['id']}» "
                        f"({a['start']}…{a['end']}) и "
                        f"«{b['name_ru'] or b['name_en'] or b['id']}» "
                        f"({b['start']}…{b['end']}) пересекаются по времени")
    return problems


def match_expected(records, expected):
    """
    Сверяет найденное со списком «что должно быть на этой эпохе».
    Список вы заполняете в era.yml — это единственный способ узнать о ПРОПУСКАХ:
    инструмент не может догадаться, чего в данных нет.

    Сравнение нестрогое: ищем по подстрокам в name/name_en/name_local/name:*,
    потому что «Ancient Egypt» в OHM лежит как «Kemet», а «Индская цивилизация» —
    как «Indus Valley Civilisation». Поэтому совпадение показываем вместе с
    тем, что именно нашлось, — чтобы вы могли проверить глазами.
    """
    found, missing = [], []
    for item in expected or []:
        if isinstance(item, dict):
            label = str(item.get("ru") or item.get("name") or "?")
            keys = []
            for v in item.values():
                # ВАЖНО: variants — это СПИСОК. Наивное str(v) превращает его
                # в "['Kulli']" и сопоставление молча не срабатывает: именно так
                # «Культура Кулли» оказалась в пропусках, хотя Kulli culture
                # в данных лежала. Списки разворачиваем, строки берём как есть.
                if isinstance(v, (list, tuple)):
                    keys += [str(x).lower() for x in v if x]
                elif v:
                    keys.append(str(v).lower())
        else:
            label = str(item)
            keys = [label.lower()]
        keys = [k for k in keys if len(k) >= 3]
        hit = None
        for rec, geom, line in records:
            hay = " ".join(str(rec.get(f, "")) for f in
                           ("name_ru", "name_en", "name_local", "wikidata")).lower()
            if any(k in hay for k in keys):
                hit = rec
                break
        if hit:
            found.append((label, hit))
        else:
            missing.append(label)
    return found, missing


# -----------------------------------------------------------------------------
# Pleiades — античные места с датами обитания
# -----------------------------------------------------------------------------

def fetch_pleiades(cache, era_year, window, bbox=None):
    """
    Pleiades: 41 000+ мест древности, у каждого inhabitedSince/inhabitedUntil.
    Лицензия CC BY 3.0 — коммерчески безопасно, но авторство указать ОБЯЗАТЕЛЬНО.

    Файл 136 МБ в gzip, поэтому качается один раз в maps/_cache/ и дальше
    используется локально.
    """
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        log(f"  скачиваю Pleiades → {cache}")
        log(f"    {PLEIADES_JSON}")
        log("    это 136 МБ, один раз; дальше инструмент берёт файл из кэша")
        req = urllib.request.Request(PLEIADES_JSON, headers={"User-Agent": UA})
        tmp = cache + ".part"
        with urllib.request.urlopen(req, timeout=1800) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b); got += len(b)
                if total:
                    print(f"\r    {got/1e6:.0f}/{total/1e6:.0f} МБ "
                          f"({100*got/total:.0f}%)", end="", flush=True)
        print()
        os.replace(tmp, cache)
    else:
        log(f"  Pleiades из кэша: {cache} ({os.path.getsize(cache)/1e6:.0f} МБ)")

    log("  разбираю (это JSON на ~500 МБ в памяти, займёт минуту-две)…")
    opener = gzip.open if cache.endswith(".gz") else open
    data = json.load(io.TextIOWrapper(opener(cache, "rb"), encoding="utf-8"))
    feats = data.get("features", data if isinstance(data, list) else [])
    log(f"    всего мест: {len(feats)}")

    y0, y1 = era_year - window, era_year + window
    out = []
    for f in feats:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if not g.get("coordinates"):
            continue
        since = p.get("inhabitedSince")
        until = p.get("inhabitedUntil")
        try:
            since = int(since) if since is not None else None
            until = int(until) if until is not None else None
        except (TypeError, ValueError):
            since = until = None
        # правило Pleiades: пустое since = «с начала», пустое until = «до сих пор»
        if since is not None and since > y1:
            continue
        if until is not None and until < y0:
            continue
        if bbox:
            c = g["coordinates"]
            pt = c[0] if isinstance(c[0], list) else c
            if not (bbox[0] <= pt[0] <= bbox[2] and bbox[1] <= pt[1] <= bbox[3]):
                continue

        names = p.get("names") or []
        name_local = ""
        for n in names:
            if n.get("languageGroup") or n.get("attestations"):
                name_local = n.get("name_transliterated") or n.get("romanized") or ""
                if name_local:
                    break
        if not name_local and names:
            name_local = names[0].get("romanized") or names[0].get("name_transliterated") or ""

        wd = str(p.get("wikidata") or "").strip()
        if wd.startswith("http"):
            wd = wd.rstrip("/").split("/")[-1]
        gaps = []
        if not wd:
            gaps.append("нет wikidata")
        if since is None and until is None:
            gaps.append("нет дат обитания — попадание в эпоху не подтверждено")
        rec = {k: "" for k in FIELDS}
        rec.update({
            "id": wd or f"pleiades-{p.get('id','')}",
            "wikidata": wd,
            "name_ru": "",
            "name_local": name_local,
            "name_en": p.get("title") or "",
            "kind": "city" if (p.get("featureType") or p.get("featureCategory"))
                    in ("urban", "settlement", "city") else "place",
            "status": "ok" if not gaps else "needs-review",
            "start": since if since is not None else "",
            "end": until if until is not None else "",
            "start_raw": str(since or ""), "end_raw": str(until or ""),
            "color": "#7a6a52",
            "label_lon": round(g["coordinates"][0], 5) if g.get("type") == "Point" else "",
            "label_lat": round(g["coordinates"][1], 5) if g.get("type") == "Point" else "",
            "label_z_min": 5,
            "source": f"Pleiades {p.get('id','')} (CC BY 3.0)",
            "note": (p.get("featureType") or "") + " / " + (p.get("featureCategory") or ""),
            "ohm_url": f"https://pleiades.stoa.org/places/{p.get('id','')}",
            "gap": "; ".join(gaps),
        })
        out.append((rec, g, g.get("type") in ("LineString", "MultiLineString")))
    log(f"    подходит эпохе {y0}…{y1}: {len(out)} мест")
    return out


# -----------------------------------------------------------------------------
# Запись слоёв
# -----------------------------------------------------------------------------

def write_layer(path, items):
    """Служебные поля с «_» наружу не отдаём — они нужны только раскладке по слоям."""
    fc = {"type": "FeatureCollection",
          "features": [{"type": "Feature",
                        "properties": {k: v for k, v in rec.items() if not k.startswith("_")},
                        "geometry": geom}
                       for rec, geom, _ in items]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return os.path.getsize(path)


def write_layers(qdir, records):
    """Раскладывает записи по слоям. Пустые слои тоже создаём — с правильной
    схемой полей, чтобы их можно было сразу наполнять руками в QGIS."""
    buckets = {k: [] for k in LAYERS}
    seen = set()          # один ohm_id — один слой, иначе объект дублируется
    for rec, geom, line in records:
        key = rec.get("ohm_id") or rec.get("id")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kind = rec["kind"]
        gtype = (geom or {}).get("type", "")
        # культуры, народы и кочевники — всегда отдельный слой, даже если это
        # полигон с admin_level=2 (в OHM у культур нет своего тега)
        if kind in ("culture", "civilization", "tribe", "nomads", "confederation"):
            buckets["cultures"].append((rec, geom, line))
        # ТОЧКА не может быть ни границей, ни дорогой, ни рекой: у неё нет
        # ни площади, ни протяжённости. Это правило должно стоять ПЕРЕД
        # проверкой тегов, иначе тег решает судьбу точки.
        # Реальный случай: Londinium (Q927198) пришёл из OHM узлом place=city,
        # но с boundary=administrative. Проверка boundary стояла выше, город
        # попадал в границы, файла геометрии для точки не создавалось — и
        # сборка печатала «Londinium: геометрия не найдена», а валидатор
        # блокировал публикацию. Город отправляется в places, где ему и место.
        elif gtype in ("Point", "MultiPoint"):
            # Дорога, путь или река, у которых вместо линии получилась точка.
            # Такое бывает, когда геометрию не удалось собрать из участников
            # отношения и остался только центроид. Оставлять kind=route нельзя:
            # рисовать нечего, и валидатор справедливо ругается на «route»
            # в точечном файле. Понижаем до подписи и объясняем почему.
            if rec.get("kind") in ("route", "water"):
                rec["note"] = ((rec.get("note") or "") + " | ").strip(" |") + \
                    f"в OHM это {rec.get('kind')}, но геометрия не собралась — " \
                    "остался только центроид, поэтому на карте будет подписью, " \
                    "а не линией. Нарисуйте линию в QGIS вручную"
                rec["kind"] = "label"
                rec["gap"] = ((rec.get("gap") or "") + "; ").strip("; ") + \
                    "нет линейной геометрии: объект показан точкой"
            buckets["places"].append((rec, geom, line))
        # Административная граница, даже если она легла НЕЗАМКНУТОЙ линией.
        # Реальный случай: у Кёльна в OHM шесть путей boundary=administrative
        # «Colonia Claudia Ara Agrippinensium», и все они — разомкнутые линии.
        # По типу геометрии они уезжали в routes, и город оказывался «дорогой»,
        # а в границах его не было вовсе. Тег boundary важнее формы.
        elif rec.get("_boundary") == "administrative":
            buckets["borders"].append((rec, geom, line))
        # Дороги — по kind, а не по типу геометрии.
        # Прежний порядок смотрел на `line` и на теги, из-за чего Via Appia
        # (route=road, kind=route, но замкнутая линия) уезжала в borders,
        # а в routes оказывались современные немецкие дороги N90 и N80.
        elif kind == "route":
            buckets["routes"].append((rec, geom, line))
        # реки и озёра эпохи — тоже по kind, теги как запасной признак
        elif kind == "water" \
                or rec.get("_natural") in ("water", "wetland", "coastline", "bay") \
                or rec.get("_waterway"):
            buckets["hydro"].append((rec, geom, line))
        # точечные объекты: города, памятники, постройки, подписи регионов
        elif gtype == "Point" or rec.get("_place") or rec.get("_historic"):
            buckets["places"].append((rec, geom, line))
        # прочее линейное без явного типа — тоже считаем путём, но помечаем
        elif line:
            buckets["routes"].append((rec, geom, line))
        # всё остальное полигональное и линейное = государства
        else:
            buckets["borders"].append((rec, geom, line))

    sizes = {}
    for name in LAYERS:
        p = os.path.join(qdir, f"{name}.geojson")
        sizes[name] = write_layer(p, buckets[name])
    return buckets, sizes


def geom_key(rec):
    """
    Ключ, под которым объект лежит в geom/. ОДИН И ТОТ ЖЕ ключ используется
    и для имени файла, и для колонки geom в CSV — иначе сборка не находит
    геометрию. Реальный сбой: у «Petit Pont» не было wikidata, колонка geom
    осталась пустой, и build_map.py напечатал «геометрия не найдена», хотя
    файл geom/way_202444560.geojson лежал рядом.
    """
    return (rec.get("wikidata") or "").strip() \
        or (rec.get("ohm_id") or "").replace("/", "_") \
        or ""


def write_geom_files(geomdir, records):
    """
    Личный файл на объект: geom/<wikidata>.geojson — ровно тот формат, который
    ждёт build_map.py. Без этого собранные границы нельзя превратить в тайлы:
    build_map ищет геометрию по имени файла из колонки geom.

    Имя файла — Wikidata ID, если он есть, иначе ohm_id с заменой «/» на «_»
    (relation/2859881 → relation_2859881). Это же значение попадает в колонку
    geom заготовки CSV, так что связка сходится автоматически.
    """
    os.makedirs(geomdir, exist_ok=True)
    written = 0
    hydro = []
    for rec, geom, line in records:
        if not geom or not geom.get("coordinates"):
            continue
        gtype = geom.get("type")
        if gtype == "Point":
            continue                      # точка не может быть границей
        # Реки и озёра эпохи складываем ОТДЕЛЬНО в geom/hydro.geojson.
        # Это не дублирование по рассеянности: build_map.py читает гидрографию
        # именно оттуда (см. блок «2. ГИДРОГРАФИЯ ЭПОХИ» в build_map.py),
        # а файл qgis/hydro.geojson нужен только для разглядывания в QGIS.
        # Пока этого не было, слой hydro собирался, показывался в отчёте,
        # но в тайлы не попадал вообще — ни в одной эпохе.
        if rec.get("kind") == "water" or rec.get("_waterway") \
                or rec.get("_natural") in ("water", "wetland", "coastline", "bay"):
            hydro.append({"type": "Feature",
                          "properties": {k: v for k, v in rec.items()
                                         if not k.startswith("_")},
                          "geometry": geom})
        key = geom_key(rec)
        if not key:
            continue
        props = {k: v for k, v in rec.items() if not k.startswith("_")}
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": props, "geometry": geom}]}
        path = os.path.join(geomdir, f"{key}.geojson")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
        written += 1
    hydro = add_base_hydro(hydro, geomdir)
    if hydro:
        with open(os.path.join(geomdir, "hydro.geojson"), "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": hydro},
                      f, ensure_ascii=False, separators=(",", ":"))
    return written


# Какой масштаб Natural Earth брать по зуму эпохи. 110m — это 13 крупнейших
# рек мира: Тигра, Евфрата, Нила как отдельного объекта там НЕТ. Поэтому для
# исторической карты нужен 50m (477 рек), а 110m годится только для зумов 0–3.
BASE_HYDRO_FILES = ("rivers-50m.geojson", "lakes-50m.geojson")
BASE_HYDRO_SRC = "Natural Earth 1:50 млн (Public Domain)"


def add_base_hydro(hydro, geomdir, limit=600):
    """
    Добавляет к найденному в OHM базовую гидрографию из Natural Earth.

    Зачем это нужно. Замерено 22.10.2026 на живом OHM:
        waterway=river, путей всего             579 250
        из них со start_date                     10 297   (1,8%)
        именованных и активных в 117 г. н. э.       140
        именованных и активных в −2400 г.             5 (весь Ближний Восток)
    То есть датированной гидрографии в OHM практически нет, а Тигр, Евфрат,
    Нил, Инд и Ганг не датированы вовсе. Без Natural Earth на карте эпохи
    не было бы НИ ОДНОЙ великой реки древности — только римские акведуки,
    которые OHM как раз датировал (Aqua Appia −311…500, Aqua Virgo −18…500,
    Cloaca Maxima −600…500, Aqua Claudia 52…500).

    Natural Earth — общественное достояние, поэтому для платного продукта
    безопасен без ограничений.
    """
    # Путь к maps/base считаем ОТ ЭТОГО ФАЙЛА, а не от geomdir.
    # Прежний вариант делал dirname() дважды от …/maps/eras/<id>/geom,
    # получал …/maps/eras и затем склеивал «../maps/base» — выходило
    # …/maps/maps/base, которого не существует. Работало только потому,
    # что ниже был запасной вариант; на чистой машине без него слой рек
    # молча оставался пустым.
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    base = os.path.normpath(os.path.join(tools_dir, "..", "maps", "base"))
    if not os.path.isdir(base):
        base = os.path.normpath(os.path.join(os.path.abspath(geomdir),
                                             "..", "..", "..", "base"))
    have = {f["properties"].get("wikidata") for f in hydro
            if f["properties"].get("wikidata")}
    have |= {str(f["properties"].get("name_en") or "").strip().lower() for f in hydro}
    added = 0
    for fn in BASE_HYDRO_FILES:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for f in d.get("features", []):
            if added >= limit:
                break
            g = f.get("geometry")
            if not g or not g.get("coordinates"):
                continue
            pr = f.get("properties") or {}
            nm = str(pr.get("name_en") or "").strip()
            wd = str(pr.get("wikidata") or "").strip()
            # не дублировать то, что OHM уже дал с датами
            if (wd and wd in have) or (nm and nm.lower() in have):
                continue
            hydro.append({
                "type": "Feature",
                "properties": {
                    "wikidata": wd,
                    "name_ru": str(pr.get("name_ru") or ""),
                    "name_local": nm,
                    "name_en": nm,
                    "kind": "water",
                    "status": "base",
                    "start": "", "end": "",
                    "color": "#7fa8c9",
                    "label_z_min": pr.get("label_z_min") or 4,
                    "z_min": pr.get("z_min") or 2,
                    "source": BASE_HYDRO_SRC,
                    "note": ("Базовая гидрография Natural Earth, без датировки: "
                             "в OHM эта река не датирована. Русла за тысячи лет "
                             "меняются мало, но если для вашей эпохи это важно — "
                             "проверьте по источнику."),
                },
                "geometry": g,
            })
            added += 1
    return hydro


# -----------------------------------------------------------------------------
# Отчёт «чего не хватает»
# -----------------------------------------------------------------------------

def write_report(path, era, year, window, buckets, sizes, overlaps,
                 expected_found, expected_missing, source_note, planet_info,
                 dupes=None, chronologies=None, dropped_modern=None):
    total = sum(len(v) for v in buckets.values())
    need = []
    for name, items in buckets.items():
        for rec, geom, line in items:
            if rec["gap"]:
                need.append((name, rec))

    L = []
    A = L.append
    A(f"# Отчёт по срезу эпохи: {era.get('name_ru') or era.get('id')}")
    A("")
    A(f"**Точка эпохи:** {year} г.  ·  **окно среза:** {year - window}…{year + window}  ·  "
      f"**собрано:** {total} объектов")
    A(f"**Источник:** {source_note}")
    if planet_info:
        A(f"**Дамп:** {planet_info}")
    A("")
    A("Файл создан `tools/extract_era.py`. Это не список ошибок, а список мест,")
    A("где нужно ваше решение: автоматика нашла данные и честно пометила, что")
    A("в них сомнительно. Проверять стоит именно помеченное — остальное можно")
    A("брать как есть.")
    A("")

    A("## Что получилось по слоям")
    A("")
    A("| Слой | Объектов | Вес | Что это |")
    A("|---|---|---|---|")
    desc = {
        "borders": "государства: границы, заполнение, подписи",
        "cultures": "археологические культуры, народы, кочевники — ареалы",
        "places": "города и поселения эпохи",
        "routes": "дороги и торговые пути (линии)",
        "migrations": "миграции и переселения — заполняется вручную",
        "hydro": "реки и озёра эпохи — заполняется вручную",
    }
    for name in LAYERS:
        n = len(buckets.get(name, []))
        mark = "✓" if n else "—"
        A(f"| `{name}.geojson` | {mark} {n} | {sizes.get(name,0)/1024:.0f} КБ | {desc[name]} |")
    A("")

    if not buckets.get("routes"):
        A("> **`routes` пуст.** Но это НЕ значит, что в OHM нет дорог вовсе: я так")
        A("> сначала и написал — и это было неправдой, потому что переписывал только")
        A("> `boundary=*`, а дороги лежат в `route=*`. Замерено 22.10.2026:")
        A("> `route=*` в OHM — **12 569 отношений**, из них **12 090 со `start_date`**.")
        A("> Перепись по значениям: road 8162 · tram 1466 · railway 1130 · bus 622 ·")
        A("> train 415 · subway 265 · trolleybus 158 · light_rail 141 · ferry 83 ·")
        A("> tracks 66 · hiking 8 · river 5 · bicycle 3 · foot 2.")
        A("> Исторических значений `roman_road`, `trade_route`, `silk_road`,")
        A("> `amber_road` — **по нулям**. Дороги есть, но без исторической разметки:")
        A("> Via Appia лежит просто как `route=road`.")
        A("> Датированных `route=road` старше 1500 г. на весь мир — **88**. Среди них")
        A("> настоящие: Via Appia (Q189417, −311…476), Via Cassia (Q849300, −49),")
        A("> Alter Hellweg (−899), Portway (97), Camino Real de Burgos a Laredo (1450).")
        A("> Всё остальное — Шёлковый путь, янтарный путь, караванные маршруты — вручную.")
        A("")
    if not buckets.get("hydro"):
        A("> **`hydro` пуст или почти пуст — и это ожидаемо.** Замерено 22.10.2026:")
        A("> в OHM `waterway=river` — **579 250 путей**, но со `start_date` только")
        A("> **10 297** (1,8%). Именованных и активных в −2400 во всём Ближнем")
        A("> Востоке — **5**, во всей Римской империи 117 г. — **2**.")
        A("> Датированных именованных рек, активных в 117 г., на весь мир — **140**.")
        A("> Поэтому геометрию рек берём из **Natural Earth (Public Domain)**:")
        A("> `tools/prep_base.py` даёт 477 рек на масштабе 1:50 млн, у каждой есть")
        A("> `name_ru` и `wikidataid`: Тигр Q35591, Евфрат Q34589, Нил Q3392,")
        A("> Инд Q7348, Ганг Q5089, Иордан Q40059, Амударья Q8493, Хуанхэ Q7355.")
        A("> Слой `hydro` здесь — для РЕДКИХ случаев, когда река действительно")
        A("> изменилась: пересохшее русло, другое течение, исчезнувшее озеро.")
        A("> Дыры Natural Earth 50m, которые придётся дорисовать: **нет Тибра и")
        A("> Оронта**, а Сырдарья записана урезанно как «Syr Dar».")
        A("")
    # ---- что инструмент ОТБРОСИЛ сам, и почему -------------------------
    # Без этого раздела вы видите только итоговые цифры и не можете проверить,
    # не выбросил ли инструмент что-то нужное. Прозрачность важнее красоты.
    dropped_modern = dropped_modern or []
    chronologies = chronologies or []
    dupes = dupes or []
    if dropped_modern or chronologies or dupes:
        A("---")
        A("")
        A("## Что отброшено автоматически")
        A("")
        A("Инструмент убирает часть найденного сам. Здесь полный список, чтобы")
        A("вы могли проверить, не выброшено ли что-то нужное.")
        A("")
    if dropped_modern:
        A(f"### Возникли ПОСЛЕ конца эпохи — {len(dropped_modern)} шт.")
        A("")
        A(f"Опорный год {year}, окно до {year + window}. Объект, появившийся позже,")
        A("на карте этой эпохи появиться не может, даже если формально «активен».")
        A("Типичный случай — современная дорога с `start_date=0`: она проходит")
        A("фильтр «активна в 117 году», но это шоссе XX века.")
        A("")
        for m in dropped_modern[:40]:
            A(f"- {m}")
        if len(dropped_modern) > 40:
            A(f"- …и ещё {len(dropped_modern) - 40}")
        A("")
    if chronologies:
        A(f"### Несколько стадий одного объекта (хронология OHM) — {len(chronologies)} шт.")
        A("")
        A("В OHM у объекта бывает по несколько геометрий — по одной на стадию")
        A("существования. Это НЕ дубли: даты разные. Но на карте они нарисуются")
        A("наложенными друг на друга полигонами одного цвета, поэтому для снимка")
        A("эпохи выбрана одна стадия — та, что точнее описывает опорный год.")
        A("")
        A("Реальный пример, найденный при отладке: у Кёльна шесть путей")
        A("`Colonia Claudia Ara Agrippinensium` с датами конца 947, 1106, 1106,")
        A("1179, 1180 — и ни одного `wikidata`. Без группировки все шесть")
        A("попали бы на карту.")
        A("")
        for m in chronologies[:40]:
            A(f"- {m}")
        if len(chronologies) > 40:
            A(f"- …и ещё {len(chronologies) - 40}")
        A("")
    if dupes:
        A(f"### Полные дубли и расхождения дат — {len(dupes)} шт.")
        A("")
        for m in dupes[:40]:
            A(f"- {m}")
        if len(dupes) > 40:
            A(f"- …и ещё {len(dupes) - 40}")
        A("")

    if not buckets.get("migrations"):
        A("> **`migrations` всегда пуст.** Таких данных нет ни в одном открытом")
        A("> источнике: переселение народов — это интерпретация историка, а не")
        A("> записанный факт. Слой создан, чтобы вы рисовали коридоры и стрелки")
        A("> с периодом вручную.")
        A("")

    A("## Чего не хватает: по объектам")
    A("")
    if not need:
        A("Все найденные объекты полны. Так почти никогда не бывает — проверьте,")
        A("что срез действительно зацепил нужную эпоху.")
    else:
        A(f"Помечено {len(need)} из {total}. Сгруппировано по слою.")
        A("")
        cur = None
        for name, rec in sorted(need, key=lambda x: (x[0], str(x[1]["name_ru"]))):
            if name != cur:
                A(f"### {name}")
                A("")
                cur = name
            title = rec["name_ru"] or rec["name_en"] or rec["name_local"] or rec["id"]
            years = f"{rec['start']}…{rec['end']}"
            A(f"- **{title}** ({years}, `{rec['kind']}`)")
            for g in rec["gap"].split("; "):
                if g:
                    A(f"    - {g}")
            if rec["ohm_url"]:
                A(f"    - смотреть в OHM: {rec['ohm_url']}")
        A("")

    A("## Пересечения по времени")
    A("")
    if overlaps:
        A("Два объекта одного типа, жившие одновременно. Иногда это законно")
        A("(соседи), иногда — ошибка датировки или дубль в данных.")
        A("")
        for o in overlaps[:60]:
            A(f"- {o}")
        if len(overlaps) > 60:
            A(f"- …и ещё {len(overlaps) - 60}")
    else:
        A("Не найдено.")
    A("")

    A("## Кого нет из ожидаемого")
    A("")
    if not expected_found and not expected_missing:
        A("Список `expected` в `era.yml` пуст. Заполните его — иначе инструмент")
        A("не сможет сказать, что вы ПРОПУСТИЛИ: он проверяет только то, что нашёл.")
        A("Это единственная часть отчёта, которую нельзя автоматизировать полностью.")
    else:
        A(f"**Найдено: {len(expected_found)}**")
        A("")
        for label, rec in expected_found:
            title = rec["name_ru"] or rec["name_en"] or rec["name_local"] or rec["id"]
            A(f"- ✓ {label} → в данных как «{title}» ({rec['start']}…{rec['end']}, "
              f"`{rec['kind']}`)")
        A("")
        A(f"**НЕ найдено: {len(expected_missing)}** — вот это и есть настоящая дыра,")
        A("её придётся закрывать ручной отрисовкой по атласу.")
        A("")
        for m in expected_missing:
            A(f"- ✗ {m}")
    A("")

    A("## Как дополнить — по типам дыр")
    A("")
    A("| Что не так | Чем закрывать | Как |")
    A("|---|---|---|")
    A("| объекта нет вовсе | PD-скан атласа | привязать в QGIS (§V) и обвести (§VI) |")
    A("| нет `wikidata` | `tools/wd_lookup.py \"название\"` | вписать Q-номер в CSV |")
    A("| нет `name:ru` | Википедия/Wikidata | вписать в CSV, не правя OHM |")
    A("| `fixme:s` (нет источника границы) | атлас или статья | указать в поле `source` |")
    A("| дата с `~` (EDTF) | сверить с атласом | округлить до года в CSV |")
    A("| тип определён по названию | решение глазами | поправить `kind` в CSV |")
    A("| пересечение по времени | решить, кто был раньше | поправить `start`/`end` |")
    A("| нет торговых путей | PD-атлас | рисовать в слое `routes` |")
    A("| нет миграций | научный атлас | рисовать в слое `migrations` |")
    A("")
    A("**Важно про культуры и народы.** В OHM для них нет отдельного тега:")
    A("`Bell Beaker culture`, `Arzachena culture`, `Kulli culture` лежат как")
    A("`boundary=administrative` + `admin_level=2` — ровно так же, как `Elam` или")
    A("`Kemet` (Древнее царство Египта). По тегам государство от культуры неотличимо.")
    A("Инструмент определяет тип по словам в названии и по `border_type=*`, и")
    A("**помечает каждую такую догадку в отчёте** — именно эти строки и надо")
    A("проверить глазами в QGIS в первую очередь.")
    A("")
    A("Отсюда два следствия для сайта:")
    A("")
    A("1. Культуре нельзя давать ссылку на статью о государстве и наоборот.")
    A("2. Культуру нельзя рисовать как государство: у неё нет жёсткой границы,")
    A("   только ареал. На карте это полупрозрачная штриховка без контура.")
    A("")

    open(path, "w", encoding="utf-8").write("\n".join(L))
    return len(need), total



# Схемы колонок — РОЗНО для каждого файла, потому что build_map.py читает их
# по-разному. Это не косметика: если в places.csv написать label_lon вместо lon,
# валидатор выдаст 80 ошибок «пусто обязательное поле lon», а карта соберётся
# без единого города. Сверено с maps/eras/_template/*.csv.
CSV_COLUMNS = {
    # полигоны: есть geom (имя файла в geom/), color, метка как label_*
    "polities": ["wikidata", "name_ru", "name_local", "start", "end", "color",
                 "kind", "geom", "label_lon", "label_lat", "label_z_min",
                 "article", "source", "note"],
    # точки: координаты как lon/lat, зум как z_min, geom и color не нужны
    "places":   ["wikidata", "name_ru", "name_local", "kind", "lon", "lat",
                 "z_min", "start", "end", "article", "source", "note"],
    # культуры и народы: полигоны, схема как у polities
    "cultures": ["wikidata", "name_ru", "name_local", "start", "end", "color",
                 "kind", "geom", "label_lon", "label_lat", "label_z_min",
                 "article", "source", "note"],
    # линии: как полигоны
    "routes":   ["wikidata", "name_ru", "name_local", "start", "end", "color",
                 "kind", "geom", "label_lon", "label_lat", "label_z_min",
                 "article", "source", "note"],
}

# как внутренние имена записи ложатся в колонки мест (lon/lat/z_min)
PLACE_RENAME = {"label_lon": "lon", "label_lat": "lat", "label_z_min": "z_min"}


def write_csv_draft(path, records, what="polities", comment=""):
    """
    Заготовка CSV: уже заполнена тем, что нашлось в OHM.
    Остаётся проверить kind, вписать name_ru где пусто и добавить article.

    Колонки ровно те, что ждёт build_map.py, поэтому файл можно переименовать
    в polities.csv / places.csv и сразу собирать карту.

    Разделение по файлам обязательно: build_map.py читает polities.csv как
    ГОСУДАРСТВА, places.csv как точки, events.csv как события. Если свалить
    всё в один файл, пирамида Хеопса окажется государством.
    """
    cols = CSV_COLUMNS.get(what, CSV_COLUMNS["polities"])
    rename = PLACE_RENAME if what == "places" else {}
    rows = []
    for rec, geom, line in records:
        src = {rename.get(k, k): v for k, v in rec.items()}
        r = {c: src.get(c, "") for c in cols}
        if "geom" in cols:
            # geom = имя файла в geom/; write_geom_files кладёт их под этим же ключом
            r["geom"] = geom_key(rec)
        note = rec.get("note", "")
        gap = rec.get("gap", "")
        if gap:
            note = (note + " | ПРОВЕРИТЬ: " + gap) if note else "ПРОВЕРИТЬ: " + gap
        r["note"] = note[:600]
        rows.append(r)
    # ВАЖНО: никаких «#»-комментариев в начале файла. Excel, LibreOffice, QGIS
    # и pandas считают ПЕРВУЮ строку заголовком, и комментарий превращается
    # в заголовок из одной колонки — файл выглядит сломанным. Пояснение уходит
    # в gaps.md, а не в CSV.
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_open_script(path, qdir, layers):
    """Скрипт, открывающий все слои в QGIS одной командой."""
    files = " ".join(f'"{os.path.join(qdir, l + ".geojson")}"'
                     for l in layers if os.path.exists(os.path.join(qdir, l + ".geojson")))
    path_abs = os.path.abspath(path)
    with open(path_abs, "w", encoding="utf-8") as f:
        f.write(f"""#!/usr/bin/env bash
# Открывает все слои эпохи в QGIS одной командой.
# Слои перечислены в порядке снизу вверх: сначала подложка, потом границы.
set -e
cd "{qdir}"
qgis {files} &
echo "QGIS запускается. Слои загрузятся в перечисленном порядке."
echo "Если QGIS уже открыт — слои добавятся в существующее окно."
""")
    os.chmod(path_abs, 0o755)
    return path_abs


# -----------------------------------------------------------------------------
# doctor: проверка окружения Ubuntu
# -----------------------------------------------------------------------------

def find_all_jdk():
    """
    Ищет ВСЕ установленные JDK, а не только первую `java` в PATH.
    Возвращает [(путь_к_java, старшая_версия), …].

    Зачем: на Ubuntu 26.04 `openjdk-lts` — это Java 11, и она легко оказывается
    в PATH раньше установленной рядом Java 21. Проверка только `java -version`
    в этом случае врёт, что Java не годится. Я сам на это наступил: Temurin 21
    скачан, а `java -version` всё равно печатает «openjdk version 11».
    """
    cands = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        cands.append(os.path.join(jh, "bin", "java"))
    w = shutil.which("java")
    if w:
        cands.append(w)
    for pat in ("/usr/lib/jvm/*/bin/java",
                os.path.expanduser("~/jdk21/bin/java"),
                os.path.expanduser("~/jdk*/bin/java"),
                "/opt/java/*/bin/java"):
        cands.extend(sorted(glob.glob(pat)))
    out, seen = [], set()
    for c in cands:
        try:
            real = os.path.realpath(c)
        except OSError:
            continue
        if real in seen or not os.path.exists(c):
            continue
        seen.add(real)
        try:
            v = subprocess.run([c, "-version"], capture_output=True, text=True,
                               timeout=30)
            txt = (v.stderr or "") + (v.stdout or "")
            m = re.search(r'version "(\d+)', txt)
            if m:
                out.append((c, int(m.group(1))))
        except Exception:
            pass
    return out


def doctor():
    log("Проверка окружения")
    log("=" * 62)
    checks = []

    def chk(name, ok, detail, fix=""):
        checks.append(ok)
        log(f"  {'✓' if ok else '✗'} {name:34s} {detail}")
        if not ok and fix:
            log(f"      как починить: {fix}")

    # osmium
    if have("osmium"):
        v = subprocess.run(["osmium", "--version"], capture_output=True, text=True).stdout
        chk("osmium-tool", True, v.splitlines()[0][:40] if v else "есть")
    else:
        chk("osmium-tool", False, "НЕ УСТАНОВЛЕН", "sudo apt install osmium-tool")

    # java 21+
    # Проверяем НЕ только `java` из PATH, а все найденные JDK. Причина: на
    # Ubuntu 26.04 можно одновременно иметь openjdk-lts (это Java 11!) и
    # openjdk-21, и если в PATH первым стоит 11-я, наивная проверка скажет
    # «не годится», хотя 21-я установлена иPlanetiler на ней работает.
    # Я сам на это наступил: скачал Temurin 21, а `java -version` всё равно
    # печатал «openjdk version 11».
    jdks = find_all_jdk()
    if jdks:
        best = max(jdks, key=lambda x: x[1])
        chk("java (нужен 21+)", best[1] >= 21, f"будет взята Java {best[1]}: {best[0]}")
        if len(jdks) > 1:
            log("    найдено несколько JDK: " + ", ".join(f"{v} ({os.path.dirname(os.path.dirname(p))})"
                                                          for p, v in sorted(jdks, key=lambda x: -x[1])))
        if best[1] < 21:
            log("    как починить: sudo apt install openjdk-21-jdk")
    else:
        chk("java (нужен 21+)", False, "НЕТ ни одной Java",
            "sudo apt install openjdk-21-jdk")

    # qgis
    if have("qgis"):
        chk("qgis", True, "команда найдена")
    else:
        chk("qgis", False, "команда не найдена",
            "см. §II.5 инструкции: репозиторий Ubuntu даёт 3.40, qgis.org — 3.44 LTR")

    # python-модули
    try:
        import yaml
        chk("python3-yaml", True, "импортируется")
    except ImportError:
        chk("python3-yaml", False, "нет (инструмент обойдётся запасным парсером)",
            "sudo apt install python3-yaml")

    # сеть до OHM
    try:
        url = planet_url_latest()
        chk("доступ к дампу OHM", True, url.split("/")[-1])
    except Exception as e:
        chk("доступ к дампу OHM", False, str(e)[:40], "проверьте сеть/прокси")
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            OHM_OVERPASS + "status", headers={"User-Agent": UA}), timeout=20)
        txt = r.read().decode()[:200]
        rl = re.search(r"Rate limit: (\d+)", txt)
        chk("OHM Overpass", True, f"отвечает, лимит {rl.group(1) if rl else '?'} запроса")
    except Exception as e:
        chk("OHM Overpass", False, str(e)[:40])

    log("=" * 62)
    if all(checks):
        log("  окружение готово")
        return 0
    log(f"  не готово: {checks.count(False)} пункт(ов)")
    return 1


# -----------------------------------------------------------------------------
# Команды
# -----------------------------------------------------------------------------

def era_paths(era_id):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "maps", "eras", era_id)
    return root, d, os.path.join(d, "era.yml"), os.path.join(d, "qgis")


def resolve_planet(era, root):
    """Где искать дамп OHM: era.yml → переменная окружения → ~/ohm/planet.osm.pbf"""
    cands = []
    if era.get("ohm_planet"):
        cands.append(str(era["ohm_planet"]))
    if os.environ.get("OHM_PLANET"):
        cands.append(os.environ["OHM_PLANET"])
    cands += [os.path.expanduser("~/ohm/planet.osm.pbf"),
              os.path.expanduser("~/ohm/planet-latest.osm.pbf"),
              os.path.join(root, "planet.osm.pbf")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return cands[0] if cands else None


def cmd_ohm(era_id, overpass=False, window=None, force=False, bbox=None):
    root, d, yml, qdir = era_paths(era_id)
    era = load_yaml(yml)
    if not era:
        die(f"не найден или пуст {yml}\n"
            f"  Скопируйте шаблон:  cp -r maps/eras/_template maps/eras/{era_id}\n"
            f"  и заполните year, valid_from, valid_to.")
    year = era.get("year")
    if year is None:
        die(f"в {yml} не задан year — без него срез невозможен")
    year = int(year)

    # -----------------------------------------------------------------
    # ПАРАМЕТРЫ ИЗ era.yml, а не только из командной строки.
    # Без этого era.yml выглядел заполненным, но рамка молча
    # игнорировалась и вместо 43 государств империи приходило 75
    # со всего мира — включая те, что к Риму отношения не имеют.
    # Явный ключ в командной строке всегда важнее файла.
    # -----------------------------------------------------------------
    if bbox is None and era.get("bbox"):
        try:
            b = [float(x) for x in list(era["bbox"])]
            if len(b) == 4:
                bbox = tuple(b)
                log(f"  рамка из era.yml: {bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]} "
                    f"(запад, юг, восток, север)")
        except (TypeError, ValueError):
            log(f"  ! bbox в era.yml не читается как четыре числа — игнорирую")

    if window is None:
        vf, vt = era.get("valid_from"), era.get("valid_to")
        if vf is not None and vt is not None:
            # окно не уже половины заявленного диапазона эпохи, но не меньше 25 лет
            window = max(25, (int(vt) - int(vf)) // 2)
        else:
            window = 25
        log(f"  окно ±{window} лет — из era.yml (valid_from/valid_to) или по умолчанию")
    elif era.get("valid_from") is not None and era.get("valid_to") is not None:
        window = max(window, (int(era["valid_to"]) - int(era["valid_from"])) // 2)

    os.makedirs(qdir, exist_ok=True)
    scope = str(era.get("scope") or "world").strip().lower()
    log(f"Срез эпохи «{era.get('name_ru') or era_id}»")
    log(f"  год: {year}   окно: {year - window}…{year + window}")
    if bbox:
        log(f"  охват: рамка {bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]} "
            f"(запад, юг, восток, север)")
    else:
        log("  охват: ВЕСЬ МИР — bbox в era.yml не задана")
        if scope not in ("world", ""):
            log(f"  ! в era.yml scope: {scope}, но рамки нет. Для регионального "
                f"среза рамка нужна, иначе придут объекты со всей Земли. "
                f"Для мировой карты так и задумано — тогда поставьте scope: world.")

    if overpass:
        feats = fetch_from_overpass(year, bbox)
        src = f"OHM Overpass API, запрос {time.strftime('%Y-%m-%d %H:%M')}"
        pinfo = ""
    else:
        planet = resolve_planet(era, root)
        work = os.path.join(qdir, "_work")
        if force and os.path.isdir(work):
            shutil.rmtree(work)
        feats = fetch_from_planet(planet, work)
        pinfo = f"{planet} ({os.path.getsize(planet)/1e9:.2f} ГБ)" if planet and os.path.exists(planet) else str(planet)
        src = f"планетарный дамп OHM (CC0), один проход osmium"

    log(f"  сырых объектов: {len(feats)}")
    if not feats:
        die("пусто. Проверьте год в era.yml и путь к дампу. Для пробы: --overpass")

    # Рамку применяем САМИ, по геометрии. Причина в fetch_from_overpass:
    # bbox Overpass для отношений молча теряет 8 объектов из 10.
    if bbox:
        before = len(feats)
        feats = [f for f in feats if in_bbox(f.get("geometry"), bbox)]
        log(f"  в рамке {bbox}: {len(feats)} (отсеяно {before - len(feats)})")

    records = build_records(feats, year, window)
    log(f"  подходит эпохе: {len(records)}")

    buckets, sizes = write_layers(qdir, records)
    n_geom = write_geom_files(os.path.join(d, "geom"), records)
    overlaps = find_overlaps(records)
    dupes = getattr(build_records, "last_dupes", [])
    dropped_modern = getattr(build_records, "last_dropped_modern", [])
    chronologies = getattr(build_records, "last_chronologies", [])
    found, missing = match_expected(records, era.get("expected"))

    # Заготовки CSV — по файлу на слой: build_map.py читает polities как
    # государства, places как точки. Свали всё в один файл — и пирамида
    # Хеопса окажется государством.
    n_pol = write_csv_draft(
        os.path.join(d, "polities.auto.csv"), buckets["borders"], "polities",
        "ГОСУДАРСТВА эпохи. Проверьте kind и впишите article.")
    n_cul = write_csv_draft(
        os.path.join(d, "cultures.auto.csv"), buckets["cultures"], "cultures",
        "АРХЕОЛОГИЧЕСКИЕ КУЛЬТУРЫ И НАРОДЫ. Это НЕ государства: жёсткой границы "
        "нет, только ареал. На карте — полупрозрачная штриховка.")
    n_pl = write_csv_draft(
        os.path.join(d, "places.auto.csv"), buckets["places"], "places",
        "ГОРОДА, ПОСЕЛЕНИЯ, ПАМЯТНИКИ. kind = city / settlement / monument / place.")
    n_rt = write_csv_draft(
        os.path.join(d, "routes.auto.csv"), buckets["routes"], "routes",
        "ДОРОГИ И ТОРГОВЫЕ ПУТИ. В OHM их почти нет — наполнять вручную по атласам.")

    script = write_open_script(os.path.join(qdir, "открыть_в_qgis.sh"), qdir, LAYERS)

    n_need, total = write_report(
        os.path.join(qdir, "gaps.md"), era, year, window, buckets, sizes,
        overlaps, found, missing, src, pinfo,
        dupes=dupes, chronologies=chronologies, dropped_modern=dropped_modern)

    log("")
    log("Готово")
    log("=" * 62)
    for name in LAYERS:
        n = len(buckets.get(name, []))
        bar = "·" * min(n, 40)
        log(f"  {name:12s} {n:5d}  {bar}")
    log("=" * 62)
    log(f"  слои:            {qdir}/")
    log(f"  отчёт:           {os.path.join(qdir, 'gaps.md')}")
    log(f"  геометрия:       {os.path.join(d, 'geom')}/ ({n_geom} файлов — их читает build_map.py)")
    log(f"  заготовки CSV — по слою, колонки как ждёт build_map.py:")
    log(f"      polities.auto.csv  {n_pol:4d}  государства")
    log(f"      cultures.auto.csv  {n_cul:4d}  культуры и народы")
    log(f"      places.auto.csv    {n_pl:4d}  города, поселения, памятники")
    log(f"      routes.auto.csv    {n_rt:4d}  дороги и торговые пути")
    log(f"  открыть в QGIS:  {script}")
    log("")
    log(f"  объектов с пометкой «проверить»: {n_need} из {total}")
    if missing:
        log(f"  НЕ найдено из ожидаемого: {len(missing)} — см. отчёт")
    log("")
    log("Дальше:")
    log(f"  1. {script}")
    log(f"  2. прочитать {os.path.join(qdir, 'gaps.md')}")
    log("  3. поправить kind/даты/имена прямо в QGIS или в CSV")
    log(f"  4. python3 tools/build_map.py era {era_id}")
    return 0


def cmd_pleiades(era_id, window=100, bbox=None):
    root, d, yml, qdir = era_paths(era_id)
    era = load_yaml(yml)
    if not era:
        die(f"не найден {yml}")
    year = int(era["year"])
    os.makedirs(qdir, exist_ok=True)
    cache = os.path.join(root, "maps", "_cache", "pleiades-places-latest.json.gz")
    log(f"Pleiades для эпохи {year} (окно ±{window} лет — для древности берём шире)")
    recs = fetch_pleiades(cache, year, window, bbox)
    p = os.path.join(qdir, "pleiades.geojson")
    size = write_layer(p, recs)
    log(f"  записано {len(recs)} мест → {p} ({size/1024:.0f} КБ)")
    log("  лицензия CC BY 3.0: на сайте ОБЯЗАТЕЛЬНО указать авторство Pleiades")
    return 0


def cmd_open(era_id):
    root, d, yml, qdir = era_paths(era_id)
    s = os.path.join(qdir, "открыть_в_qgis.sh")
    if not os.path.exists(s):
        die(f"нет {s} — сначала выполните: python3 tools/extract_era.py ohm {era_id}")
    os.execv("/bin/bash", ["/bin/bash", s])


def usage():
    log(textwrap.dedent("""
    extract_era.py — срез эпохи из всех источников разом

    Использование:
      python3 tools/extract_era.py doctor
          проверить окружение (osmium, java, qgis, доступ к OHM)

      python3 tools/extract_era.py ohm <эпоха> [--overpass] [--window N]
                                     [--bbox З,Ю,В,С] [--force]
          главный срез: государства, культуры, народы, города, пути

      python3 tools/extract_era.py pleiades <эпоха> [--window N] [--bbox З,Ю,В,С]
          античные места с датами обитания (CC BY 3.0)

      python3 tools/extract_era.py all <эпоха>
          ohm + pleiades

      python3 tools/extract_era.py open <эпоха>
          открыть готовые слои в QGIS

    Ключи:
      --overpass   брать данные из OHM Overpass API, а не из дампа.
                   Не нужен файл на 1,3 ГБ, но лимит 2 запроса одновременно.
      --window N   запас по годам вокруг точки эпохи (по умолчанию 25).
                   Для древности ставьте больше: границы менялись медленно.
      --bbox       ограничить регион: запад,юг,восток,север.
                   Обязателен для --overpass на больших эпохах.
      --force      пересчитать промежуточный PBF заново

    Где искать дамп OHM (по порядку):
      1. поле ohm_planet в era.yml
      2. переменная окружения OHM_PLANET
      3. ~/ohm/planet.osm.pbf
    """).strip())


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        usage()
        return 0
    cmd = a[0]
    if cmd == "doctor":
        return doctor()

    rest = a[1:]
    if not rest:
        usage()
        return 1
    era_id = rest[0]
    flags = rest[1:]

    def val(name, default=None):
        if name in flags:
            i = flags.index(name)
            if i + 1 < len(flags):
                return flags[i + 1]
        return default

    bbox = None
    if val("--bbox"):
        try:
            p = [float(x) for x in val("--bbox").split(",")]
            if len(p) != 4:
                raise ValueError
            bbox = tuple(p)
        except ValueError:
            die("--bbox нужен в виде запад,юг,восток,север (через запятую)")

    window = int(val("--window")) if val("--window") else None
    overpass = "--overpass" in flags
    force = "--force" in flags

    if cmd == "ohm":
        return cmd_ohm(era_id, overpass=overpass, window=window, force=force, bbox=bbox)
    if cmd == "pleiades":
        return cmd_pleiades(era_id, window=int(val("--window", 100)), bbox=bbox)
    if cmd == "all":
        cmd_ohm(era_id, overpass=overpass, window=window, force=force, bbox=bbox)
        return cmd_pleiades(era_id, window=int(val("--window", 100)), bbox=bbox)
    if cmd == "open":
        return cmd_open(era_id)
    die(f"неизвестная команда «{cmd}»")


if __name__ == "__main__":
    sys.exit(main())
