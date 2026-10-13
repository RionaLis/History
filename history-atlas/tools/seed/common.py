"""Общие хелперы для генерации контента (md-файлов) из компактных таблиц.

Схема сущности (entity):
    id      — латинский идентификатор (имя файла)
    name    — название на русском
    type    — state | people | culture | empire | colony | polity
    start   — год начала (отрицательные — до н.э., 0 не используется)
    end     — год окончания
    spans   — список присутствий по «дорожкам» (lane):
                ("lane_id", share, from, to)        — постоянная доля региона
                ("lane_id", [(год, доля), ...])     — доля меняется во времени
              доля = какую часть площади дорожки (суб-региона) занимает
              государство; именно она задаёт толщину ленты на схеме.
    summary — одно предложение для всплывающей подсказки
    body    — подробный текст (markdown) для панели/страницы, необязателен
    tags    — список меток
    color   — явный цвет (иначе вычисляется от региона)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union
import colorsys
import hashlib

Span = Union[Tuple[str, float, int, int], Tuple[str, Sequence[Tuple[int, float]]]]

TYPE_NAMES = {
    "state": "государство",
    "empire": "империя",
    "people": "народ",
    "culture": "археологическая культура",
    "polity": "политическое образование",
    "colony": "колониальное владение",
    "confed": "союз / конфедерация",
}


@dataclass
class E:
    id: str
    name: str
    type: str
    start: int
    end: int
    spans: List[Span]
    summary: str = ""
    body: str = ""
    tags: List[str] = field(default_factory=list)
    color: Optional[str] = None
    label: Optional[str] = None  # короткая подпись на ленте
    aliases: List[str] = field(default_factory=list)


@dataclass
class Ev:
    id: str
    name: str
    year: int
    lane: str
    icon: str  # pottery|metal|battle|revolt|revolution|migration|invasion|massive|idea|disaster
    summary: str = ""
    body: str = ""
    scale: int = 2  # 1..3 — значимость (влияет на размер значка и порог показа)
    year_end: Optional[int] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class Mig:
    id: str
    name: str
    points: List[Tuple[int, str]]  # [(год, lane_id), ...] — путь переселения
    summary: str = ""
    body: str = ""
    kind: str = "migration"  # migration | invasion | trade | diffusion
    tags: List[str] = field(default_factory=list)


def norm_spans(spans: List[Span]):
    out = []
    for sp in spans:
        if len(sp) == 4:
            lane, share, a, b = sp
            pts = [[int(a), float(share)], [int(b), float(share)]]
        else:
            lane, raw = sp
            pts = [[int(y), float(s)] for y, s in raw]
        pts.sort(key=lambda p: p[0])
        out.append({"lane": lane, "points": pts})
    return out


def auto_color(entity_id: str, base_hue: float, spread: float = 40.0,
               kind: str = "state") -> str:
    """Детерминированный цвет в палитре региона (как семейства цветов на плакате).

    Государства и империи — насыщеннее, народы и культуры — бледнее и мягче:
    это даёт визуальную иерархию «фон — политии»."""
    h = hashlib.md5(entity_id.encode("utf-8")).digest()
    hue = (base_hue + ((h[0] / 255.0) - 0.5) * spread) % 360.0
    if kind in ("empire", "state", "colony"):
        sat = 0.50 + (h[1] / 255.0) * 0.42
        lig = 0.50 + (h[2] / 255.0) * 0.20
    else:
        sat = 0.30 + (h[1] / 255.0) * 0.32
        lig = 0.62 + (h[2] / 255.0) * 0.17
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, lig, sat)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def fmt_year(y: int) -> str:
    if y < 0:
        return f"{abs(y)} до н.э."
    return f"{y} н.э."


def fmt_period(a: int, b: int) -> str:
    return f"{fmt_year(a)} — {fmt_year(b)}"
