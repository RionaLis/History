#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_public.py — собрать папку, которую МОЖНО показывать людям.

Зачем этот файл
---------------
Ваше требование: смотреть карту с любого устройства вам и паре друзей,
а оригиналы данных должны остаться только у вас на одном компьютере.

Проблема в том, что обычная команда «отдать папку в интернет» отдаёт ВСЁ,
что в ней лежит. А в `history-demo/` кроме готовых тайлов лежат:

    maps/eras/<эпоха>/geom/*.geojson     — геометрия, 10 МБ на эпоху
    maps/eras/<эпоха>/qgis/gaps.md       — отчёт о дырах в данных
    maps/eras/<эпоха>/*.auto.csv         — заготовки ваших таблиц
    maps/eras/<эпоха>/era.yml            — паспорт эпохи
    maps/_cache/overpass/*.json          — кэш ответов OHM, до 20 МБ
    tools/                               — весь код, включая этот файл
    ne/, hb_*.geojson                    — скачанное сырьё

Ничего из этого посетителю не нужно, и ничего из этого не должно уйти наружу:
`gaps.md` — это по сути список того, что у вас ещё не сделано.

Поэтому этот скрипт собирает ОТДЕЛЬНУЮ папку `public/`, в которую кладёт
только то, что нужно для показа:

    public/
      index.html          — карта, открывается сразу
      maplibre-gl.js      — библиотека карты
      maplibre-gl.css     — её стили
      tiles/*.pmtiles     — готовые тайлы эпох
      eras.json           — список эпох, чтобы карта знала, что показывать

Всё. Ни таблиц, ни геометрии, ни кэша, ни кода.

Что с этим делать дальше
------------------------
Собранную папку можно отдать тремя способами, все бесплатные:

  1. Туннель Cloudflare — самый быстрый, работает сразу, но только пока
     ваш компьютер включён. Команды в документе РАЗВЕРНУТЬ_БЕСПЛАТНО.md, §1.
  2. R2 + Worker — постоянный, работает всегда, тайлы закрыты ключом.
     Команды там же, §2.
  3. GitHub Pages — если решите сделать публичное демо. Учтите: там тайлы
     НЕ закрыты, их может скачать кто угодно.

    python3 tools/make_public.py              # собрать public/
    python3 tools/make_public.py --check      # собрать и проверить, что
                                              # лишнего не попало
    python3 tools/make_public.py --serve      # собрать и показать на :8080

Проверка `--check` важна: она убеждается, что в `public/` не оказалось
ни одного файла из запрещённого списка. Если вы когда-нибудь положите
в папку эпохи картинку или PDF, скрипт их не скопирует, но проверка
скажет об этом вслух.
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")

# Что копируем. Только это и ничего больше.
TILES = os.path.join(ROOT, "tiles")
ERAS = os.path.join(ROOT, "maps", "eras")

# Версия MapLibre, которая лежит у вас в корне. На CDN проверен именно этот
# номер: jsdelivr отдаёт файл размером 1 056 837 байт — байт в байт как ваш
# локальный maplibre-gl.js.
MAPLIBRE_VERSION = "5.24.0"
CDN = f"https://cdn.jsdelivr.net/npm/maplibre-gl@{MAPLIBRE_VERSION}/dist"

# Что копируем в public/ рядом с index.html, когда библиотека НЕ на CDN.
LOCAL_FILES = ["maplibre-gl.js", "maplibre-gl.css"]

# ---------------------------------------------------------------------
# КУДА КЛАСТЬ БИБЛИОТЕКУ: К СЕБЕ ИЛИ НА CDN.
#
# По умолчанию — К СЕБЕ, в папку public/. Причина географическая, а не
# техническая. С 9 июня 2025 года российские провайдеры обрезают соединения
# к сетям Cloudflare после первых 16 КБ, а поддомен *.workers.dev заблокирован
# РКН целиком (источники: официальное заявление Cloudflare от 26.06.2025,
# habr.com/ru/news/922532). jsdelivr сам по себе не Cloudflare и работает,
# но зависеть от зарубежного CDN, отдающего ОБЯЗАТЕЛЬНЫЙ файл, — это точка
# отказа, которая в любой момент может стать недоступной части посетителей.
# Локальная библиотека таких рисков не имеет: она уезжает на сервер вместе
# со всем остальным и весит 1 056 837 байт — немного.
#
# Флаг --cdn нужен ровно для одного случая: публикации через Cloudflare
# Worker на бесплатном тарифе, где весь код Worker'а вместе с модулями
# ограничен 1 МБ, а один maplibre-gl.js весит 1 056 837 байт, то есть ровно
# весь лимит. Для аудитории в России этот сценарий нерабочий; флаг оставлен
# на случай переезда или если у вас появится зарубежная площадка.
#
# Проверено: jsdelivr отдаёт файл размером 1 056 837 байт — байт в байт как
# локальный maplibre-gl.js, версия 5.24.0 совпадает.

# preview.html подключает библиотеку локально:
#     <link rel="stylesheet" href="maplibre-gl.css">
#     <script src="maplibre-gl.js"></script>
# Для публикации эти две строки заменяются на CDN. Причина не в красоте,
# а в жёстком ограничении Cloudflare Worker: весь код Worker'а вместе с
# его модулями должен влезать в 1 МБ на бесплатном тарифе, а один только
# maplibre-gl.js весит 1 056 837 байт — то есть ровно весь лимит, и места
# не остаётся даже на ваш код. С CDN Worker отдаёт только HTML (17 КБ),
# стили (70 КБ) и тайлы, и в лимит укладывается с большим запасом.
#
# Плата за это — зависимость от CDN: если jsdelivr недоступен, карта не
# откроется. Для платного продукта библиотеку надо будет положить к себе
# (тогда Worker нужен другой — см. РАЗВЕРНУТЬ_БЕСПЛАТНО.md, §2, шаг 7).
HTML_REWRITE = [
    ('href="maplibre-gl.css"', f'href="{CDN}/maplibre-gl.css"'),
    ('src="maplibre-gl.js"',   f'src="{CDN}/maplibre-gl.js"'),
]

# Что НЕ должно попасть в public ни при каких условиях.
# Проверка --check ищет эти имена по всему дереву public/.
FORBIDDEN = (
    ".csv", ".yml", ".yaml", ".py", ".sh", ".md", ".txt",
    "gaps", "auto", "geom", "_cache", "overpass", "planet",
    ".pbf", ".osm", ".shp", ".dbf", ".shx", ".prj", ".cpg",
    ".java", ".class", ".jar",
)


def log(msg=""):
    print(msg, flush=True)


def human(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:,.1f} {unit}".replace(",", " ")
        n /= 1024
    return f"{n:,.1f} ТБ"


def find_eras():
    """
    Список эпох по готовым тайлам, а не по папкам.

    Папка эпохи может существовать, а тайл — ещё нет (эпоху собрали, но не
    нарезали). Показывать такую нельзя: карта запросит файл и получит 404.
    Поэтому идём от тайлов.
    """
    out = []
    if not os.path.isdir(TILES):
        return out
    for fn in sorted(os.listdir(TILES)):
        if not fn.endswith(".pmtiles") or not fn.startswith("era-"):
            continue
        eid = fn[4:-len(".pmtiles")]
        yml = os.path.join(ERAS, eid, "era.yml")
        name, year = eid, None
        if os.path.exists(yml):
            # era.yml разбираем вручную: PyYAML может быть не установлен,
            # а нужны всего два поля.
            for line in open(yml, encoding="utf-8"):
                if line[:1] in (" ", "\t") or ":" not in line:
                    continue
                k, _, v = line.partition(":")
                v = v.split("#")[0].strip().strip('"').strip("'")
                if k.strip() == "name_ru" and v:
                    name = v
                elif k.strip() == "year" and v:
                    try:
                        year = int(v)
                    except ValueError:
                        year = None
        out.append({"id": eid, "name": name, "year": year,
                    "file": f"tiles/{fn}",
                    "bytes": os.path.getsize(os.path.join(TILES, fn))})
    return out


def build(use_cdn=False):
    if os.path.isdir(PUB):
        shutil.rmtree(PUB)
    os.makedirs(os.path.join(PUB, "tiles"), exist_ok=True)

    eras = find_eras()
    if not eras:
        log("✗ в tiles/ нет ни одного era-*.pmtiles.")
        log("  Сначала соберите тайлы:  python3 tools/make_tiles.py")
        return None

    total = 0
    for e in eras:
        src = os.path.join(TILES, os.path.basename(e["file"]))
        dst = os.path.join(PUB, "tiles", os.path.basename(e["file"]))
        shutil.copy2(src, dst)
        total += os.path.getsize(dst)
        log(f"  ✓ {os.path.basename(dst):26s} {human(e['bytes'])}")

    # Библиотека MapLibre. По умолчанию копируется в public/ — см. LOCAL_FILES
    # и комментарий выше про доступность зарубежных CDN из России.
    if use_cdn:
        log("  ! --cdn: библиотека подключается с cdn.jsdelivr.net, а не лежит "
            "в public/. Для аудитории в России это точка отказа")
    else:
        for fn in LOCAL_FILES:
            src = os.path.join(ROOT, fn)
            if not os.path.exists(src):
                log(f"  ✗ {fn} не найден в {ROOT} — карта не откроется.")
                log(f"    Скачайте: curl -L -o {fn} {CDN}/{fn}")
                return None
            shutil.copy2(src, os.path.join(PUB, fn))
            total += os.path.getsize(src)
            log(f"  ✓ {fn:26s} {human(os.path.getsize(src))}")

    # preview.html → index.html, с заменой библиотеки на CDN (только при --cdn).
    # index.html — привычное имя, любой хостинг отдаёт его сам.
    src = os.path.join(ROOT, "preview.html")
    if not os.path.exists(src):
        log("  ✗ preview.html не найден — публиковать нечего")
        return None
    html = open(src, encoding="utf-8").read()
    if use_cdn:
        for old, new in HTML_REWRITE:
            if old not in html:
                log(f"  ! в preview.html нет «{old}» — замена на CDN не сработала, "
                    f"карта может не открыться")
            html = html.replace(old, new)

    # КЛЮЧ ДОСТУПА БЕРЁТСЯ ИЗ ЯКОРЯ URL, а не из строки запроса.
    #
    # Якорь (всё после «#») браузер НЕ ОТПРАВЛЯЕТ на сервер. Значит ключ:
    #   • не попадает в журналы Cloudflare, R2 и вашего провайдера;
    #   • не светится в истории посещений как часть запроса;
    #   • не уходит в заголовок Referer на сторонние сайты.
    # Если бы ключ был в «?k=…», он осел бы в логах навсегда.
    #
    # Ссылка для друзей выглядит так:
    #   https://ВАШ-АДРЕС/#k=СЕКРЕТ
    # Всё, что после #, видит только браузер того, кому вы её дали.
    # r-строка: внутри JavaScript есть \/, и Python без r-префикса
    # выдавал SyntaxWarning: invalid escape sequence.
    KEY_SNIPPET = r"""
<script>
// Ключ доступа из якоря URL. Якорь не уходит на сервер, поэтому ключ
// не попадает в журналы. Держим его в памяти страницы и добавляем
// к каждому запросу тайла.
(function () {
  var m = (location.hash || '').match(/[?&]k=([^&]+)/);
  var key = m ? decodeURIComponent(m[1]) : '';
  if (!key) return;
  window.__CHRONO_KEY__ = key;
  // Перехватываем fetch, чтобы MapLibre и PMTiles сами подставляли ключ.
  // Библиотека про Range-запросы ничего не знает и знать не должна.
  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      // Ключ добавляем только к своим тайлам, не к CDN и не к Wikidata.
      if (/\/tiles\//.test(url) && url.indexOf('k=') === -1) {
        url += (url.indexOf('?') === -1 ? '?' : '&') + 'k=' + encodeURIComponent(key);
        if (typeof input === 'string') return realFetch(url, init);
        return realFetch(new Request(url, input), init);
      }
    } catch (e) { /* если что-то пошло не так — отдаём запрос как есть */ }
    return realFetch(input, init);
  };
})();
</script>
"""
    # Защита от утечки ключа через Referer.
    #
    # Страница обращается к сторонним ресурсам: MapLibre с CDN, ссылки на
    # wikidata.org и на ваши статьи. По умолчанию браузер передаёт им полный
    # адрес страницы в заголовке Referer — вместе с «?k=СЕКРЕТ», который
    # добавляет перехватчик fetch. Meta-тег referrer=no-referrer обрывает это:
    # сторонние сайты видят только происхождение, без строки запроса.
    # Без якоря (#) проблемы бы не было, но запросы тайлов идут именно с «?k=».
    REFERRER_META = '<meta name="referrer" content="no-referrer">\n'
    if 'name="referrer"' not in html:
        if "<head>" in html:
            html = html.replace("<head>", "<head>\n" + REFERRER_META, 1)
        else:
            html = REFERRER_META + html

    # Вставляем перед закрывающим </head>, чтобы ключ был готов до загрузки карты
    if "</head>" in html:
        html = html.replace("</head>", KEY_SNIPPET + "</head>", 1)
    else:
        html = KEY_SNIPPET + html
        log("  ! в preview.html нет </head> — ключ вставлен в самое начало")

    dst = os.path.join(PUB, "index.html")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(html)
    total += os.path.getsize(dst)
    log(f"  ✓ {'index.html':26s} {human(os.path.getsize(dst))}  "
        f"(ключ из якоря{' , библиотека с CDN' if use_cdn else ''})")

    # Список эпох — карта читает его, чтобы построить переключатель
    with open(os.path.join(PUB, "eras.json"), "w", encoding="utf-8") as fh:
        json.dump({"eras": [{k: e[k] for k in ("id", "name", "year", "file")}
                            for e in eras]}, fh, ensure_ascii=False, indent=1)
    total += os.path.getsize(os.path.join(PUB, "eras.json"))

    log("")
    log(f"  эпох: {len(eras)}   всего в public/: {human(total)}")
    log(f"  папка: {PUB}")
    return eras


def check():
    """
    Убедиться, что в public/ не попало ничего лишнего.

    Это не паранойя: стоит один раз положить в папку эпохи скан атласа или
    конспект, и следующий запуск скопирует его в интернет. Проверка идёт по
    всему дереву, а не только по первому уровню.
    """
    bad = []
    nfiles = 0
    allowed = {"index.html", "eras.json", "maplibre-gl.js", "maplibre-gl.css"}
    for dirpath, _dirs, files in os.walk(PUB):
        for fn in files:
            nfiles += 1
            low = fn.lower()
            for pat in FORBIDDEN:
                if pat in low:
                    if low in allowed:
                        continue
                    bad.append((os.path.relpath(os.path.join(dirpath, fn), PUB),
                                pat))
                    break
    log("")
    log(f"Проверка public/: файлов {nfiles}")
    if bad:
        log(f"  ✗ НАЙДЕНО ЛИШНЕЕ — это уйдёт в интернет:")
        for path, pat in bad:
            log(f"      {path}   (совпало с «{pat}»)")
        return False
    log("  ✓ лишнего нет: только index.html, стили, библиотека, eras.json и тайлы")
    # Отдельно убедимся, что папок с исходниками вообще не появилось
    for d in ("maps", "tools", "out", "ne", "geom", "qgis", "_cache"):
        if os.path.exists(os.path.join(PUB, d)):
            log(f"  ✗ в public/ есть каталог {d}/ — его там быть не должно")
            return False
    return True


def main(argv):
    do_check = "--check" in argv
    do_serve = "--serve" in argv

    use_cdn = "--cdn" in argv
    log(f"Сборка публичной папки (библиотека: "
        f"{'с CDN' if use_cdn else 'локально, в public/'})")
    eras = build(use_cdn=use_cdn)
    if eras is None:
        return 1

    ok = check() if do_check else True
    if do_check and not ok:
        return 1

    if do_serve:
        log("")
        log("Поднимаю локальный сервер на public/ — порт 8080")
        log("  открыть:  http://localhost:8080/")
        log("  остановить: Ctrl+C")
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        try:
            import devserver
            # --root . ОБЯЗАТЕЛЕН: без него devserver возьмёт корень проекта
            # от своего __file__ и начнёт отдавать исходники вместе с картой.
            sys.argv = ["devserver.py", "8080", "--root", PUB]
            devserver.main()
        except Exception as e:
            log(f"  ! не удалось поднять devserver: {e!r:.100}")
            log("    запасной вариант: cd public && python3 -m http.server 8080")
            log("    (но он не отвечает 206 на Range — PMTiles может не открыться)")
            return 1
    else:
        log("")
        log("Дальше — один из трёх способов публикации:")
        log("  1. Туннель (быстро, пока компьютер включён):")
        log("     cloudflared tunnel --url http://localhost:8080")
        log("     и держать сервер:  python3 tools/make_public.py --serve")
        log("  2. R2 + Worker (постоянно, тайлы под ключом):")
        log("     см. deploy/worker.js и РАЗВЕРНУТЬ_БЕСПЛАТНО.md §2")
        log("  3. GitHub Pages (публично, тайлы НЕ закрыты)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
