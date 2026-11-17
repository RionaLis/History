#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harvest_wikidata.py — слои, которых НЕТ в OpenHistoricalMap.

Зачем этот файл существует
--------------------------
OHM хорош для границ, культур и поселений, но трёх нужных вам слоёв в нём
просто нет. Замерено 22.10.2026:

  * морские сражения — в OHM нет класса «морская битва» вообще;
  * эпидемии — нет ни одного объекта;
  * исторические названия водоёмов — из 210 именованных водоёмов с датой
    в OHM только У ОДНОГО есть name:ru и У ОДНОГО old_name/alt_name.
    Исторических названий там нет. Зато есть другая беда: 120 из 210
    (57%) помечены `start_date:fixme = arbitrary`, то есть дата проставлена
    произвольно, лишь бы объект попадал в срезы.

Wikidata закрывает первые два слоя почти полностью. Замер того же дня:
по классам «эпидемия», «пандемия» и «морское сражение» SPARQL отдаёт
400 объектов (лимит выборки), из них **263 с координатами** и **377 с датой
начала**. В выборке есть битва при Саламине (Q178850, 23.5667 37.9514,
−479-09-2x), Чёрная смерть (Q42005) и Юстинианова чума (Q821711).

Третий слой — названия водоёмов — автоматизируется наполовину: Wikidata
даёт все названия и варианты (labels + aliases) по Q-номеру, но НЕ говорит,
в какую эпоху какое из них употреблялось. Это остаётся вашим решением.
Поэтому здесь собирается заготовка: список водоёмов с их историческими
названиями, а периоды вы проставляете сами.

Лицензия
--------
Wikidata — CC0, общественное достояние. Можно использовать в платном
продукте без ограничений и без атрибуции. Это единственная причина,
по которой сюда не подмешаны Wikipedia-тексты: их лицензия CC BY-SA
требует указания автора и той же лицензии downstream.

Как пользоваться
----------------
    python3 tools/harvest_wikidata.py doctor
    python3 tools/harvest_wikidata.py battles   rome117      # морские сражения
    python3 tools/harvest_wikidata.py epidemics rome117      # эпидемии
    python3 tools/harvest_wikidata.py waters    rome117      # названия водоёмов
    python3 tools/harvest_wikidata.py all       rome117      # всё сразу

Результат кладётся рядом с остальными данными эпохи:
    maps/eras/<эпоха>/sea_battles.auto.csv
    maps/eras/<эпоха>/geom/epidemics.geojson
    maps/eras/<эпоха>/water_names.auto.csv

Файлы с суффиксом .auto.csv перезаписываются при каждом запуске. Ваши правки
надо вносить в sea_battles.csv и water_names.csv — сборка карты читает именно
их. Скопировать заготовку в рабочий файл:

    cp maps/eras/rome117/sea_battles.auto.csv maps/eras/rome117/sea_battles.csv

Про лимиты
----------
SPARQL-эндпоинт Wikidata отдаёт 429 Too Many Requests, если слать подряд.
Замерено на себе: два запроса с паузой 8 секунд — второй уже 429;
с паузой 75 секунд — проходит. Здесь между запросами пауза 70 секунд,
и на 429 делается до трёх повторов с ростом ожидания. Один прогон
`all` занимает примерно три-четыре минуты — это нормально, не прерывайте.

User-Agent обязателен: без него Wikidata блокирует запрос сразу.
"""

import csv
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERAS = os.path.join(ROOT, "maps", "eras")

SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"

# Без осмысленного User-Agent Wikidata отвечает 403. Формат просит указывать
# контакт — подставьте свой, это снижает шанс блокировки.
UA = ("ChronoMapa-harvest/1.0 (historical map project; contact: user@example.org) "
      "python-urllib")

# Пауза между запросами к SPARQL, секунд. Замерено: 8 с — 429, 75 с — 200.
GAP = 70

# Пауза между запросами внутри одного прогона, когда их много. Обычный API
# Wikidata (wbgetentities) гораздо мягче к частоте, чем SPARQL, поэтому
# внутри класса можно идти быстрее. Замерено: прогон водоёмов с паузой 20 с
# между классами прошёл без единого 429.
SPARQL_GAP = 20

# ---------------------------------------------------------------------------
# Классы Wikidata. ВСЕ проверены через wbsearchentities 22.10.2026, а не взяты
# по памяти. Первый раз я написал сюда Q189574 и Q19822712 «по памяти» —
# запрос вернул ноль результатов. Настоящие номера:
#
#   Q44512    epidemic       «rapid spread of infectious disease…»
#   Q12184    pandemic       «epidemic … spread across a large region»
#   Q1261499  naval battle   «battle at sea or on a body of water»
#
# Отдельно проверенные объекты, которые обязаны находиться в выборке —
# по ним функция doctor сверяет, что запрос вообще работает:
#   Q42005    Black Death / Чёрная смерть
#   Q821711   Plague of Justinian / Юстинианова чума
#   Q178850   битва при Саламине
CLASSES_EPIDEMICS = ["Q44512", "Q12184"]

# P276 «location» — где произошло событие. Для пандемии это РЕГИОНЫ, а не точка.
# Замерено на Чёрной смерти (Q42005): P625 (координаты) у неё НЕТ вовсе, зато
# P276 = Q48 (Азия), Q46 (Европа), Q27381, Q18869 — четыре региона;
# P580/P582 = 1346…1352; P1120 = 75 000 000 жертв.
#
# Отсюда следует главное про этот слой: строить буфер вокруг координат
# бессмысленно — у крупнейших пандемий координат нет. Нужно брать список
# поражённых регионов и отдавать его вам как заготовку, а контур вы рисуете
# в QGIS по своим регионам. Именно так и сделано в cmd_epidemics.
P_LOCATION = "P276"
P_COUNTRY = "P17"
P_DEATHS = "P1120"
CLASSES_BATTLES = ["Q1261499"]
MUST_FIND = {"Q42005": "Чёрная смерть", "Q821711": "Юстинианова чума",
             "Q178850": "битва при Саламине"}

# Классы природных водоёмов — для слоя исторических названий.
#
# ВСЕ проверены через wbsearchentities 22.10.2026. Первый вариант этого списка
# я написал по памяти, и doctor показал, что четыре номера из шести были
# неверны: Q23397 оказался ОЗЕРОМ (а не морем), Q35032 — ПРАВОСЛАВНОЙ ЦЕРКОВЬЮ,
# Q35509 — ПЕЩЕРОЙ, Q40880 — итальянской коммуной Таламона. Запрос с такими
# классами не падает — он молча возвращает ерунду. Поэтому doctor сверяет
# каждый номер отдельно и показывает его английскую и русскую подпись.
# Порядок в списке осмысленный: моря и проливы первыми, потому что именно их
# исторические названия нужны чаще всего (Понт Эвксинский, Меотида, Геллеспонт).
#
# Третье число — предел выборки на класс. Без него слой распухает до нерабочего
# состояния: замерено, что бухт в Wikidata 1200+, озёр 1200+, проливов 430,
# и файл на 3401 строку уже нельзя ни открыть, ни проверить. Исторические
# названия мелких бухт не нужны никому, а моря нужны все.
#
# ★ ГЛАВНОЕ ПРО КЛАСС МОРЕ. Запрос `?item wdt:P31 wd:Q165` ЧЁРНОЕ МОРЕ НЕ НАХОДИТ.
# Проверено 22.10.2026: у Q166 (Чёрное море) P31 = Q1973404, а Q1973404 — это
# «adjacent sea / внутреннее море», которое само является подклассом Q165
# (P279 = Q165). У Средиземного моря (Q4918) вообще два P31: Q1973404 и
# Q166620 (водосборный бассейн). Поэтому по морям, проливам и заливам нужен
# обход по иерархии: `wdt:P31/wdt:P279*`. С ним морей находится 149, и все
# нужные на месте — Чёрное, Средиземное, Мраморное, Эгейское, Каспийское,
# Балтийское, все с координатами. Без обхода — 89, и без Чёрного и Средиземного.
# Для рек и озёр обход не нужен: там P31 указывает на класс напрямую.
CLASSES_WATERS = [
    # Q-номер    название    предел   нужен ли обход по P279*
    ("Q165",     "море",      300,     True),
    ("Q37901",   "пролив",    120,     True),
    ("Q1322134", "залив",      80,     True),
    ("Q9430",    "океан",      20,     True),
    ("Q4022",    "река",      250,     False),
    ("Q23397",   "озеро",     150,     False),
]

# ---------------------------------------------------------------------
# ОБЯЗАТЕЛЬНЫЕ ВОДОЁМЫ. Запрос по классу с LIMIT отдаёт произвольную выборку,
# и важные объекты из неё молча выпадают. Замерено 22.10.2026: при LIMIT 250
# по классу «река» в файл попали Дон и Тибр, но НЕ попали Дунай, Тигр, Евфрат
# и Днепр — четыре реки, без которых античная карта бессмысленна. Ошибки при
# этом не было никакой: запрос честно вернул 250 строк, просто не те.
#
# Поэтому обязательные водоёмы добираются ОТДЕЛЬНЫМ запросом по названию
# (wbsearchentities, не SPARQL — он быстрый и без лимита на выборку), и их
# присутствие проверяется явно. Список правьте под свои эпохи: для средневековья
# сюда просится Янцзы и Ганг, для Нового времени — Миссисипи и Амазонка.
# Явные Q-номера для тех, где поиск по названию даёт НЕ ТО.
# Все проверены через wbsearchentities 22.10.2026:
#   Q35591  Tigris — «river flowing from Turkey through Iraq and Syria».
#           По запросу «Тигр» первым приходит Q19939 = tiger, вид кошачьих.
#   Q36124  Strait of Gibraltar. По запросу «Гибралтар» первым приходит город.
#   Q166    Чёрное море. Проверял отдельно, потому что сначала взял по памяти
#           Q3313 — это оказалась категория «Архитекторы Словакии».
WATERS_BY_QID = {
    "Q35591": "Тигр",
    "Q36124": "Гибралтарский пролив",
    "Q166":   "Чёрное море",
    "Q4918":  "Средиземное море",
    "Q35367": "Мраморное море",
    "Q1653":  "Дунай",
    "Q34589": "Евфрат",
    "Q48256": "Днепр",
    "Q131210":"Днестр",
    "Q3392":  "Нил",
    "Q7348":  "Инд",
    "Q5089":  "Ганг",
    "Q6514":  "Дарданеллы",
    "Q35958": "Босфор",
    # Озёра, которые поиском по русскому названию находятся неверно.
    # «Ван» → Q6593 Vannes, коммуна во Франции; разбор по словам про воду его
    # не спасает. «Чад» и «Иссык-Куль» дают одноимённые регионы и страны.
    # Все четыре номера проверены через wbsearchentities 22.10.2026:
    #   Q126307 Lake Van · Q125309 Lake Chad · Q126982 Sea of Galilee ·
    #   Q42191 Issyk-Kul. Я сначала написал сюда Q127099 по памяти — номер
    #   оказался чужим. Это ровно та ошибка, против которой написан doctor.
    "Q126307": "озеро Ван",
    "Q125309": "озеро Чад",
    "Q126982": "Галилейское море",
    "Q42191":  "Иссык-Куль",
}

# Слова, по которым из нескольких кандидатов выбирается ВОДОЁМ, а не тёзка.
WATER_HINTS = ("river", "reka", "река", "sea", "море", "strait", "пролив",
               "lake", "озеро", "ocean", "океан", "gulf", "залив", "bay",
               "бухта", "water", "вод", "fluss", "fleuve", "rio", "rivier",
               "çay", "nehri", "potok", "ponto", "mare", "meer", "mer",
               "lagoon", "лагуна", "reservoir", "водохранилище", "canal", "канал")


def _pick_water(cands, want):
    """
    Из результатов поиска по названию выбрать водоём, а не тёзку.

    Реальный случай: на запрос «Тигр» Wikidata отдаёт
      1. Q19939  tiger — «species of big cat»
      2. Q35591  Tigris — «river flowing from Turkey through Iraq and Syria»
      3. Q151221 Tiger I — танк
      4. Q740762 Tiger — знак зодиака
    Брать первый результат — значит положить в слой исторических названий рек
    большого кота. Поэтому выбираем того, у кого в описании есть слово про воду,
    а если таких нет — первого, но с честной пометкой в отчёте.
    """
    for c in cands or []:
        blob = ((c.get("description") or "") + " " + (c.get("label") or "")).lower()
        if any(h in blob for h in WATER_HINTS):
            return c, True
    return (cands[0] if cands else None), False


WATERS_ESSENTIAL = [
    # моря, без которых не читается античная и средневековая карта
    "Чёрное море", "Средиземное море", "Мраморное море", "Эгейское море",
    "Ионическое море", "Адриатическое море", "Красное море",
    "Каспийское море", "Балтийское море", "Северное море",
    "Аравийское море", "Азовское море",
    # проливы
    "Босфор", "Дарданеллы", "Гибралтарский пролив", "Керченский пролив",
    "пролив Босфор",
    # реки Древнего Востока и античности
    "Нил", "Тигр", "Евфрат", "Инд", "Ганг", "Дунай", "Рейн", "Рона",
    "Днепр", "Днестр", "Дон", "Волга", "Западный Буг", "По",
    "Луара", "Сена", "Гвадалквивир", "Эбро", "Тахо", "Иордан",
    "Хуанхэ", "Янцзы", "Меконг", "Евфрат",
    # озёра
    "Аральское море", "Байкал", "Ладожское озеро", "Онежское озеро",
    "Чад", "Виктория", "Галилейское море", "Иссык-Куль", "Ван", "Урмия",
]
# Дубли в списке намеренно оставлены: «Босфор» и «пролив Босфор» — две разные
# строки поиска, и одна из них может не сработать. Перед запросом список
# очищается от повторов по найденному Q-номеру, а не по тексту.


# Бухты (Q39594) из списка убраны намеренно: их в Wikidata больше 1200,
# исторических названий у мелких бухт нет, а место в файле они съедают.
# Если понадобятся — добавьте строку ("Q39594", "бухта", 100, True).


def log(msg=""):
    print(msg, flush=True)


# ============================================================ HTTP ==========

def _get(url, params=None, accept="application/json", tries=4):
    """
    GET с повторами на 429/5xx и на обрыв соединения.

    429 у Wikidata означает «слишком часто», а не «нельзя»: ждать и повторять
    можно. Растущая пауза 40/80/120/160 с на практике доводит запрос до успеха.
    """
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": accept,
            "Accept-Language": "ru,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                wait = 40 + 40 * i
                log(f"    {last} — ждём {wait} с и пробуем снова ({i + 1}/{tries})")
                time.sleep(wait)
                continue
            raise
        except Exception as e:                      # обрыв, таймаут
            last = repr(e)[:120]
            wait = 20 + 20 * i
            log(f"    {last} — ждём {wait} с")
            time.sleep(wait)
    raise RuntimeError(f"не удалось получить {url[:90]}… последняя ошибка: {last}")


def sparql(query, tries=3):
    """Запрос к SPARQL. Возвращает список словарей {имя: значение}."""
    last = None
    for i in range(tries):
        if i:
            wait = GAP * (i + 1)
            log(f"    повтор через {wait} с ({i + 1}/{tries})")
            time.sleep(wait)
        body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
        req = urllib.request.Request(SPARQL, data=body, headers={
            "User-Agent": UA,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            log(f"    SPARQL вернул {last}")
            if e.code == 429:
                continue
            raise
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            # Wikidata под нагрузкой отдаёт HTML-страницу с кодом 200 — та же
            # ловушка, что у Overpass OHM. Лечится только ожиданием.
            last = f"ответ не JSON ({len(raw)} байт, начинается с {raw[:40]!r})"
            log(f"    {last}")
            time.sleep(GAP)
            continue
        out = []
        for b in d.get("results", {}).get("bindings", []):
            out.append({k: v.get("value") for k, v in b.items()
                        if isinstance(v, dict) and v.get("value") is not None})
        return out
    raise RuntimeError(f"SPARQL не ответил после {tries} попыток: {last}")


# ====================================================== РАЗБОР ДАТ ==========

def parse_year(v):
    """
    Дата Wikidata → целое число лет. Отрицательное = до нашей эры.

    Wikidata отдаёт дату в формате ISO 8601, но для древности он вырождается:
    «-0479-09-2x» у Саламина, «0050-00-00» у объектов без известного месяца.
    Берём только год, потому что месяц у античных событий обычно спорный,
    а для карты достаточно года.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^([+-]?\d{1,10})", s)
    if not m:
        return None
    try:
        y = int(m.group(1))
    except ValueError:
        return None
    # «0050» → 50, «-0479» → −479. Ноль в исторических датах не встречается,
    # а 0000 по ISO означает «год не указан».
    return y


def parse_point(v):
    """«Point(23.56666667 37.95138889)» → (lon, lat) или None."""
    if not v:
        return None
    m = re.search(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", str(v))
    if not m:
        return None
    try:
        lon, lat = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return lon, lat


def qid_of(url):
    return str(url or "").rsplit("/", 1)[-1].strip()


# ============================================================ ЭПОХА ========

def load_era(era_id):
    """
    Читает era.yml БЕЗ сторонних библиотек.

    PyYAML в песочнице то стоит, то нет, а нам нужны три числа и одна строка.
    Разбираем вручную: этого достаточно для плоского паспорта эпохи.
    """
    path = os.path.join(ERAS, era_id, "era.yml")
    if not os.path.exists(path):
        raise SystemExit(f"нет файла {path}. Доступные эпохи: "
                         + ", ".join(sorted(d for d in os.listdir(ERAS)
                                            if not d.startswith(("_", ".")))))
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.lstrip().startswith("#") or ":" not in line:
            continue
        if line[:1] in (" ", "\t"):          # вложенные списки не трогаем
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.split("#")[0].strip().strip('"').strip("'")
    year = parse_year(out.get("year"))
    if year is None:
        raise SystemExit(f"в {path} не разобрано поле year: {out.get('year')!r}")
    vf = parse_year(out.get("valid_from"))
    vt = parse_year(out.get("valid_to"))
    if vf is None or vt is None:
        # запасной вариант: ±50 лет от точки эпохи
        vf, vt = year - 50, year + 50
    return {"id": era_id, "year": year, "valid_from": vf, "valid_to": vt,
            "name_ru": out.get("name_ru", "")}


# ================================================== МОРСКИЕ СРАЖЕНИЯ =======

# Q-номер Wikidata: Q и цифры. Natural Earth содержит и мусор — замерено,
# что у озера Ямбуто в поле wikidata стоит «-1». Без проверки такой «номер»
# ушёл бы в запрос пачкой и испортил бы всю пачку.
QID_RE = re.compile(r"^Q[1-9]\d*$")

# Карта Q-номера класса → русское название. Нужна, чтобы у объекта,
# добытого по Q-номеру с карты, было понятное поле class_ru.
CLASS_NAMES = {
    "Q165": "море", "Q37901": "пролив", "Q1322134": "залив", "Q39594": "бухта",
    "Q9430": "океан", "Q4022": "река", "Q23397": "озеро",
    "Q1973404": "внутреннее море", "Q166620": "водосборный бассейн",
    "Q35657": "русло", "Q55659167": "водоток", "Q47521": "поток",
    "Q187971": "водопад", "Q188161": "ледник", "Q355304": "водоносный горизонт",
}


def names_from_qids(qids, progress_every=200):
    """
    Забрать labels и aliases у списка Q-номеров через обычный API.

    Это wbgetentities, а не SPARQL: он быстрый, не имеет предела выборки и
    не страдает от того, что нужный объект не попал в первые N строк. Пачки
    по 50 — эмпирический предел, при большем ответ приходит не полностью.

    Возвращает {Q-номер: {"name_ru":…, "class_ru":…, "coord":…, "names":[…]}}.
    """
    out = {}
    qids = [q for q in dict.fromkeys(qids) if QID_RE.match(q)]
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        try:
            raw = _get(API, {"action": "wbgetentities", "ids": "|".join(chunk),
                             "props": "labels|aliases|claims", "format": "json"})
            d = json.loads(raw)
        except Exception as e:
            log(f"      ! пачка {i // 50 + 1} не получена: {e!r:.80}")
            time.sleep(5)
            continue
        for qi, ent in (d.get("entities") or {}).items():
            if ent.get("missing") == "" or not ent:
                continue
            ru = ((ent.get("labels") or {}).get("ru") or {}).get("value")
            en = ((ent.get("labels") or {}).get("en") or {}).get("value")
            if not (ru or en):
                continue
            # Все названия. labels — словарь, aliases — СПИСОК вариантов на
            # каждый язык. Перепутать их легко: итерация «взять .get('value')»
            # по aliases падает с AttributeError: 'list' object has no
            # attribute 'get'. Эта ошибка уже случалась и исправлена здесь.
            names = []
            for lg, v in (ent.get("labels") or {}).items():
                if isinstance(v, dict):
                    val = (v.get("value") or "").strip()
                    if val and val not in names:
                        names.append(val)
            for lg, arr in (ent.get("aliases") or {}).items():
                if isinstance(arr, dict):
                    arr = [arr]
                for v in (arr or []):
                    if not isinstance(v, dict):
                        continue
                    val = (v.get("value") or "").strip()
                    if val and val not in names:
                        names.append(val)
            claims = ent.get("claims") or {}
            p31 = []
            for c in claims.get("P31", []):
                try:
                    p31.append(c["mainsnak"]["datavalue"]["value"]["id"])
                except Exception:
                    continue
            cls = next((CLASS_NAMES[q] for q in p31 if q in CLASS_NAMES), "")
            coord = None
            for c in claims.get("P625", []):
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    coord = parse_point(f"Point({v['longitude']} {v['latitude']})")
                    if coord:
                        break
                except Exception:
                    continue
            out[qi] = {"name_ru": ru or en, "class_ru": cls,
                       "coord": coord, "names": names}
        if progress_every and (i // 50 + 1) % (progress_every // 50) == 0:
            log(f"      названия: {min(i + 50, len(qids))} из {len(qids)}")
        time.sleep(2)
    return out


def qids_from_map(era_id):
    """
    Q-номера водоёмов, которые РЕАЛЬНО лежат на карте этой эпохи.

    Зачем это нужно. Первый вариант слоя названий строился от запроса к
    Wikidata «дай мне моря, проливы, реки…» с LIMIT на каждый класс. Замер
    23.10.2026 показал, что так теряется почти всё: на карте 117 года было
    **412 уникальных Q-номеров** водоёмов, а в собранном списке нашлось
    только **72** из них — 340 (83%) пропали. Среди пропавших Юкон, Цзиньша,
    Гань, Уаикато, Сент-Клэр — всё это настоящие реки, просто их вытеснили
    другие реки в пределах LIMIT.

    Причина в том, что Natural Earth УЖЕ несёт поле wikidata: замерено, что
    его имеют 550 из 600 базовых объектов гидрографии (92%). Значит список
    нужных водоёмов уже лежит на вашей карте, и запрашивать Wikidata надо
    именно по нему — а не надеяться, что ограниченный запрос вернёт те же
    объекты.

    Запрос по классам после этого всё равно остаётся, но как ДОПОЛНЕНИЕ: он
    нужен для морей и проливов, которых на карте может не оказаться, и для
    того, чтобы вы видели варианты названий у объектов, которых у вас пока нет.
    """
    path = os.path.join(ERAS, era_id, "geom", "hydro.geojson")
    if not os.path.exists(path):
        return [], 0
    d = json.load(open(path, encoding="utf-8"))
    qids, bad = [], []
    for f in d.get("features", []):
        p = f.get("properties") or {}
        v = str(p.get("wikidata") or "").strip()
        if not v:
            continue
        if QID_RE.match(v):
            qids.append(v)
        else:
            bad.append((v, p.get("name_ru") or p.get("name_en") or "?"))
    uniq = list(dict.fromkeys(qids))
    if bad:
        seen = set()
        log(f"      ! в Natural Earth попадается мусор в поле wikidata — "
            f"{len(bad)} шт., отброшено:")
        for v, nm in bad:
            if v in seen:
                continue
            seen.add(v)
            log(f"          wikidata=«{v}» у «{nm}» — не похоже на Q-номер")
            if len(seen) >= 5:
                break
        if len(seen) > 5:
            log(f"          …и ещё {len(seen) - 5}")
    return uniq, len(qids)


def build_query(classes, extra=""):
    values = " ".join(f"wd:{q}" for q in classes)
    return f"""
SELECT ?item ?itemLabel ?coord ?start ?end ?when ?deaths ?part ?partLabel
WHERE {{
  VALUES ?c {{ {values} }}
  ?item wdt:P31 ?c .
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?item wdt:P580 ?start }}
  OPTIONAL {{ ?item wdt:P582 ?end }}
  OPTIONAL {{ ?item wdt:P585 ?when }}
  OPTIONAL {{ ?item wdt:P1120 ?deaths }}
  OPTIONAL {{ ?item wdt:P710 ?part }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
  {extra}
}}
LIMIT 5000
""".strip()


def cmd_battles(era):
    """
    Морские сражения эпохи → sea_battles.auto.csv.

    Берём из Wikidata все объекты класса Q1261499 (naval battle), оставляем те,
    что попали в окно эпохи, и пишем в CSV формата, который уже понимает
    build_map.py. Координаты и дата приходят готовыми — это тот редкий слой,
    где автоматика даёт почти всё.

    Чего автоматика НЕ даёт и что придётся дописать в QGIS или в CSV:
      * какие именно флоты столкнулись (P710 даёт участников, но для античных
        сражений там часто пусто или стоят государства, а не флоты);
      * исход сражения;
      * ссылка на вашу статью в content/.
    """
    log(f"  Запрос к Wikidata: морские сражения (класс Q1261499)…")
    rows = sparql(build_query(CLASSES_BATTLES))
    log(f"    получено {len(rows)} объектов за всю историю")

    # Дедупликация: SPARQL возвращает по строке на каждого участника (P710),
    # поэтому Саламин может прийти трижды. Сводим по Q-номеру, участников
    # склеиваем в одно поле.
    by_q = {}
    for r in rows:
        q = qid_of(r.get("item"))
        if not q:
            continue
        cur = by_q.setdefault(q, {"label": r.get("itemLabel", ""),
                                  "coord": r.get("coord"), "parts": [],
                                  "deaths": r.get("deaths"),
                                  "start": r.get("start") or r.get("when"),
                                  "end": r.get("end")})
        if not cur["coord"] and r.get("coord"):
            cur["coord"] = r["coord"]
        p = (r.get("partLabel") or "").strip()
        if p and p not in cur["parts"]:
            cur["parts"].append(p)
        if not cur["label"] and r.get("itemLabel"):
            cur["label"] = r["itemLabel"]

    vf, vt = era["valid_from"], era["valid_to"]
    y0, y1 = vf - 200, vt + 200          # окно шире эпохи: битва до или после
    picked, no_coord, no_date = [], 0, 0
    for q, r in sorted(by_q.items()):
        y = parse_year(r["start"])
        if y is None:
            no_date += 1
            continue
        if not (y0 <= y <= y1):
            continue
        pt = parse_point(r["coord"])
        if not pt:
            no_coord += 1
            # Оставляем в отчёте, но без координат на карту не поставить.
            picked.append((q, r, y, None))
            continue
        picked.append((q, r, y, pt))

    picked.sort(key=lambda x: x[2])
    log(f"    в окно {y0}…{y1} попало {len(picked)} сражений"
        f"  (без даты {no_date}, без координат {no_coord})")

    dst = os.path.join(ERAS, era["id"], "sea_battles.auto.csv")
    cols = ["wikidata", "year", "month", "day", "kind", "title_ru",
            "lon", "lat", "z_min", "fleets_ru", "outcome_ru", "deaths",
            "article", "icon", "note", "source"]
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for q, r, y, pt in picked:
            w.writerow({
                "wikidata": q,
                "year": y, "month": "", "day": "",
                "kind": "морское сражение",
                "title_ru": r["label"],
                "lon": round(pt[0], 5) if pt else "",
                "lat": round(pt[1], 5) if pt else "",
                # Морской бой виден только при достаточном приближении:
                # на z0–3 точка в океане ничего не сообщает.
                "z_min": 4,
                "fleets_ru": "; ".join(r["parts"]) if r["parts"] else "",
                "outcome_ru": "",
                "deaths": int(float(r["deaths"])) if r.get("deaths") else "",
                "article": "",
                "icon": "anchor",
                "note": "" if pt else "НЕТ КООРДИНАТ: найдите их и впишите "
                                      "lon/lat, иначе точка не появится",
                "source": f"Wikidata {q} (CC0)",
            })
    log(f"    записано: {dst}")
    return picked


# ========================================================== ЭПИДЕМИИ =======

def cmd_epidemics(era):
    """
    Эпидемии и пандемии эпохи → geom/epidemics.geojson + epidemics_regions.csv.

    Почему этот слой устроен не так, как остальные.

    Первая версия, которую я написал, строила буфер-окружность вокруг точки
    из P625 и считала радиус от длительности. Она НЕ РАБОТАЕТ, и вот почему:
    у крупнейших пандемий координат в Wikidata просто нет. Замерено на
    Чёрной смерти (Q42005): P625 отсутствует, зато есть P276 «location» с
    четырьмя регионами — Q48 Азия, Q46 Европа, Q27381 и Q18869 — и даты
    P580/P582 = 1346…1352, и P1120 = 75 000 000 жертв. То же у Юстиниановой
    чумы (Q821711). Буфер вокруг пустоты — это ноль объектов на карте.

    Поэтому сделано иначе и в два файла:

      geom/epidemics.geojson   — точки: центр каждой эпидемии (если он есть)
                                 плюс центр каждого поражённого региона.
                                 Слой рисуется как подписи с датами.
      epidemics_regions.csv    — ЗАГОТОВКА: по строке на пару
                                 «эпидемия × регион», с названием региона,
                                 его Q-номером, датами и ПУСТЫМИ колонками
                                 match и note.

    Контур вы рисуете сами в QGIS, а в epidemics_regions.csv вписываете,
    какой ваш полигон соответствует региону из Wikidata. Автоматически
    сопоставить «Азия» из Wikidata с вашим полигоном Азии нельзя: у вас
    границы свои, нарисованные по источникам, а у Wikidata регион — это
    понятие без геометрии.

    Что автоматика даёт полностью: список эпидемий эпохи, их даты, число
    жертв, список поражённых регионов и координаты этих регионов. Это уже
    достаточно, чтобы слой появился на карте и чтобы было что проверять.
    """
    log(f"  Запрос к Wikidata: эпидемии (Q44512) и пандемии (Q12184)…")
    values = " ".join(f"wd:{q}" for q in CLASSES_EPIDEMICS)
    q = f"""
SELECT ?item ?itemLabel ?start ?end ?when ?deaths ?place ?placeLabel ?country ?countryLabel ?coord
WHERE {{
  VALUES ?c {{ {values} }}
  ?item wdt:P31 ?c .
  OPTIONAL {{ ?item wdt:P580 ?start }}
  OPTIONAL {{ ?item wdt:P582 ?end }}
  OPTIONAL {{ ?item wdt:P585 ?when }}
  OPTIONAL {{ ?item wdt:{P_DEATHS} ?deaths }}
  OPTIONAL {{ ?item wdt:{P_LOCATION} ?place }}
  OPTIONAL {{ ?item wdt:{P_COUNTRY} ?country }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
}}
LIMIT 5000
""".strip()
    rows = sparql(q)
    log(f"    получено строк {len(rows)} (по строке на каждый регион)")

    # Сводим: по одной записи на эпидемию, регионы собираем списком.
    by_q = {}
    for r in rows:
        qi = qid_of(r.get("item"))
        if not qi:
            continue
        cur = by_q.setdefault(qi, {
            "label": r.get("itemLabel", ""),
            "start": parse_year(r.get("start") or r.get("when")),
            "end": parse_year(r.get("end")),
            "deaths": r.get("deaths"),
            "coord": r.get("coord"),
            "places": [], "countries": [],
        })
        if not cur["label"] and r.get("itemLabel"):
            cur["label"] = r["itemLabel"]
        if cur["start"] is None:
            cur["start"] = parse_year(r.get("start") or r.get("when"))
        if cur["end"] is None:
            cur["end"] = parse_year(r.get("end"))
        pq, pl = qid_of(r.get("place")), (r.get("placeLabel") or "").strip()
        if pq and (pq, pl) not in cur["places"]:
            cur["places"].append((pq, pl))
        cq, cl = qid_of(r.get("country")), (r.get("countryLabel") or "").strip()
        if cq and (cq, cl) not in cur["countries"]:
            cur["countries"].append((cq, cl))

    vf, vt = era["valid_from"], era["valid_to"]
    picked = []
    for qi, r in sorted(by_q.items()):
        s0 = r["start"]
        if s0 is None:
            continue
        e0 = r["end"] if r["end"] is not None else s0 + 5
        # Эпидемия относится к эпохе, если её период ПЕРЕСЕКАЕТ окно эпохи,
        # а не если началась внутри него: Чёрная смерть 1346–1352 должна
        # попасть в срез 1350 года.
        if e0 < vf or s0 > vt:
            continue
        picked.append((qi, r, s0, e0))

    picked.sort(key=lambda x: x[2])
    log(f"    пересекают эпоху {vf}…{vt}: {len(picked)} эпидемий")

    # Координаты самих регионов: у «Азии» (Q48) есть P625, и по ней видно,
    # где именно рисовать. Забираем обычным API пачками по 50.
    need = []
    for _, r, _, _ in picked:
        for pq, _pl in r["places"]:
            need.append(pq)
        for cq, _cl in r["countries"]:
            need.append(cq)
    need = list(dict.fromkeys(need))
    coords = {}
    names = {}
    log(f"    узнаю координаты {len(need)} регионов…")
    for i in range(0, len(need), 50):
        chunk = need[i:i + 50]
        try:
            raw = _get(API, {"action": "wbgetentities", "ids": "|".join(chunk),
                             "props": "claims|labels", "format": "json"})
            d = json.loads(raw)
        except Exception as e:
            log(f"      ! пачка {i // 50 + 1} не получена: {e!r:.90}")
            time.sleep(5)
            continue
        for qi, ent in (d.get("entities") or {}).items():
            ru = ((ent.get("labels") or {}).get("ru") or {}).get("value")
            en = ((ent.get("labels") or {}).get("en") or {}).get("value")
            names[qi] = ru or en or qi
            cl = (ent.get("claims") or {}).get("P625") or []
            for c in cl:
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    pt = parse_point(f"Point({v['longitude']} {v['latitude']})")
                    if pt:
                        coords[qi] = pt
                        break
                except Exception:
                    continue
        if i + 50 < len(need):
            time.sleep(2)

    got = sum(1 for q in need if q in coords)
    log(f"      координаты нашлись у {got} из {len(need)} регионов")

    # --- файл 1: слой на карте --------------------------------------------
    feats = []
    for qi, r, s0, e0 in picked:
        deaths = ""
        try:
            deaths = int(float(r["deaths"])) if r.get("deaths") else ""
        except Exception:
            deaths = ""
        centre = parse_point(r.get("coord"))
        regs = r["places"] + r["countries"]
        note = (f"Поражённые регионы по Wikidata: "
                + ", ".join(names.get(a, b or a) for a, b in regs[:10])
                if regs else
                "Регионы в Wikidata не указаны — определите их сами по источникам")
        if not centre and not regs:
            note += ". Ни координат, ни регионов нет: объект придётся " \
                    "размещать полностью вручную"
        base = {
            "wikidata": qi,
            "name_ru": r["label"],
            "name_local": "",
            "start": s0, "end": e0,
            "kind": "epidemic",
            "deaths_est": deaths,
            "status": "needs-review",
            "article": "",
            "note": note,
            "source": f"Wikidata {qi} (CC0)",
            "gap": "ареала нет: Wikidata хранит регионы понятиями, "
                   "контур надо нарисовать в QGIS",
        }
        # точка самой эпидемии, если она есть
        if centre:
            p = dict(base)
            p.update({"centre_lon": centre[0], "centre_lat": centre[1],
                      "point_kind": "epidemic_centre"})
            feats.append({"type": "Feature", "properties": p,
                          "geometry": {"type": "Point",
                                       "coordinates": [round(centre[0], 5),
                                                       round(centre[1], 5)]}})
        # точки поражённых регионов — по ним видно, где именно рисовать
        for pq, pl in regs:
            pt = coords.get(pq)
            if not pt:
                continue
            p = dict(base)
            p.update({"centre_lon": pt[0], "centre_lat": pt[1],
                      "point_kind": "affected_region",
                      "region_wikidata": pq,
                      "name_ru": names.get(pq, pl or pq),
                      "epidemic_wikidata": qi,
                      "epidemic_name": r["label"]})
            feats.append({"type": "Feature", "properties": p,
                          "geometry": {"type": "Point",
                                       "coordinates": [round(pt[0], 5),
                                                       round(pt[1], 5)]}})

    gdir = os.path.join(ERAS, era["id"], "geom")
    os.makedirs(gdir, exist_ok=True)
    dst = os.path.join(gdir, "epidemics.geojson")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh,
                  ensure_ascii=False)
    log(f"    записано: {dst}  ({len(feats)} точек)")

    # --- файл 2: заготовка для ручной привязки регионов --------------------
    dst2 = os.path.join(ERAS, era["id"], "epidemics_regions.auto.csv")
    cols = ["epidemic_wikidata", "epidemic_name_ru", "start", "end",
            "deaths_est", "region_wikidata", "region_name_ru",
            "region_lon", "region_lat", "match", "article", "note"]
    with open(dst2, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for qi, r, s0, e0 in picked:
            deaths = ""
            try:
                deaths = int(float(r["deaths"])) if r.get("deaths") else ""
            except Exception:
                pass
            regs = r["places"] + r["countries"]
            if not regs:
                # Пустой строкой помечаем, что эпидемия есть, а регионов нет:
                # иначе вы не узнаете, что здесь вообще должна быть работа.
                w.writerow({"epidemic_wikidata": qi, "epidemic_name_ru": r["label"],
                            "start": s0, "end": e0, "deaths_est": deaths,
                            "region_wikidata": "", "region_name_ru": "(не указаны)",
                            "region_lon": "", "region_lat": "", "match": "",
                            "article": "",
                            "note": "в Wikidata нет ни P276, ни P17 — регионы "
                                    "определите по источникам"})
                continue
            for rq, rl in regs:
                pt = coords.get(rq)
                w.writerow({
                    "epidemic_wikidata": qi, "epidemic_name_ru": r["label"],
                    "start": s0, "end": e0, "deaths_est": deaths,
                    "region_wikidata": rq,
                    "region_name_ru": names.get(rq, rl or rq),
                    "region_lon": round(pt[0], 5) if pt else "",
                    "region_lat": round(pt[1], 5) if pt else "",
                    # сюда вписываете имя ВАШЕГО полигона из geom/, которому
                    # соответствует этот регион
                    "match": "",
                    "article": "",
                    "note": "" if pt else "у региона нет координат в Wikidata",
                })
    log(f"    записано: {dst2}")
    return picked


# ================================================ НАЗВАНИЯ ВОДОЁМОВ =======

def cmd_waters(era):
    """
    Исторические названия водоёмов → water_names.auto.csv.

    Честно о том, что здесь автоматика делает, а что нет.

    ДЕЛАЕТ: находит в Wikidata крупные реки, моря, проливы и озёра, у каждого
    забирает ВСЕ названия и варианты (labels + aliases). Для Дуная это даст
    Dunărea, Donau, Danube, Δούναβης, Danubius, Ister и так далее — то есть
    весь набор имён, которыми водоём называли в разные эпохи.

    НЕ ДЕЛАЕТ: не говорит, какое из этих имён к какой эпохе относится.
    Wikidata хранит названия как плоский список без дат. Привязку «в 117 году
    н. э. римляне звали его Danubius» придётся сделать вам — по источникам.
    Поэтому файл отдаётся как ЗАГОТОВКА с пустыми колонками period_*_name.

    Второй честный момент: геометрию этот слой не добывает. Водоём уже есть
    на вашей карте — из Natural Earth или из OHM. Здесь только имена, и они
    подставляются к уже нарисованному по Q-номеру.

    Классы водоёмов ПРОВЕРЕНЫ через wbsearchentities; если Wikidata переименует
    класс, doctor это покажет.
    """
    # ПО ЗАПРОСУ НА КАЖДЫЙ КЛАСС, а не одним общим.
    #
    # Первый вариант слал один запрос с VALUES по всем семи классам и LIMIT 1500.
    # SPARQL не гарантирует порядка строк, и 1500 мест почти целиком съели реки
    # и озёра: в выборке оказались Азовское, Эгейское, Красное и Каспийское моря,
    # но НЕ оказалось Чёрного и Средиземного — двух главных морей для античной
    # карты. Молча, без ошибки: запрос просто вернул другие 1500 строк.
    #
    # Отдельный запрос на класс гарантирует, что редкий класс (морей в мире
    # около четырёхсот, рек — десятки тысяч) не будет вытеснен частым.
    rows = []

    # === ЭТАП 0. Водоёмы, которые РЕАЛЬНО лежат на карте этой эпохи. =======
    # Это главный этап: он гарантирует, что название найдётся для каждого
    # объекта карты. Запрос по классам ниже — только дополнение, потому что
    # LIMIT молча выбрасывает нужное (см. qids_from_map).
    map_qids, mentions = qids_from_map(era["id"])
    if map_qids:
        log(f"    с карты этой эпохи: {len(map_qids)} уникальных Q-номеров "
            f"({mentions} упоминаний)")
        got = names_from_qids(map_qids)
        log(f"      названия получены у {len(got)} из {len(map_qids)}")
        for qi, v in got.items():
            coord = v.get("coord")
            rows.append({
                "item": f"http://www.wikidata.org/entity/{qi}",
                "itemLabel": v.get("name_ru") or "",
                "coord": (f"Point({coord[0]} {coord[1]})" if coord else ""),
                "_class": v.get("class_ru") or "с карты",
                "_origin": "map",
                "_names": v.get("names") or [],
            })
        miss = len(map_qids) - len(got)
        if miss:
            log(f"      ! у {miss} Q-номеров названия не получены: либо номер "
                f"не существует, либо у объекта нет подписи ни на одном языке")
    else:
        log(f"    ! на карте этой эпохи нет объектов с wikidata — этап 0 пуст")
        log(f"      Соберите срез: python3 tools/extract_era.py ohm {era['id']} --overpass")

    # === ЭТАП 1. Запрос по классам — дополнение к карте. ===================
    for i, (cls, cls_name, limit, walk) in enumerate(CLASSES_WATERS):
        if i:
            log(f"    …пауза {SPARQL_GAP} с перед следующим классом")
            time.sleep(SPARQL_GAP)
        # walk=True → обход по иерархии подклассов. Без него Чёрное и
        # Средиземное моря не находятся: они экземпляры «внутреннего моря».
        inst = f"wdt:P31/wdt:P279* wd:{cls}" if walk else f"wdt:P31 wd:{cls}"
        q = f"""
SELECT DISTINCT ?item ?itemLabel ?coord WHERE {{
  ?item {inst} .
  ?item rdfs:label ?lbl .
  FILTER(LANG(?lbl) = "ru")
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru". }}
}}
LIMIT {limit}
""".strip()
        try:
            part = sparql(q)
        except Exception as e:
            log(f"    ! класс {cls} ({cls_name}) не получен: {e!r:.90}")
            continue
        for r in part:
            r["_class"] = cls_name
            r["_origin"] = "class"
        rows.extend(part)
        log(f"    {cls_name:8s} (wd:{cls:9s}{', с обходом подклассов' if walk else ''}) → {len(part)}")
    log(f"    всего {len(rows)} водоёмов")

    # --- добор обязательных водоёмов --------------------------------------
    # Идём по названию через wbsearchentities. Это обычный API, а не SPARQL:
    # он быстрый, не имеет предела выборки и не страдает от того, что нужная
    # река не попала в первые N строк.
    log(f"    добираю {len(WATERS_ESSENTIAL)} обязательных водоёмов по названию…")
    found_ess, miss_ess = {}, []
    # 1. Те, у кого Q-номер задан явно, — берём без поиска.
    for qi, name in WATERS_BY_QID.items():
        found_ess[qi] = (name, "Q-номер задан явно")

    # 2. Остальные — поиском по названию, с разбором тёзок.
    for name in dict.fromkeys(WATERS_ESSENTIAL):
        try:
            raw = _get(API, {"action": "wbsearchentities", "search": name,
                             "language": "ru", "type": "item", "format": "json",
                             "limit": "5"})
            cands = json.loads(raw).get("search") or []
        except Exception as e:
            log(f"      ! «{name}»: {e!r:.70}")
            miss_ess.append(name)
            time.sleep(1)
            continue
        c, sure = _pick_water(cands, name)
        if not c:
            miss_ess.append(name)
            time.sleep(1)
            continue
        qi = qid_of(c.get("id"))
        if qi in found_ess:
            time.sleep(1)
            continue
        if not sure:
            log(f"      ? «{name}» → {qi} «{c.get('label')}»: в описании нет "
                f"слова про воду, проверьте, тот ли объект "
                f"({(c.get('description') or '')[:44]})")
        found_ess[qi] = (c.get("label") or name,
                         (c.get("description") or "")[:40])
        time.sleep(1)
    log(f"      найдено {len(found_ess)}, не найдено {len(miss_ess)}")
    if miss_ess:
        log(f"      не нашлись: {', '.join(miss_ess[:12])}")

    # Забираем их координаты и названия тем же API, что и для остальных.
    if found_ess:
        ids = list(found_ess)
        for i in range(0, len(ids), 50):
            try:
                raw = _get(API, {"action": "wbgetentities",
                                 "ids": "|".join(ids[i:i + 50]),
                                 "props": "claims|labels|aliases", "format": "json"})
                d = json.loads(raw)
            except Exception as e:
                log(f"      ! пачка не получена: {e!r:.70}")
                time.sleep(3)
                continue
            for qi, ent in (d.get("entities") or {}).items():
                cl = (ent.get("claims") or {}).get("P625") or []
                pt = None
                for c in cl:
                    try:
                        v = c["mainsnak"]["datavalue"]["value"]
                        pt = parse_point(f"Point({v['longitude']} {v['latitude']})")
                        if pt:
                            break
                    except Exception:
                        continue
                ru = ((ent.get("labels") or {}).get("ru") or {}).get("value")
                if not pt or not ru:
                    continue
                rows.append({"item": f"http://www.wikidata.org/entity/{qi}",
                             "itemLabel": ru,
                             "coord": f"Point({pt[0]} {pt[1]})",
                             "_class": "обязательный", "_origin": "essential",
                             "_essential": qi})
            time.sleep(2)

    # Отбираем только те, что имеют отношение к эпохе: без координат привязать
    # имя к объекту на карте нечем.
    picked = []
    for r in rows:
        qi = qid_of(r.get("item"))
        pt = parse_point(r.get("coord"))
        if qi:
            # Координаты больше НЕ обязательны. Раньше объект без P625
            # выбрасывался, и именно поэтому моря с карты пропадали: у части
            # из них координат нет, а имя для карты всё равно нужно.
            picked.append((qi, r.get("itemLabel", ""), pt,
                           r.get("_class", ""), r.get("_origin", ""),
                           r.get("_names") or []))
    # Дедупликация по Q-номеру
    # Дедупликация: объект может прийти и с карты, и из запроса по классу,
    # и из обязательного списка. Приоритет — у версии с карты, потому что
    # у неё уже добыты все названия и не нужен второй запрос.
    prio = {"map": 0, "essential": 1, "class": 2}
    picked.sort(key=lambda x: prio.get(x[4], 3))
    seen, uniq = {}, []
    for qi, lbl, pt, cls, origin, names in picked:
        # Служебные классы «обязательный» и «с карты» — это НЕ класс водоёма,
        # а пометка о том, откуда объект пришёл. Раньше первый попавшийся
        # вариант записывался в class_ru и настоящий класс терялся: Чёрное
        # море (Q166) пришло из обязательного списка, получило
        # class_ru=«обязательный» и перестало опознаваться как море —
        # из-за этого подпись Понта Эвксинского не создавалась.
        REAL = cls if cls not in ("обязательный", "с карты") else ""
        if qi in seen:
            i, cur = seen[qi]
            merged = list(cur)
            if not merged[3] and REAL:
                merged[3] = REAL          # дописываем настоящий класс
            if not merged[2] and pt:
                merged[2] = pt            # дописываем координаты
            if not merged[5] and names:
                merged[5] = names         # дописываем названия
            uniq[i] = tuple(merged)
            continue
        # В слот класса кладём ТОЛЬКО настоящий класс, а не служебную пометку
        # «обязательный» / «с карты». Первая версия писала сюда `REAL or cls`,
        # то есть пометка занимала слот, и условие слияния `if not merged[3]`
        # после этого никогда не срабатывало: настоящий класс из запроса по
        # классам приходил позже и отбрасывался. Именно поэтому Чёрное море
        # и Дарданеллы так и остались с class_ru=«обязательный», хотя запрос
        # по классу «море» и «пролив» их честно возвращал (проверено отдельно:
        # обход P31/P279* от wd:Q165 даёт 142 моря с русской подписью, и все
        # пять нужных там есть).
        # Пометка о происхождении живёт в origin (слот 4) — она нужна для
        # приоритета и для колонки on_map, и класс не подменяет.
        seen[qi] = (len(uniq), [qi, lbl, pt, REAL, origin, names])
        uniq.append((qi, lbl, pt, REAL, origin, names))
    with_coord = sum(1 for u in uniq if u[2])
    from_map = sum(1 for u in uniq if u[4] == "map")
    log(f"    без повторов: {len(uniq)}  (с карты {from_map}, с координатами {with_coord})")

    # Забираем все названия пачками по 50 — это обычный API, не SPARQL,
    # поэтому лимиты мягче и запросы быстрее.
    #
    # Но для объектов, пришедших С КАРТЫ, названия уже добыты на этапе 0
    # функцией names_from_qids — повторно запрашивать их смысла нет. Замер:
    # на срезе 117 года таких 411, то есть без переиспользования пришлось бы
    # сделать лишних восемь пачек запросов.
    labels = {}
    need = []
    for qi, lbl, pt, cls, origin, names in uniq:
        if names:
            labels[qi] = names
        else:
            need.append(qi)
    log(f"    названия уже есть у {len(labels)}, дозапрашиваем {len(need)}")
    batch = 50
    for i in range(0, len(need), batch):
        chunk = need[i:i + batch]
        params = {"action": "wbgetentities", "ids": "|".join(chunk),
                  "props": "labels|aliases", "format": "json"}
        try:
            raw = _get(API, params)
            d = json.loads(raw)
        except Exception as e:
            log(f"    ! пачка {i // batch + 1} не получена: {e!r:.90}")
            continue
        for qi, ent in (d.get("entities") or {}).items():
            names = []
            # labels и aliases устроены РАЗНО, и я это сначала перепутал:
            #   labels  = {"ru": {"language":"ru","value":"Дунай"}, …}   — словарь
            #   aliases = {"ru": [{"value":"Данубиус"}, {"value":"Истр"}]} — СПИСОК
            # Итерация «для всех взять .get("value")» на aliases падала с
            # AttributeError: 'list' object has no attribute 'get'.
            for lg, v in (ent.get("labels") or {}).items():
                if isinstance(v, dict):
                    val = (v.get("value") or "").strip()
                    if val and val not in names:
                        names.append(val)
            for lg, arr in (ent.get("aliases") or {}).items():
                if isinstance(arr, dict):
                    arr = [arr]
                for v in (arr or []):
                    if not isinstance(v, dict):
                        continue
                    val = (v.get("value") or "").strip()
                    if val and val not in names:
                        names.append(val)
            labels[qi] = names
        if i + batch < len(need):
            time.sleep(2)          # обычный API мягче, но паузу держим
        if (i // batch) % 5 == 0:
            log(f"    названия: {min(i + batch, len(need))} из {len(need)}")

    dst = os.path.join(ERAS, era["id"], "water_names.auto.csv")
    cols = ["wikidata", "class_ru", "on_map", "name_modern_ru", "lon", "lat",
            "all_names", "ancient_name", "ancient_from", "ancient_to",
            "medieval_name", "medieval_from", "medieval_to",
            "epoch_name", "epoch_from", "epoch_to",
            "article", "note", "source"]
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for qi, lbl, pt, cls, origin, _names in uniq:
            names = labels.get(qi, [])
            w.writerow({
                "wikidata": qi,
                # Пустой class_ru означает, что объект не попал ни в один
                # запрос по классам. Тогда пишем происхождение — это честнее,
                # чем пустая ячейка, и match_waters.py определит акваторию
                # по названию.
                # Служебные пометки происхождения переводим на русский,
                # чтобы в файле не мешались «map» и «essential» среди
                # «река» и «озеро».
                "class_ru": cls or {"map": "с карты",
                                    "essential": "обязательный",
                                    "class": ""}.get(origin, origin) or "",
                "on_map": "да" if origin == "map" else "",
                "name_modern_ru": lbl,
                # Координат может не быть: у части морей и озёр P625 в
                # Wikidata отсутствует, но имя для карты всё равно нужно.
                # Раньше такой объект выбрасывался целиком — поэтому моря
                # с карты и пропадали из слоя названий.
                "lon": round(pt[0], 5) if pt else "",
                "lat": round(pt[1], 5) if pt else "",
                # Все варианты одной ячейкой через « | ». Отсюда вы берёте
                # нужное имя и переносите в epoch_name.
                "all_names": " | ".join(names[:24]),
                "ancient_name": "", "ancient_from": "", "ancient_to": "",
                "medieval_name": "", "medieval_from": "", "medieval_to": "",
                # epoch_* — то, что попадёт на карту этой эпохи.
                "epoch_name": "", "epoch_from": "", "epoch_to": "",
                "article": "",
                "note": "выберите из all_names то имя, которым водоём звали "
                        "в эту эпоху, и впишите в epoch_name вместе с "
                        "периодом. Wikidata даты имён не хранит",
                "source": f"Wikidata {qi} (CC0)",
            })
    log(f"    записано: {dst}")

    # Контроль: эти моря ОБЯЗАНЫ найтись. Если их нет — значит, обход по
    # иерархии классов сломался, и слой тихо потерял самое важное.
    control = [("Q166", "Чёрное море"), ("Q4918", "Средиземное море"),
               ("Q35367", "Мраморное море"), ("Q34575", "Эгейское море")]
    got = {u[0] for u in uniq}
    miss = [name for qi, name in control if qi not in got]
    if miss:
        log(f"    ! КОНТРОЛЬ НЕ ПРОЙДЕН: в слое нет «{', '.join(miss)}».")
        log(f"      Для античной карты это главные моря. Проверьте, что в")
        log(f"      CLASSES_WATERS у моря стоит walk=True (обход по подклассам).")
    else:
        log(f"    контроль пройден: Чёрное, Средиземное, Мраморное и Эгейское "
            f"моря в слое")

    # Контроль по обязательному списку: показываем, чего именно не хватает.
    # Это не ошибка программы, а список вашей ручной работы.
    if miss_ess:
        log(f"    ! из обязательного списка не найдено {len(miss_ess)}: "
            + ", ".join(miss_ess))
        log(f"      Проверьте написание или добавьте Q-номер вручную")
    return uniq


# ================================================================ DOCTOR ==

def cmd_doctor():
    """
    Проверка, что классы Wikidata живы и запрос вообще работает.

    Смысл отдельной команды: SPARQL-запрос с неверным Q-номером класса НЕ
    падает — он молча возвращает ноль строк. Именно так я в первый раз и
    попал: написал классы по памяти, получил пустой результат и мог бы решить,
    что в Wikidata нет ни одной эпидемии. Поэтому doctor сверяет каждый класс
    отдельно и ищет три контрольных объекта, которые обязаны найтись.
    """
    log("Проверка Wikidata")
    log("  1. Классы через wbsearchentities (быстрый API, лимиты мягкие):")
    want = [("Q44512", "эпидемия"), ("Q12184", "пандемия"),
            ("Q1261499", "морское сражение")] + CLASSES_WATERS
    for qi, expect in want:
        try:
            raw = _get(API, {"action": "wbgetentities", "ids": qi,
                             "props": "labels|claims", "format": "json"})
            ent = (json.loads(raw).get("entities") or {}).get(qi) or {}
            if ent.get("missing") == "":
                log(f"      ✗ {qi} НЕ СУЩЕСТВУЕТ — «{expect}» надо искать заново")
                continue
            en = ((ent.get("labels") or {}).get("en") or {}).get("value", "?")
            ru = ((ent.get("labels") or {}).get("ru") or {}).get("value", "—")
            log(f"      ✓ {qi:10s} {en[:26]:28s} / {ru[:24]}")
        except Exception as e:
            log(f"      ! {qi}: {e!r:.80}")
        time.sleep(1)

    log("")
    log("  2. Контрольные объекты (SPARQL, один запрос, ждите до минуты):")
    ids = " ".join(f"wd:{q}" for q in MUST_FIND)
    # Проверяем и координаты (P625), и поражённые регионы (P276): у пандемии
    # координат в Wikidata нет вообще, и это норма, а не поломка данных.
    # Достаточно, чтобы нашлось ХОТЬ ЧТО-ТО из двух — иначе привязать
    # эпидемию к карте нечем.
    q = f"""
SELECT ?item ?itemLabel ?coord ?start ?place WHERE {{
  VALUES ?item {{ {ids} }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?item wdt:P580 ?start }}
  OPTIONAL {{ ?item wdt:P585 ?start }}
  OPTIONAL {{ ?item wdt:{P_LOCATION} ?place }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
}}
""".strip()
    try:
        rows = sparql(q)
    except Exception as e:
        log(f"      ! SPARQL недоступен: {e!r:.90}")
        log("        Эпидемии и морские сражения собрать не получится,")
        log("        пока эндпоинт не ответит. Это не ошибка в ваших данных.")
        return 1
    got = {}
    places = {}
    for r in rows:
        qi = qid_of(r.get("item"))
        got.setdefault(qi, r)
        if r.get("place"):
            places.setdefault(qi, set()).add(qid_of(r["place"]))
    ok = True
    for qi, name in MUST_FIND.items():
        r = got.get(qi)
        if not r:
            log(f"      ✗ {qi} {name} НЕ НАЙДЕН")
            ok = False
            continue
        pt = parse_point(r.get("coord"))
        y = parse_year(r.get("start"))
        regs = sorted(places.get(qi, ()))
        how = (f"координаты есть" if pt else
               (f"регионов {len(regs)}: {', '.join(regs[:4])}" if regs else
                "НИ координат, НИ регионов"))
        log(f"      {'✓' if (pt or regs) else '✗'} {qi} {name:24s} "
            f"{how}   год {y if y is not None else 'нет'}")
        if not pt and not regs:
            log(f"        → привязать к карте нечем, слой будет пустым")
            ok = False
    log("")
    log("  ИТОГ: " + ("всё работает, можно собирать слои"
                        if ok else "есть проблемы — смотрите выше"))
    return 0 if ok else 1


# ============================================================== ВХОД =======

def usage():
    log(__doc__.split("Как пользоваться")[0].strip()[:400])
    log("")
    log("Команды:")
    log("  doctor                        проверить классы и доступ к Wikidata")
    log("  battles   <эпоха>             морские сражения → sea_battles.auto.csv")
    log("  epidemics <эпоха>             эпидемии       → geom/epidemics.geojson")
    log("  waters    <эпоха>             названия водоёмов → water_names.auto.csv")
    log("  all       <эпоха>             все три слоя подряд")
    log("")
    log("Доступные эпохи: "
        + ", ".join(sorted(d for d in os.listdir(ERAS)
                           if not d.startswith(("_", ".")))))
    return 2


def main(argv):
    if len(argv) < 2:
        return usage()
    cmd = argv[1].strip().lower()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd not in ("battles", "epidemics", "waters", "all"):
        log(f"неизвестная команда «{cmd}»")
        return usage()
    if len(argv) < 3:
        log("нужно имя эпохи, например:  battles rome117")
        return usage()
    era = load_era(argv[2].strip())
    log(f"Эпоха «{era['name_ru'] or era['id']}»  год {era['year']}  "
        f"окно {era['valid_from']}…{era['valid_to']}")
    log(f"  Пауза между запросами к Wikidata: {GAP} с — это нормально, не прерывайте.")
    log("")

    if cmd in ("battles", "all"):
        cmd_battles(era)
        if cmd == "all":
            log(f"  …ждём {GAP} с перед следующим запросом"); time.sleep(GAP)
    if cmd in ("epidemics", "all"):
        cmd_epidemics(era)
        if cmd == "all":
            log(f"  …ждём {GAP} с перед следующим запросом"); time.sleep(GAP)
    if cmd in ("waters", "all"):
        cmd_waters(era)

    log("")
    log("Готово. Дальше:")
    log(f"  1. cp maps/eras/{era['id']}/sea_battles.auto.csv "
        f"maps/eras/{era['id']}/sea_battles.csv")
    log(f"  2. cp maps/eras/{era['id']}/water_names.auto.csv "
        f"maps/eras/{era['id']}/water_names.csv")
    log("  3. дописать fleets_ru, outcome_ru, article и период у названий —")
    log("     этого Wikidata не знает")
    log("  4. python3 tools/build_map.py era " + era["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
