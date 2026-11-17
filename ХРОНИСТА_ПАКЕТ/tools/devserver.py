#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальный сервер для просмотра карты.

    python3 tools/devserver.py            # порт 8080
    python3 tools/devserver.py 8090       # свой порт

Чем отличается от `python3 -m http.server`:

  1. Поддерживает заголовки Range и отвечает 206 Partial Content.
     Без этого невозможно читать .pmtiles: MapLibre и библиотека pmtiles
     запрашивают отдельные байты архива, а не файл целиком. Стандартный
     http.server всегда отвечает 200 со всем файлом — PMTiles при этом
     просто не работает. Именно поэтому GitHub Pages и Cloudflare R2
     подходят, а голый python -m http.server — нет.

  2. Отвечает на CORS-префлайс OPTIONS (204 + разрешающие заголовки)
     и добавляет Access-Control-Allow-Origin ко всем ответам.
     Стандартный сервер на OPTIONS отвечает 501, и если запрос окажется
     кросс-доменным (например, через прокси предпросмотра), карта упадёт
     молча — в консоли будет непонятная ошибка сети.

  3. Принимает любой Host. Стандартный сервер на подделанный Host отвечает
     404 ("Invalid host header"), что ломает работу через прокси.

Всё остальное — как в стандартном http.server.
"""
import os
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Сколько байт отдавать одним куском при потоковой передаче
CHUNK = 65536


class Handler(SimpleHTTPRequestHandler):
    server_version = "ChronoDev/1.0"
    protocol_version = "HTTP/1.1"      # нужно, чтобы работал Connection: keep-alive

    # --- CORS ---------------------------------------------------------------
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Authorization")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Length, Content-Range, Accept-Ranges")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.end_headers()

    def log_message(self, fmt, *args):
        # короче и без мусора: метод путь код размер
        sys.stderr.write("  %s\n" % (fmt % args))

    # --- Range --------------------------------------------------------------
    def _range(self, length):
        """Разбор 'bytes=a-b' / 'bytes=a-' / 'bytes=-N'. → (start, end) или None."""
        h = self.headers.get("Range")
        if not h or not h.startswith("bytes="):
            return None
        try:
            unit, _, val = h.partition("=")
            val = val.split(",")[0].strip()
            if val.startswith("-"):                      # последние N байт
                n = int(val[1:])
                if n <= 0:
                    return None
                return max(0, length - n), length - 1
            a, _, b = val.partition("-")
            start = int(a)
            end = int(b) if b else length - 1
        except (ValueError, IndexError):
            return None
        if start >= length or start > end:
            return ("bad", length)
        return start, min(end, length - 1)

    def _send_body(self, f, length, start, end):
        """Отправить [start..end] включительно. length = полный размер файла."""
        partial = start is not None
        if partial:
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{length}")
            self.send_header("Content-Length", str(end - start + 1))
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(length))

        ctype = self.guess_type(self.path)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Last-Modified",
                         self.date_time_string(os.fstat(f.fileno()).st_mtime))
        self.end_headers()

        if self.command == "HEAD":
            return
        f.seek(start or 0)
        left = (end - start + 1) if partial else length
        while left > 0:
            buf = f.read(min(CHUNK, left))
            if not buf:
                break
            self.wfile.write(buf)
            left -= len(buf)

    def send_head(self):
        """Полностью берём на себя отдачу файла, чтобы поддержать Range."""
        path = self.translate_path(self.path)

        if os.path.isdir(path):
            # каталог: index.html или список файлов — делегируем родителю
            if not self.path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", self.path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            for idx in ("index.html", "index.htm"):
                p = os.path.join(path, idx)
                if os.path.isfile(p):
                    path = p
                    break
            else:
                return super().send_head()

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        try:
            length = os.fstat(f.fileno()).st_size
            r = self._range(length)
            if r and r[0] == "bad":
                # диапазон вне файла → 416, как требует RFC 7233
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{length}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                f.close()
                return None
            start, end = r if r else (None, None)
            self._send_body(f, length, start, end)
        except (BrokenPipeError, ConnectionResetError):
            pass                        # клиент закрыл вкладку — это не ошибка
        finally:
            f.close()
        return None                     # тело уже отправлено


def main():
    """
    Запуск:  python3 tools/devserver.py [ПОРТ] [--root ПАПКА]

    --root задаёт, ЧТО отдавать. По умолчанию — корень проекта, это удобно для
    разработки. Для публикации друзьям ОБЯЗАТЕЛЬНО нужен --root public/, иначе
    вместе с картой уйдут таблицы, геометрия, gaps.md и кэш Overpass.

    Раньше ключа --root не было: main() жёстко брал корень от __file__ и
    игнорировал аргументы. Из-за этого make_public.py --serve поднимал сервер
    с корнем проекта и честно отдавал maps/eras/*/qgis/gaps.md кодом 200 —
    ровно то, что публиковать нельзя. Заметил я это только потому, что
    index.html пришёл размером 1004 байта вместо 19300.
    """
    argv = list(sys.argv[1:])
    root = None
    if "--root" in argv:
        i = argv.index("--root")
        root = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    positional = [a for a in argv if not a.startswith("-")]
    port = int(positional[0]) if positional else 8080

    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root is None:
        root = proj
    elif root == ".":
        # текущая папка — так делает make_public.py --serve
        root = os.getcwd()
    elif not os.path.isabs(root):
        root = os.path.join(proj, root)
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        print(f"  ✗ корень не найден: {root}")
        return 1
    os.chdir(root)

    # 0.0.0.0 обязательно: сервер должен быть виден извне песочницы
    # ПЕЧАТАЕМ КОРЕНЬ ВСЛУХ. Однажды я поднял сервер не из public/, а из корня
    # проекта, и он исправно отдавал maps/eras/*/qgis/gaps.md, polities.csv,
    # era.yml и кэш Overpass — то есть всё, что публиковать нельзя. Ошибку
    # было не видно: сервер отвечал 200 на всё, и только размер index.html
    # (1004 байта вместо 19300) выдавал, что корень другой.
    #
    # Если вы публикуете карту друзьям — корень ДОЛЖЕН быть public/.
    # Проверить после запуска:
    #     curl -s -o /dev/null -w "%{http_code}\n" http://localhost:ПОРТ/maps/
    # должно быть 404. Если 200 — вы отдаёте исходники, остановите сервер.
    root = os.path.abspath(root)
    print(f"  корень:  {root}")
    if os.path.basename(root) != "public":
        print("  ! ВНИМАНИЕ: корень НЕ public/. Если сервер доступен из интернета,")
        print("    вместе с картой отдаются таблицы, геометрия, отчёты gaps.md и кэш.")
        print("    Правильно:  python3 tools/make_public.py --serve")
    print(f"  адрес:   http://localhost:{port}/")
    httpd = ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, directory=root))
    httpd.daemon_threads = True

    # Баннер намеренно короткий: корень и адрес уже напечатаны выше, и дубль
    # только мешал читать предупреждение про корень.
    print(f"""
  Сервер запущен. Ctrl+C — остановить

  Range-запросы: поддерживаются (206 Partial Content) — .pmtiles читаются
  CORS: разрешён для всех источников
""")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  остановлено")
        httpd.server_close()


if __name__ == "__main__":
    main()
