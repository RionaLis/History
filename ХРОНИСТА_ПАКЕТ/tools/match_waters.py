#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_waters.py — сопоставить исторические названия водоёмов с картой.

Задача
------
`tools/harvest_wikidata.py waters` собирает из Wikidata названия водоёмов:
современное русское, все варианты (включая исторические — «Euxinus» у Чёрного
моря, «Proponditis» у Мраморного, «Ellaspontus» у Дарданелл) и координаты.
Но сам по себе этот список на карту не ложится: надо понять, КАКОМУ объекту
на вашей карте какое имя соответствует.

Это и делает данный файл. Правило, которое вы задали:

    Понт Эвксинский = Чёрное море = Q166
    если не задана иная историческая геометрия — берётся Wikidata id.

То есть сопоставление идёт ПО Q-НОМЕРУ, а не по названию. Название — только
запасной путь, и каждый такой случай помечается на ручную проверку.

Почему по Q-номеру это работает
-------------------------------
Замерено 23.10.2026 на срезе 117 года н. э.: в слое гидрографии 645 объектов,
из них 600 — базовая гидрография Natural Earth, и **550 из 600 (92%) уже несут
поле wikidata**. Причём `prep_base.py` берёт его из атрибутов Natural Earth,
то есть это те же самые Q-номера Wikidata: Евфрат там Q34589 — ровно тот,
который harvest_wikidata.py нашёл по названию.

Отсюда три уровня доверия:

  точно      Q-номер совпал. Применять можно, проверять не нужно.
             Так находится большинство объектов.
  вероятно   Q-номера нет, но современное название совпало после
             нормализации («Чёрное море» = «Черное море»). ПОМЕЧАЕТСЯ
             на ручную проверку:同名ный приток или залив — частая ошибка.
  не найдено Ни Q-номера, ни совпадения имени. Остаётся пустым и попадает
             в список вашей ручной работы.

Что получается на выходе
------------------------
1. `geom/hydro.geojson` дописывается свойствами:
       hist_name         — имя для этой эпохи (если вы его задали)
       hist_names_all    — все известные варианты, через « | »
       hist_match        — точно | вероятно | не найдено
       hist_wikidata     — Q-номер, по которому совпало
       hist_note         — что именно сомнительно
   и, если совпадение не точное, добавляется пометка в `gap`.

2. `qgis/названия_водоёмов.md` — таблица сопоставлений в том виде, в каком
   вы её описали: историческое имя = современное = Q-номер, плюс уровень
   доверия и причина сомнения. Всё с уровнем «вероятно» и «не найдено»
   вынесено в начало — проверять нужно именно их.

3. `water_names.matched.csv` — то же самое машиночитаемым файлом.

Отдельная папка для ПЕРИОДОВ
----------------------------
Wikidata хранит названия плоским списком БЕЗ ДАТ. Она знает, что Чёрное море
звалось Euxinus, но не знает, в какие годы. Поэтому период вы задаёте сами,
в файле `maps/eras/<эпоха>/water_names_periods.csv`:

    wikidata,name_for_era,from,to,source
    Q166,Понт Эвксинский,-700,400,Страбон II.1; Плиний IV.24
    Q35367,Пропонтида,-700,1453,
    Q6514,Геллеспонт,-700,1453,
    Q1653,Данубий,-30,400,римская традиция

Строки из этого файла имеют ПРИОРИТЕТ над автоматикой: если вы указали имя
для эпохи, на карту пойдёт оно, а не первый попавшийся вариант из Wikidata.
Файл не обязателен — без него слой останется с полем hist_names_all, то есть
со всем списком вариантов, и вы будете выбирать прямо в QGIS.

Запуск
------
    python3 tools/match_waters.py rome117
    python3 tools/match_waters.py rome117 --dry    # ничего не писать, только показать
    python3 tools/match_waters.py --all            # все эпохи подряд
"""

import csv
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERAS = os.path.join(ROOT, "maps", "eras")

# Уровни доверия. Числа нужны только для сортировки в отчёте.
CONF_EXACT = "точно"          # совпал Q-номер
CONF_NAME = "вероятно"        # совпало нормализованное название
CONF_NONE = "не найдено"      # ничего не совпало
# Порядок сортировки в отчёте: самое тревожное первым.
# «расхождение Q» стоит выше «не найдено», потому что ненайденный объект
# просто пуст, а расхождение означает, что данные ПРОТИВОРЕЧАТ друг другу —
# на карте один Q-номер, в списке другой, и один из них неверен.
ORDER = {"расхождение Q": -1, CONF_NONE: 0, CONF_NAME: 1, CONF_EXACT: 2}

# ---------------------------------------------------------------------
# Слова-паразиты в названиях водоёмов. «Чёрное море» и «море Чёрное» — это
# один объект, «озеро Байкал» и «Байкал» — тоже. Без их отсечения сравнение
# имён не работает, и уровень «вероятно» почти не достигается.
STOPWORDS = {
    "море", "морской", "озеро", "река", "речка", "пролив", "залив", "бухта",
    "лиман", "водохранилище", "канал", "рукав", "дельта", "моря", "морем",
    "sea", "ocean", "lake", "river", "strait", "gulf", "bay", "lagoon",
    "canal", "reservoir", "mare", "meer", "mer", "see", "lac", "rio",
    "rivier", "fleuve", "flus", "fluss", "mar", "mare", "ozean", "deniz",
    "göl", "nehri", "çay", "potok", "jezero", "tenger", "hav", "sjö", "älv",
    "joki", "awa", "nadi", "jiang", "he", "nahr", "wadi", "oued", "nam",
}


def log(msg=""):
    print(msg, flush=True)


# ================================================= НОРМАЛИЗАЦИЯ ИМЁН =======

def norm_name(s):
    """
    Название водоёма → ключ для сравнения.

    Что делает и зачем:
      1. Приводит к нижнему регистру.
      2. Снимает диакритику: «Égeïsee» → «egeisee». Без этого латинские
         варианты одного моря никогда не совпадут.
      3. **Заменяет «ё» на «е»** — отдельным шагом, потому что NFD-разложение
         «ё» даёт «е» + combining diaeresis, и после снятия диакритики «ё»
         становится «е» само. Но «Чёрное» → «черное» должно совпасть с тем,
         как имя записали в Natural Earth, а там бывает и так и так.
      4. Выбрасывает слова-паразиты («море», «озеро», «river»…).
      5. Схлопывает пробелы и сортирует слова: порядок слов в разных языках
         разный, «море Чёрное» и «Чёрное море» должны дать один ключ.

    Результат — набор слов, а не строка, поэтому сравнение идёт по
    пересечению: это терпимо к лишнему слову, но не прощает подмену корня.
    """
    if not s:
        return frozenset()
    s = str(s).strip().lower().replace("ё", "е")
    # NFD раскладывает «é» в «e» + отдельный значок ударения, затем значки
    # категории Mn (Mark, Nonspacing) удаляются — диакритика снята.
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-zа-я0-9\s-]", " ", s)
    words = [w.strip("-") for w in s.split()]
    words = [w for w in words if w and w not in STOPWORDS and len(w) > 1]
    return frozenset(words)


def names_overlap(a, b):
    """
    Насколько названия похожи: доля общих слов в меньшем из наборов.

    Возвращает (доля, общие_слова). Доля 1.0 — один набор полностью вошёл
    в другой («Чёрное море» ⊂ «Чёрное море Азово-Черноморского бассейна»).
    Порог совпадения задан в match_one и намеренно высокий.
    """
    if not a or not b:
        return 0.0, set()
    common = a & b
    if not common:
        return 0.0, set()
    return len(common) / min(len(a), len(b)), common


# ======================================================= ЧТЕНИЕ ФАЙЛОВ ====

def read_water_names(era_dir):
    """
    water_names.csv (ваш, с правками) или water_names.auto.csv (заготовка).

    Приоритет у water_names.csv: если вы завели рабочий файл, автоматическая
    заготовка больше не используется. Это общее правило всего проекта —
    *.auto.csv перезаписывается при каждом запуске harvest, ваши правки
    живут в файле без суффикса.
    """
    for fn in ("water_names.csv", "water_names.auto.csv"):
        path = os.path.join(era_dir, fn)
        if os.path.exists(path):
            rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
            return rows, fn
    return [], None


def read_periods(era_dir):
    """
    water_names_periods.csv — ВАШЕ решение о том, какое имя к какой эпохе.

    Файл не обязателен. Колонки: wikidata, name_for_era, from, to, source.
    Строки отсюда имеют приоритет над автоматикой.
    """
    path = os.path.join(era_dir, "water_names_periods.csv")
    if not os.path.exists(path):
        return {}, None
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        wd = (r.get("wikidata") or "").strip()
        if not wd:
            continue
        out[wd] = {
            "name": (r.get("name_for_era") or "").strip(),
            "from": (r.get("from") or "").strip(),
            "to": (r.get("to") or "").strip(),
            "source": (r.get("source") or "").strip(),
        }
    return out, os.path.basename(path)


# ========================================================= СОПОСТАВЛЕНИЕ ==

def build_indexes(water_rows):
    """
    Два индекса по списку водоёмов из Wikidata: по Q-номеру и по имени.

    Индекс по имени нужен только для запасного пути, когда у объекта на карте
    нет wikidata. Он намеренно хранит ВСЕ варианты названий объекта, а не
    только современное русское: тогда «Euxinus» на карте (если вы его уже
    вписали куда-то руками) тоже найдёт своё море.
    """
    by_qid, by_name = {}, {}
    for r in water_rows:
        qi = (r.get("wikidata") or "").strip()
        if not qi:
            continue
        by_qid[qi] = r
        variants = [r.get("name_modern_ru", "")]
        variants += (r.get("all_names") or "").split(" | ")
        for v in variants:
            key = norm_name(v)
            if key:
                # При совпадении ключей оставляем первого: порядок в файле —
                # моря, проливы, заливы, океаны, реки, озёра, то есть более
                # важные классы раньше.
                by_name.setdefault(key, []).append(qi)
    return by_qid, by_name


def match_one(props, by_qid, by_name):
    """
    Сопоставить один объект на карте со списком Wikidata.

    Порядок проверки именно такой, и менять его нельзя:

      1. Q-номер. Если у объекта есть wikidata и он есть в списке — это
         точное совпадение. Никакой двусмысленности: Q166 — это Чёрное море,
         и ничто другое им быть не может.
      2. Современное русское имя (name_ru), нормализованное. Уровень
         «вероятно»: одноимённых рек и заливов в мире много, поэтому случай
         помечается на проверку.
      3. Латинское и местное имя (name_en, name_local). Тоже «вероятно»,
         но порог выше: латинские названия короче и чаще совпадают случайно.
      4. Ничего. «не найдено».

    Возвращает (уровень, Q-номер, причина).
    """
    qi = (props.get("wikidata") or "").strip()
    if qi and qi in by_qid:
        return CONF_EXACT, qi, f"Q-номер {qi} совпал напрямую"

    nm_ru = props.get("name_ru") or ""
    if nm_ru:
        key = norm_name(nm_ru)
        # Ищем и по частичному совпадению набора слов. Реальный случай:
        # на карте лежало «Дніпро» (украинское написание из Natural Earth),
        # а в списке Wikidata — «Днепр». Точное совпадение их не видело,
        # и объект уходил в «не найдено».
        #
        # Порог намеренно высокий: все слова короткого имени должны найтись
        # в длинном. Ниже опускать нельзя — иначе «Северный Дон» совпал бы
        # с «Дон».
        cand_keys = [key] + [k for k in by_name
                             if k != key and len(k & key) >= max(1, len(key) - 1)]
        for k in cand_keys:
            for cand in by_name.get(k, []):
                how = "совпало" if k == key else "совпало частично"
                return CONF_NAME, cand, (f"{how} русское имя «{nm_ru}»; "
                                         f"Q-номера у объекта нет — проверьте")

    for field in ("name_en", "name_local"):
        nm = props.get(field) or ""
        if not nm:
            continue
        key = norm_name(nm)
        if len(key) < 2:
            # Однословные латинские имена («Don», «Nil», «Tigr») совпадают
            # слишком легко: Don есть и в Англии, и в Ирландии, и во Франции.
            continue
        for cand in by_name.get(key, []):
            return CONF_NAME, cand, (f"совпало {field}=«{nm}»; Q-номера у объекта нет — "
                                     f"одноимённые водоёмы часты, проверьте")

    return CONF_NONE, "", "ни Q-номера, ни совпадения имени"


def pick_variant(row):
    """
    Кандидаты на имя эпохи — УПОРЯДОЧЕННЫЙ СПИСОК, а не решение.

    Поле `hist_name` эта функция НЕ заполняет. Заполняете вы, в файле
    `water_names_periods.csv`.

    Почему. Первая версия угадывала «древнейшее на вид» имя по форме слова и
    попала впросак на каждом сколько-нибудь важном объекте:

        Евфрат   → «Eufrates»              (испанский, а не латынь)
        Янцзы    → «Karayan Yangtze»       (тагальский)
        Иордан   → «Abhainn na hIordáine»  (ирландский)
        Тигр     → «Kali Tigris»           (индонезийский)
        Днепр    → «Dnièpre»               (французская транскрипция)

    Все пять — настоящие названия объекта из Wikidata, и все пять бесполезны
    на карте римской эпохи. Правильных ответов («Euphrates», «Tigris»,
    «Danubius», «Borysthenes») в списке либо нет вовсе, либо они не отличимы
    от испанского по форме слова: Wikidata хранит названия плоским списком
    без дат, поэтому выбрать исторически верное автоматикой нельзя в принципе.

    Неверное имя на карте хуже пустого. Пустое вы заметите и заполните,
    а «Eufrates» останется и уедет в платный продукт.

    Порядок в списке помогает читать отчёт, но ничего не решает за вас:
    сначала латиница и греческий (исторические имена античности почти всегда
    записаны ими), затем прочие, современное русское исключено — оно и так
    видно на карте.
    """
    modern = (row.get("name_modern_ru") or "").strip()
    variants = [v.strip() for v in (row.get("all_names") or "").split(" | ") if v.strip()]
    others = [v for v in variants if v != modern]
    lat = [v for v in others if re.search(r"[A-Za-z]", v) and not re.search(r"[а-яА-Я]", v)]
    rest = [v for v in others if v not in lat]
    return lat + rest


# ========================================================= СОПОСТАВЛЕНИЕ ==

def build_indexes(water_rows):
    """
    Два индекса по списку водоёмов из Wikidata: по Q-номеру и по имени.

    Индекс по имени нужен только для запасного пути, когда у объекта на карте
    нет wikidata. Он намеренно хранит ВСЕ варианты названий объекта, а не
    только современное русское: тогда «Euxinus» на карте (если вы его уже
    вписали куда-то руками) тоже найдёт своё море.
    """
    by_qid, by_name = {}, {}
    for r in water_rows:
        qi = (r.get("wikidata") or "").strip()
        if not qi:
            continue
        by_qid[qi] = r
        variants = [r.get("name_modern_ru", "")]
        variants += (r.get("all_names") or "").split(" | ")
        for v in variants:
            key = norm_name(v)
            if key:
                # При совпадении ключей оставляем первого: порядок в файле —
                # моря, проливы, заливы, океаны, реки, озёра, то есть более
                # важные классы раньше.
                by_name.setdefault(key, []).append(qi)
    return by_qid, by_name


def match_one(props, by_qid, by_name):
    """
    Сопоставить один объект на карте со списком Wikidata.

    Порядок проверки именно такой, и менять его нельзя:

      1. Q-номер. Если у объекта есть wikidata и он есть в списке — это
         точное совпадение. Никакой двусмысленности: Q166 — это Чёрное море,
         и ничто другое им быть не может.
      2. Современное русское имя (name_ru), нормализованное. Уровень
         «вероятно»: одноимённых рек и заливов в мире много, поэтому случай
         помечается на проверку.
      3. Латинское и местное имя (name_en, name_local). Тоже «вероятно»,
         но порог выше: латинские названия короче и чаще совпадают случайно.
      4. Ничего. «не найдено».

    Возвращает (уровень, Q-номер, причина).
    """
    qi = (props.get("wikidata") or "").strip()
    if qi and qi in by_qid:
        return CONF_EXACT, qi, f"Q-номер {qi} совпал напрямую"

    nm_ru = props.get("name_ru") or ""
    if nm_ru:
        key = norm_name(nm_ru)
        # Порог 1.0 = все слова короткого названия найдены в длинном.
        # Ниже опускать нельзя: при 0.5 «Чёрное море» совпало бы с
        # «Жёлтое море» по одному слову «море» — но «море» и так в
        # STOPWORDS, поэтому реальная опасность в другом: «Северный Дон»
        # и «Дон» совпали бы наполовину.
        for cand in by_name.get(key, []):
            return CONF_NAME, cand, f"совпало русское имя «{nm_ru}»; Q-номера у объекта нет — проверьте"

    for field in ("name_en", "name_local"):
        nm = props.get(field) or ""
        if not nm:
            continue
        key = norm_name(nm)
        if len(key) < 2:
            # Однословные латинские имена («Don», «Nil», «Tigr») совпадают
            # слишком легко: Don есть и в Англии, и в Ирландии, и во Франции.
            continue
        for cand in by_name.get(key, []):
            return CONF_NAME, cand, (f"совпало {field}=«{nm}»; Q-номера у объекта нет — "
                                     f"одноимённые водоёмы часты, проверьте")

    return CONF_NONE, "", "ни Q-номера, ни совпадения имени"


def best_variant(row, era_year):
    """
    Какое имя из списка Wikidata показать на карте, если вы не задали своё.

    ЧЕСТНО: Wikidata не хранит привязки имён к датам, поэтому «лучшего»
    варианта по эпохе выбрать нельзя. Здесь берётся древнейшее на вид имя —
    то, что записано латиницей или греческим и не является современным
    русским. Это ДОГАДКА, и она всегда помечается: если у объекта уже задано
    имя в water_names_periods.csv, оно побеждает, а догадка не используется.
    """
    modern = (row.get("name_modern_ru") or "").strip()
    variants = [v.strip() for v in (row.get("all_names") or "").split(" | ") if v.strip()]
    # Современное русское имя исключаем: оно и так есть на карте.
    variants = [v for v in variants if v != modern]
    if not variants:
        return "", "других названий в Wikidata нет"
    # Предпочитаем латиницу и греческий: исторические имена античных водоёмов
    # почти всегда записаны ими. Кириллические варианты — это обычно переводы
    # на современные славянские языки, а не исторические имена.
    for v in variants:
        if re.search(r"[A-Za-z]", v) and not re.search(r"[а-яА-Я]", v):
            if re.search(r"(us|os|on|um|is|es|a$|e$)", v, re.I):
                return v, "догадка по форме имени: похоже на античное"
    for v in variants:
        if re.search(r"[A-Za-z]", v) and not re.search(r"[а-яА-Я]", v):
            return v, "догадка: первый латинский вариант"
    return variants[0], "догадка: первый вариант из списка"


# ===================================================== ПОДПИСИ МОРЕЙ =====

# Классы Wikidata, которые означают АКВАТОРИЮ, а не водоток или озеро.
# Только для них создаются подписи: река уже нарисована линией, озеро —
# полигоном, а море не нарисовано ничем.
SEA_CLASSES = {"море", "внутреннее море", "пролив", "залив", "бухта", "океан",
               "sea", "adjacent sea", "strait", "gulf", "bay", "ocean",
               "обязательный", "с карты", ""}

# Имена собственные проливов и морей, в которых НЕТ опознавательного слова.
# «Дарданеллы», «Босфор», «Сунду», «Эресунн» — это проливы, но ни корня
# «пролив», ни «strait» в их названиях нет, поэтому определение по слову
# их пропускает. Замерено: из-за этого ваши Геллеспонт и Боспор Фракийский
# не легли на карту, хотя Q-номера и координаты были на месте.
# Список пополняйте по своим эпохам.
SEA_PROPER_NAMES = {
    "дарданеллы", "босфор", "эресунн", "сунду", "каттегат", "скагеррак",
    "пролив босфор", "боспор", "киммерийский", "лаперуза", "торреса",
    "магелланов", "гибралтар", "пролив отранто", "бонифачо", "мессинский",
    "керченский", "пролив джорджа", "минданао", "тайваньский", "юнго",
    "босфор восточный", "геллеспонт",
}


def add_sea_labels(d, water_rows, periods, per_src):
    """
    Создать подписи морей и проливов — их на карте больше нечем показать.

    Замерено 23.10.2026: в слое гидрографии эпохи 117 года 645 объектов
    (319 LineString, 182 MultiLineString, 143 Polygon, 1 MultiPolygon) — и
    НИ ОДНОГО моря. Не найдено Чёрное, Средиземное, Мраморное, Эгейское,
    Азовское, Каспийское, Балтийское, Красное. В maps/base/lakes-50m.geojson
    из 412 объектов «Black» встречается один раз, «Mediterranean» — ноль,
    «Caspian» и «Baltic» — ноль.

    Причина не в ошибке, а в устройстве Natural Earth: это данные СУШИ.
    Море там — пустое место между береговыми линиями, отдельного полигона
    «Чёрное море» в них нет и не будет. Поэтому ваше правило
    «Понт Эвксинский = Чёрное море = Q166» сопоставлялось корректно, но
    привязать имя было не к чему.

    Здесь создаются ТОЧКИ-подписи: координаты берутся из P625 того же
    объекта Wikidata (у Чёрного моря это 34.26, 43.41), имя — из вашего
    water_names_periods.csv, а если вы его не задали, поле остаётся пустым
    и объект помечается на проверку. Полигон моря при этом по-прежнему
    рисуется сам — цветом воды из базовой карты; подпись просто встаёт
    поверх него в нужном месте.

    Возвращает число добавленных подписей.
    """
    have = {str((f.get("properties") or {}).get("hist_wikidata") or "")
            for f in d.get("features", [])}
    have |= {str((f.get("properties") or {}).get("wikidata") or "")
             for f in d.get("features", [])}

    added = 0
    for r in water_rows:
        cls = (r.get("class_ru") or "").strip().lower()
        # Класс может быть неизвестен: у объектов, добытых по Q-номеру с карты
        # или из обязательного списка, он записывается не всегда. Тогда
        # определяем акваторию по названию — это надёжно, потому что слово
        # «море» или «пролив» в русском имени водоёма случайным не бывает.
        if cls not in SEA_CLASSES or cls in ("обязательный", "с карты", ""):
            nm = (r.get("name_modern_ru") or "") + " " + (r.get("all_names") or "")
            low = nm.lower()
            # Сначала имя собственное, потом опознавательное слово.
            proper = next((w for w in SEA_PROPER_NAMES if w in low), "")
            guess = proper or next((w for w in ("море", "пролив", "залив", "бухта",
                                                "океан", "sea", "strait", "gulf",
                                                "bay", "ocean") if w in low), "")
            if not guess:
                continue
            if proper and not any(w in low for w in ("море", "пролив", "залив",
                                                     "sea", "strait")):
                # Имя собственное без родового слова: Дарданеллы, Босфор.
                # Относим к проливам — почти все такие объекты проливы.
                cls = "пролив"
            cls = {"море": "море", "sea": "море", "пролив": "пролив",
                   "strait": "пролив", "залив": "залив", "gulf": "залив",
                   "бухта": "бухта", "bay": "бухта", "океан": "океан",
                   "ocean": "океан"}[guess]
        qi = (r.get("wikidata") or "").strip()
        if not qi or qi in have:
            continue
        lon = (r.get("lon") or "").strip()
        lat = (r.get("lat") or "").strip()
        if not lon or not lat:
            continue
        try:
            lon, lat = float(lon), float(lat)
        except ValueError:
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue

        per = periods.get(qi) or {}
        hist = (per.get("name") or "").strip()
        cands = [v.strip() for v in (r.get("all_names") or "").split(" | ") if v.strip()]
        cands = [v for v in cands if v != (r.get("name_modern_ru") or "")]

        if hist:
            note = f"задано вами в {per_src}"
            gap = ""
            status = "ok"
        else:
            note = ("имя для эпохи не задано — выберите из кандидатов и впишите "
                    "в water_names_periods.csv")
            gap = f"акватория {cls}: имя для эпохи не задано"
            status = "needs-review"

        d["features"].append({
            "type": "Feature",
            "properties": {
                "wikidata": qi,
                "hist_wikidata": qi,
                "name_ru": r.get("name_modern_ru", ""),
                "name_en": "",
                "name_local": "",
                "kind": "water" if cls in ("море", "внутреннее море", "океан") else cls,
                "water_class": cls,
                "status": status,
                "start": "", "end": "",
                "color": "#7fa8c9",
                # Подпись акватории видна уже на средних зумах: море занимает
                # пол-экрана, и прятать его имя до z6 смысла нет.
                "label_z_min": 3,
                "z_min": 3,
                "hist_name": hist,
                "hist_candidates": " | ".join(cands[:12]),
                "hist_names_all": r.get("all_names", ""),
                "hist_match": "точно",
                "hist_modern_ru": r.get("name_modern_ru", ""),
                "hist_note": note,
                "hist_source": per.get("source", ""),
                "hist_label": True,
                "gap": gap,
                "source": f"Wikidata {qi} (CC0), подпись акватории",
                "note": f"Подпись {cls}. Полигон моря рисуется цветом воды базовой "
                        f"карты: в Natural Earth моря как объекта нет вовсе",
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })
        have.add(qi)
        added += 1
    return added


# ================================================================ РАБОТА ==

def process_era(era_id, dry=False):
    era_dir = os.path.join(ERAS, era_id)
    hyd_path = os.path.join(era_dir, "geom", "hydro.geojson")
    if not os.path.isdir(era_dir):
        log(f"  ✗ нет эпохи {era_id}")
        return None
    if not os.path.exists(hyd_path):
        log(f"  ✗ нет geom/hydro.geojson — сначала соберите срез эпохи:")
        log(f"      python3 tools/extract_era.py ohm {era_id} --overpass")
        return None

    water_rows, water_src = read_water_names(era_dir)
    if not water_rows:
        log(f"  ✗ нет water_names.csv — сначала соберите названия:")
        log(f"      python3 tools/harvest_wikidata.py waters {era_id}")
        return None

    periods, per_src = read_periods(era_dir)
    by_qid, by_name = build_indexes(water_rows)

    era_year = None
    yml = os.path.join(era_dir, "era.yml")
    if os.path.exists(yml):
        for line in open(yml, encoding="utf-8"):
            if line.startswith("year:"):
                try:
                    era_year = int(line.split(":", 1)[1].split("#")[0].strip())
                except ValueError:
                    pass

    log(f"  водоёмов из Wikidata: {len(by_qid)}  (файл {water_src})")
    if per_src:
        log(f"  ваших периодов задано: {len(periods)}  (файл {per_src})")
    else:
        log(f"  water_names_periods.csv нет — поле hist_name останется пустым:")
        log(f"    Wikidata не хранит дат у названий, угадывать нельзя. Список")
        log(f"    кандидатов будет в отчёте и в свойстве hist_candidates")

    d = json.load(open(hyd_path, encoding="utf-8"))
    feats = d.get("features", [])

    stat = {CONF_EXACT: 0, CONF_NAME: 0, CONF_NONE: 0}
    changed = 0
    review = []
    for f in feats:
        p = f.get("properties") or {}
        # Гидрография без имени сопоставлять не с чем
        if not (p.get("wikidata") or p.get("name_ru") or p.get("name_en")):
            continue
        conf, qi, why = match_one(p, by_qid, by_name)
        stat[conf] += 1
        if conf == CONF_NONE:
            review.append({"conf": conf, "qi": "", "why": why,
                           "map_name": p.get("name_ru") or p.get("name_en") or "",
                           "map_wd": p.get("wikidata") or "",
                           "hist": "", "all": "", "src": ""})
            continue

        row = by_qid.get(qi, {})

        # РАСХОЖДЕНИЕ Q-НОМЕРОВ — самый опасный тихий случай.
        #
        # Замерено на Днепре 23.10.2026. На карте объект лежал с
        # wikidata=Q40855 — это РЕКА Днепр, и в её алиасах есть «Борисфен»,
        # «Borysthenes», «Βορυσθένης», ровно то, что нужно. А в моём списке
        # обязательных водоёмов был Q48256 — это ГОРОД Днепр. Сопоставление
        # по имени «Днепр» сработало, уровень «вероятно», всё выглядело
        # пристойно, но период «Борисфен» привязался бы к городу.
        #
        # Поэтому: если у объекта на карте Q-номер есть и он НЕ равен тому,
        # по которому совпало, — это отдельная пометка, важнее уровня.
        map_wd = (p.get("wikidata") or "").strip()
        qid_clash = bool(map_wd) and map_wd != qi

        # 1. Ваше решение имеет приоритет над любой автоматикой.
        per = periods.get(qi)
        if per and per.get("name"):
            hist, hist_why = per["name"], f"задано вами в {per_src}"
            src = per.get("source", "")
        else:
            # Имя для эпохи НЕ УГАДЫВАЕТСЯ. Поле остаётся пустым, кандидаты
            # кладутся рядом. См. pick_variant — там примеры провальных догадок.
            hist = ""
            hist_why = ("имя для эпохи не задано — выберите из кандидатов "
                        "и впишите в water_names_periods.csv")
            src = ""

        p["hist_name"] = hist
        p["hist_candidates"] = " | ".join(pick_variant(row)[:12])
        p["hist_names_all"] = row.get("all_names", "")
        p["hist_match"] = conf
        p["hist_wikidata"] = qi
        p["hist_modern_ru"] = row.get("name_modern_ru", "")
        p["hist_note"] = hist_why
        if src:
            p["hist_source"] = src

        # На проверку уходит: (а) расхождение Q-номеров, (б) всё, что не
        # «точно», и (в) всё, где имя для эпохи так и не задано — даже при
        # точном совпадении Q-номера. Точное совпадение означает, что мы
        # знаем, ЧТО это за водоём, но не значит, что знаем, как его звали
        # в 117 году.
        if qid_clash:
            flag = (f"РАСХОЖДЕНИЕ Q-НОМЕРОВ: на карте объект помечен {map_wd}, "
                    f"а сопоставление нашло {qi} «{row.get('name_modern_ru','')}». "
                    f"Одно из двух неверно — сверьтесь с Wikidata. Так бывает "
                    f"у тёзок: река и город с одинаковым названием")
            p["hist_qid_clash"] = f"{map_wd} != {qi}"
        elif conf != CONF_EXACT or not hist:
            flag = f"название водоёма сопоставлено как «{conf}»: {why}"
        else:
            flag = ""
        if flag:
            g = (p.get("gap") or "").strip("; ")
            p["gap"] = (g + "; " if g else "") + flag
            p["status"] = "needs-review"
            review.append({"conf": ("расхождение Q" if qid_clash else conf),
                           "qi": qi, "why": (flag or why),
                           "map_name": p.get("name_ru") or p.get("name_en") or "",
                           "map_wd": p.get("wikidata") or "",
                           "hist": hist, "all": p.get("hist_candidates", ""),
                           "src": src or hist_why})
            changed += 1
        else:
            changed += 1

    log(f"  объектов гидрографии сопоставлено: "
        f"{stat[CONF_EXACT]} точно, {stat[CONF_NAME]} вероятно, "
        f"{stat[CONF_NONE]} не найдено")

    # Моря и проливы: в Natural Earth их нет, поэтому подписи создаются.
    n_sea = add_sea_labels(d, water_rows, periods, per_src or "water_names_periods.csv")
    if n_sea:
        with_name = sum(1 for f in d["features"]
                        if f["properties"].get("hist_label") and f["properties"].get("hist_name"))
        log(f"  добавлено подписей акваторий: {n_sea}  (из них с вашим именем: {with_name})")
        log(f"    в Natural Earth моря нет вовсе — это не ошибка, а устройство")
        log(f"    источника: там суша, а море получается пустым местом между")
        log(f"    берегами. Подпись ставится в точку из P625 объекта Wikidata")
    else:
        log(f"  подписей акваторий не добавлено: нет координат у объектов класса море/пролив")

    if dry:
        log("  (--dry: файлы не менялись)")
        write_report(era_dir, era_id, review, stat, water_src, per_src, dry=True)
        return stat

    # --- записываем слой ---------------------------------------------------
    with open(hyd_path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    log(f"  ✓ {os.path.relpath(hyd_path, ROOT)}  (свойства дописаны у {changed})")

    write_report(era_dir, era_id, review, stat, water_src, per_src)
    write_matched_csv(era_dir, era_id, review)
    return stat


def write_report(era_dir, era_id, review, stat, water_src, per_src, dry=False):
    """
    Отчёт в том виде, который вы описали:
        историческое имя = современное = Q-номер
    Сомнительное — в начале, потому что проверять нужно именно его.
    """
    qdir = os.path.join(era_dir, "qgis")
    os.makedirs(qdir, exist_ok=True)
    path = os.path.join(qdir, "названия_водоёмов.md")

    review.sort(key=lambda r: (ORDER.get(r["conf"], 0), r["map_name"]))
    L = []
    A = L.append
    A(f"# Исторические названия водоёмов — эпоха {era_id}")
    A("")
    A(f"Файл создан `tools/match_waters.py`. Источник имён: `{water_src}`"
      + (f", ваши периоды: `{per_src}`." if per_src else
         "; файл периодов `water_names_periods.csv` не задан, имена для эпохи — догадка."))
    A("")
    A("Правило сопоставления, которое вы задали:")
    A("")
    A("    Понт Эвксинский = Чёрное море = Q166")
    A("    если не задана иная историческая геометрия — берётся Wikidata id.")
    A("")
    A("То есть совпадение ищется **по Q-номеру**. Название — только запасной")
    A("путь, и он всегда помечается как сомнительный.")
    A("")
    A("| Уровень | Объектов | Что это значит |")
    A("|---|---:|---|")
    A(f"| **точно** | {stat[CONF_EXACT]} | Q-номер совпал — известно, ЧТО это за водоём |")
    A(f"| **вероятно** | {stat[CONF_NAME]} | Q-номера нет, совпало имя. **Проверьте** |")
    A(f"| **не найдено** | {stat[CONF_NONE]} | Ничего не совпало. Нужна ручная работа |")
    A("")
    A("> Счётчик — это **объекты в слое**, а не уникальные водоёмы: Natural Earth")
    A("> режет длинные реки на сегменты, поэтому Евфрат встречается несколько раз.")
    A("> Имя эпохи задаётся один раз — в `water_names_periods.csv`, по Q-номеру.")
    A("")
    A("### Важное про уровень «точно»")
    A("")
    A("Точное совпадение Q-номера означает, что известно, **что это за водоём**.")
    A("Оно НЕ означает, что известно, **как его звали в эту эпоху**: Wikidata")
    A("хранит названия плоским списком без дат. Поэтому `hist_name` остаётся")
    A("пустым, пока не заполнен `water_names_periods.csv`. Кандидаты для выбора")
    A("— в таблице ниже и в свойстве `hist_candidates` каждого объекта.")
    A("")
    if not review:
        A("Сомнительных и ненайденных нет — проверять нечего.")
        A("")
    else:
        A("## Проверить вручную")
        A("")
        A("Сортировка: сначала то, что не нашлось вовсе, затем сопоставленное")
        A("по имени. Точные совпадения сюда не попадают.")
        A("")
        A("| Уровень | На карте | Q на карте | = | Имя эпохи | = Q | Кандидаты из Wikidata |")
        A("|---|---|---|---|---|---|---|")
        shown = set()
        for r in review:
            # Сегменты одной реки не дублируем: имя задаётся на Q-номер,
            # а не на каждый кусок русла. Иначе Евфрат занял бы пять строк.
            key = (r["qi"] or r["map_name"], r["conf"])
            if key in shown:
                continue
            shown.add(key)
            cands = (r["all"] or "").replace("|", " · ")
            if len(cands) > 76:
                cands = cands[:73] + "…"
            A(f"| {r['conf']} | {r['map_name'][:26]} | {r['map_wd'] or '—'} | = | "
              f"{r['hist'][:24] or '—'} | {r['qi'] or '—'} | {cands or '—'} |")
        A("")
        A("### Почему помечено")
        A("")
        seen = set()
        for r in review:
            if r["why"] in seen:
                continue
            seen.add(r["why"])
            A(f"- {r['why']}")
        A("")
    A("## Как исправить")
    A("")
    A("**Если сопоставление неверное** (например, «Дон» совпал с английской")
    A("рекой Don) — впишите правильный Q-номер в поле `wikidata` объекта")
    A("прямо в QGIS, либо в `geom/hydro.geojson`. При следующем запуске")
    A("совпадение станет точным.")
    A("")
    A("**Если историческое имя не то** — заведите `water_names_periods.csv`:")
    A("")
    A("```csv")
    A("wikidata,name_for_era,from,to,source")
    A("Q166,Понт Эвксинский,-700,400,Страбон II.1; Плиний IV.24")
    A("Q35367,Пропонтида,-700,1453,")
    A("Q6514,Геллеспонт,-700,1453,")
    A("Q1653,Данубий,-30,400,римская традиция")
    A("```")
    A("")
    A("Строки из этого файла имеют приоритет над автоматикой: указанное вами")
    A("имя попадёт в `hist_name` и на карту, а догадка использоваться не будет.")
    A("Колонка `source` — необязательна, но для платного продукта нужна:")
    A("это ваше доказательство, что имя взято не с потолка.")
    A("")
    A("После правок пересоберите:")
    A("")
    A("```bash")
    A(f"python3 tools/match_waters.py {era_id}")
    A(f"python3 tools/build_map.py era {era_id}")
    A("```")
    A("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    tag = " (не записан, --dry)" if dry else ""
    log(f"  ✓ отчёт: {os.path.relpath(path, ROOT)}{tag}")


def write_matched_csv(era_dir, era_id, review):
    path = os.path.join(era_dir, "water_names.matched.csv")
    cols = ["confidence", "map_name", "map_wikidata", "hist_name",
            "matched_wikidata", "candidates", "why"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in review:
            w.writerow({"confidence": r["conf"], "map_name": r["map_name"],
                        "map_wikidata": r["map_wd"], "hist_name": r["hist"],
                        "matched_wikidata": r["qi"], "candidates": r["all"],
                        "why": r["why"]})


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    dry = "--dry" in argv
    if "--all" in argv:
        ids = sorted(d for d in os.listdir(ERAS)
                     if not d.startswith(("_", ".")) and
                     os.path.isdir(os.path.join(ERAS, d)))
    elif args:
        ids = args
    else:
        log(__doc__.split("Запуск")[0].strip()[:300])
        log("")
        log("Запуск:")
        log("  python3 tools/match_waters.py <эпоха>")
        log("  python3 tools/match_waters.py --all")
        log("")
        log("Доступные эпохи: " + ", ".join(
            sorted(d for d in os.listdir(ERAS) if not d.startswith(("_", ".")))))
        return 2

    rc = 0
    for eid in ids:
        log(f"Эпоха {eid}")
        r = process_era(eid, dry=dry)
        if r is None:
            rc = 1
        log("")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
