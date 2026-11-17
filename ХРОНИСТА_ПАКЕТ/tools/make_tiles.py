#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_tiles.py — сборка .pmtiles из GeoJSON эпох (вариант A из плана).

    out/era-<id>.geojson  →  tiles/era-<id>.pmtiles

Скрипт сам находит Java, сам скачивает planetiler.jar (один раз, в кэш),
сам компилирует профиль и сам собирает тайлы. От вас — только запустить.

    python3 tools/make_tiles.py                 # все эпохи из out/
    python3 tools/make_tiles.py bc323           # одна эпоха
    python3 tools/make_tiles.py --maxzoom 6     # задать зум для всех
    python3 tools/make_tiles.py --check         # только отчёт о весах

Что важно знать (замерено на демо):
    maxzoom 4 → 175 КБ · 5 → 335 КБ · 6 → 692 КБ · 7 → 1,5 МБ · 8 → 3,3 МБ
    Каждый лишний зум удваивает вес. Для мирового снимка хватает 5–6.
    Детальность «до Колизея» делается отдельным региональным файлом.

Требует: Java 21+ в PATH (или JAVA_HOME). На GitHub Actions ставится одной строкой.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "tools", "planetiler")
OUT = os.path.join(ROOT, "out")
TILES = os.path.join(ROOT, "tiles")

PLANETILER_VERSION = "v0.10.2"          # проверено на этой версии
PLANETILER_URL = ("https://github.com/onthegomap/planetiler/releases/download/"
                  f"{PLANETILER_VERSION}/planetiler.jar")
JAR = os.path.join(HERE, "planetiler.jar")
PROFILE = os.path.join(HERE, "ChronoProfile.java")
MIN_JAVA = 21

# Вес, выше которого файл опасно приближается к лимиту GitHub Pages (100 МБ)
WARN_MB = 20
BLOCK_MB = 90


# ------------------------------------------------------------------ Java ----
def find_java():
    """
    Возвращает (путь, старшая_версия) для ЛУЧШЕЙ найденной Java.

    Прежняя версия перебирала JAVA_HOME, затем `java` из PATH, и возвращала
    ПЕРВУЮ найденную. На Ubuntu 26.04 это ломается: в PATH часто первой стоит
    Java 11 (пакет openjdk-lts — это именно 11), а установленная рядом Java 21
    остаётся незамеченной, и сборка падает с UnsupportedClassVersionError.

    Теперь перебираем все обычные места установки и берём самую свежую версию,
    подходящую под MIN_JAVA. Проверено: при Java 11 в PATH и Temurin 21 в
    ~/.jdk/ возвращает 21-ю.
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
    found, seen = [], set()
    for cand in cands:
        try:
            real = os.path.realpath(cand)
        except OSError:
            continue
        if real in seen or not os.path.exists(cand):
            continue
        seen.add(real)
        try:
            v = subprocess.run([cand, "-version"], capture_output=True, text=True, timeout=30)
            txt = (v.stderr or "") + (v.stdout or "")
            m = re.search(r'version "(\d+)', txt)
            if m:
                found.append((cand, int(m.group(1))))
        except Exception:
            pass
    if not found:
        return None, 0
    ok = [f for f in found if f[1] >= MIN_JAVA]
    if ok:
        return max(ok, key=lambda x: x[1])
    return max(found, key=lambda x: x[1])


def ensure_java():
    path, ver = find_java()
    if not path:
        sys.exit(
            "Не найдена Java.\n"
            "  Ubuntu 26.04:  sudo apt install openjdk-21-jdk\n"
            "  Не ставьте default-jdk и openjdk-lts — в resolute это Java 11,\n"
            "  а Planetiler v0.10.2 на ней падает с UnsupportedClassVersionError.\n"
            "  Windows: Temurin JDK 21, https://adoptium.net/temurin/releases/?version=21\n"
            "  Или оставьте сборку GitHub Actions — там Java ставится сама."
        )
    if ver < MIN_JAVA:
        sys.exit(f"Найдена Java {ver}, а planetiler {PLANETILER_VERSION} собран под Java {MIN_JAVA}+.\n"
                 f"  Путь: {path}\n"
                 f"  Ubuntu 26.04:  sudo apt install openjdk-21-jdk\n"
                 f"  Если 21-я уже стоит, но PATH указывает на 11-ю — задайте JAVA_HOME:\n"
                 f"      export JAVA_HOME=$(ls -d /usr/lib/jvm/java-21-openjdk-* | head -1)\n"
                 f"  Проверить все найденные JDK:  python3 tools/extract_era.py doctor")
    return path, ver


def ensure_jar():
    if os.path.exists(JAR) and os.path.getsize(JAR) > 50_000_000:
        return
    os.makedirs(HERE, exist_ok=True)
    print(f"  ↓ скачиваю planetiler.jar ({PLANETILER_VERSION}, ~89 МБ) — один раз…")
    tmp = JAR + ".part"
    try:
        urllib.request.urlretrieve(PLANETILER_URL, tmp)
        os.replace(tmp, JAR)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        sys.exit(f"Не удалось скачать planetiler.jar: {e}\n"
                 f"  Скачайте вручную: {PLANETILER_URL}\n  и положите в {JAR}")


def compile_profile(java):
    if not os.path.exists(PROFILE):
        sys.exit(f"Нет профиля: {PROFILE}")
    classes = os.path.join(HERE, "classes")
    os.makedirs(classes, exist_ok=True)
    javac = os.path.join(os.path.dirname(java), "javac")
    if not os.path.exists(javac):
        javac = shutil.which("javac") or "javac"
    r = subprocess.run([javac, "-nowarn", "-encoding", "UTF-8",
                        "-cp", JAR, "-d", classes, PROFILE],
                       capture_output=True, text=True)
    if not os.path.exists(os.path.join(classes, "ChronoProfile.class")):
        sys.exit("Компиляция профиля не удалась:\n" + (r.stderr or r.stdout)[-2000:])
    return classes


# ---------------------------------------------------------------- сборка ----
def build(java, classes, geojson, pmtiles, maxzoom, minzoom=0):
    cp = JAR + os.pathsep + classes
    cmd = [java, "-Xmx3g", "-cp", cp, "ChronoProfile",
           f"--input={geojson}", f"--output={pmtiles}",
           f"--minzoom={minzoom}", f"--maxzoom={maxzoom}", "--force"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    if not os.path.exists(pmtiles) or os.path.getsize(pmtiles) < 200:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-14:]
        raise RuntimeError(f"planetiler не создал {os.path.basename(pmtiles)}:\n  "
                           + "\n  ".join(tail))
    return os.path.getsize(pmtiles)


def maxzoom_for(era_id):
    """Читаем maxzoom из era.yml эпохи, если он там задан."""
    yml = os.path.join(ROOT, "maps", "eras", era_id, "era.yml")
    if os.path.exists(yml):
        m = re.search(r"^\s*maxzoom\s*:\s*(\d+)", open(yml, encoding="utf-8").read(), re.M)
        if m:
            return int(m.group(1))
    return 6


def report():
    files = sorted(glob.glob(os.path.join(TILES, "*.pmtiles")))
    if not files:
        print("  в tiles/ пусто — сначала соберите")
        return 0, 0
    total, worst = 0, 0
    print(f"\n{'файл':38s} {'вес':>10s}  {'zoom':>6s}  {'статус'}")
    print("  " + "-" * 72)
    for p in files:
        s = os.path.getsize(p)
        total += s
        worst = max(worst, s)
        mb = s / 1048576
        z = "?"
        try:
            import mmap
            from pmtiles.reader import Reader, MmapSource
            with open(p, "rb") as f:
                z = f"{Reader(MmapSource(f)).header()['min_zoom']}–{Reader(MmapSource(f)).header()['max_zoom']}"
        except Exception:
            pass
        status = "✓"
        if mb >= BLOCK_MB:
            status = "✗ ПРЕВЫШАЕТ ЛИМИТ GITHUB PAGES (100 МБ) — делить по регионам"
        elif mb >= WARN_MB:
            status = "! близко к лимиту — стоит снизить maxzoom"
        print(f"  {os.path.basename(p):38s} {mb:8.2f} МБ  {z:>6s}  {status}")
    print("  " + "-" * 72)
    print(f"  {'ИТОГО':38s} {total/1048576:8.2f} МБ")
    print(f"  лимит GitHub Pages: 100 МБ на файл, 1 ГБ на сайт")
    return total, worst


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("eras", nargs="*", help="id эпох (без указания — все из out/)")
    ap.add_argument("--maxzoom", type=int, default=None)
    ap.add_argument("--minzoom", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="только отчёт о весах")
    a = ap.parse_args()

    if a.check:
        report()
        return 0

    java, ver = ensure_java()
    print(f"Java {ver}: {java}")
    ensure_jar()
    classes = compile_profile(java)
    os.makedirs(TILES, exist_ok=True)

    srcs = sorted(glob.glob(os.path.join(OUT, "era-*.geojson")))
    if a.eras:
        want = set(a.eras)
        srcs = [s for s in srcs
                if os.path.basename(s)[len("era-"):-len(".geojson")] in want]
        if not srcs:
            sys.exit(f"в out/ нет эпох {sorted(want)}. Сначала: python3 tools/build_map.py era --all")
    if not srcs:
        sys.exit("в out/ нет era-*.geojson. Сначала: python3 tools/build_map.py era --all")

    print(f"\nСборка тайлов ({len(srcs)} шт.):")
    failed = 0
    for s in srcs:
        eid = os.path.basename(s)[len("era-"):-len(".geojson")]
        mz = a.maxzoom if a.maxzoom is not None else maxzoom_for(eid)
        dst = os.path.join(TILES, f"era-{eid}.pmtiles")
        raw = os.path.getsize(s) / 1024
        try:
            size = build(java, classes, s, dst, mz, a.minzoom)
            mb = size / 1048576
            flag = "✗" if mb >= BLOCK_MB else ("!" if mb >= WARN_MB else "✓")
            print(f"  {flag} era-{eid}.pmtiles  z{a.minzoom}–{mz}  "
                  f"{raw:,.0f} КБ GeoJSON → {mb:.2f} МБ")
        except Exception as e:
            failed += 1
            print(f"  ✗ {eid}: {e}")
    report()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
