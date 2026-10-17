// Лента хронологии + мост «карта ↔ таблица ↔ лента».
// Данные — data/index.json (собирается из content/*.md скриптом tools/build.py).
// Контур на карте связан со статьёй ленты, если их названия совпадают.

import { formatYear } from './scale.js';
import { ICON_LABELS } from './icons.js';

const $ = s => document.querySelector(s);

const ICON_COLOR = {
  pottery: '#8a6a2f', metal: '#566', battle: '#9c2b2b', revolt: '#b4552d',
  revolution: '#9c2b2b', migration: '#5a4632', invasion: '#9c2b2b',
  massive: '#222733', idea: '#6b4fb3', disaster: '#b4552d',
};

let DATA = null;
let dates = [];            // отсортированные годы, в которых есть события
let eventsByYear = new Map();
let idx = 0;               // текущая позиция в dates
let chart = null;          // её таблица (window.chart из assets/js/app.js)

let src = null, srcT = 0;   // кто последний синхронизировал (guard от петель)
let suppress = false;       // наш собственный setYear — хук молчит
const mark = s => { src = s; srcT = Date.now(); };
const recent = () => Date.now() - srcT < 1500;

let tableTouch = 0;         // последнее касание шкалы таблицы («её палец»)
const tableRecent = () => Date.now() - tableTouch < 1500;

// перерисовка ленты: не чаще ~7 раз в секунду, но с хвостом после серии событий
let lastRender = 0, renderT = null;
function scheduleRender() {
  const now = Date.now();
  clearTimeout(renderT);
  if (now - lastRender >= 150) { lastRender = now; render(); return; }
  renderT = setTimeout(() => { lastRender = Date.now(); render(); }, 120);
}

/** Единственный источник истины — год карты (его двигают слайдер, таблица, чипы, ▶). */
function currentYear() {
  return (window.chronomap && typeof window.chronomap.state === 'object')
    ? window.chronomap.state.year : dates[idx];
}

/** Перенос центра таблицы с сохранением ширины окна в ГОДАХ
 *  (на нелинейной шкале центровка без пересчёта схлопывала окно). */
function centerTable(y) {
  if (!chart) return;
  try {
    const [a, b] = chart.visibleYears();
    let span = b - a;
    if (!(span >= 5)) span = 500;
    chart.setVisibleSpan(span, y);
  } catch (e) {
    try { chart.centerOn(y); } catch (e2) { /* chart ещё не готов */ }
  }
}

/* ---------------------------------------------------------- ожидание */

const t0 = Date.now();
const wait = setInterval(() => {
  if (window.DATA && window.chart && window.chronomap) {
    clearInterval(wait);
    boot();
  } else if (Date.now() - t0 > 60000) {
    clearInterval(wait);
    $('#feed-list').innerHTML = '<div class="feed-empty">Не удалось загрузить данные ленты — обновите страницу.</div>';
  }
}, 300);

function boot() {
  DATA = window.DATA;
  chart = window.chart;

  // даты = годы всех событий из content/*.md
  const years = new Set();
  for (const e of DATA.events) {
    years.add(e.year);
    if (e.yearEnd) for (let y = e.year; y <= e.yearEnd; y += Math.max(1, Math.round((e.yearEnd - e.year) / 8))) years.add(y);
  }
  dates = [...years].sort((a, b) => a - b);
  for (const e of DATA.events) {
    if (!eventsByYear.has(e.year)) eventsByYear.set(e.year, []);
    eventsByYear.get(e.year).push(e);
  }

  // стартовое положение — ближайшая дата к текущему году карты
  idx = nearestIdx(window.chronomap.state.year);
  render();

  // — клики панели навигации —
  $('#feed-prev').addEventListener('click', () => go(idx - 1));
  $('#feed-next').addEventListener('click', () => go(idx + 1));
  wireSwipe();

  // — карта/слайдер/чипы/▶ сменили год → лента и таблица следуют одновременно —
  window.chronomap.onYearChange(y => {
    if (suppress) return;                        // это мы сами двигали дату
    mark('map');
    idx = nearestIdx(y);
    scheduleRender();                            // метка, поле видимости, карточки
    if (tableRecent() || !chart) return;         // её палец на таблице — не спорим
    try {
      const [a, b] = chart.visibleYears();
      // дата ВНЕ рамки → подтягиваем окно. Внутри — окно не трогаем:
      // иначе после перетаскивания у края шкалы оно самоцентрировалось.
      if (y < a || y > b) {
        mark('feed');
        centerTable(y);
      }
    } catch (e) { /* chart ещё не готов */ }
  });

  // — шкала таблицы двигается (пан, колесо, обзорка, стрелки) → карта и лента следуют —
  // окно «её палец на шкале» продлевается при каждом движении с зажатой кнопкой
  const touchTable = () => { tableTouch = Date.now(); };
  const tz = document.querySelector('.table-zone');
  if (tz) {
    // клик по кнопке/чипу/слайдеру — это НЕ перетаскивание таблицы
    tz.addEventListener('pointerdown', e => {
      if (e.target && e.target.closest && e.target.closest('button, input, label, a')) return;
      touchTable();
    }, { passive: true });
    tz.addEventListener('pointermove', e => { if (e.buttons) touchTable(); }, { passive: true });
    tz.addEventListener('wheel', touchTable, { passive: true });
    tz.addEventListener('touchstart', touchTable, { passive: true });
    tz.addEventListener('touchmove', touchTable, { passive: true });
  }
  window.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') touchTable();
  });

  // Карта права по умолчанию; таблица побеждает, только если её центр СДВИНУЛСЯ
  // (пан/колесо/обзорка) или палец ещё на шкале. Так нет петель и отката слайдера.
  let lastCenter = null;                       // для FEED._dbg
  setInterval(() => {
    if (!window.chart || !window.chronomap) return;
    try {
      const [a, b] = window.chart.visibleYears();
      const span = b - a;
      const center = Math.round((a + b) / 2);
      const y = window.chronomap.state.year;
      const active = tableRecent();
      lastCenter = center;
      if (span > 3500) return;                  // дальний обзор не трогаем
      if (center === y) return;
      // её палец на таблице → дата = центру. Иначе: пока дата В КАДРЕ — она
      // выбранная (усечённые у края шкалы рамки, чипы вокруг даты, прыжки);
      // вывалилась из кадра — подтягиваем к центру. Так нет петель и отката.
      if (!active && y >= a && y <= b) return;
      mark('table');
      suppress = true;
      window.chronomap.setYear(center);
      suppress = false;
      idx = nearestIdx(center);
      render();                                 // метка/поле/карточки — сразу
    } catch (e) { /* таблица ещё стартует */ }
  }, 300);

  // — перерисовываем связки «контур ↔ статья» после движения карты —
  let relTimer = null;
  const scheduleRelations = () => {
    clearTimeout(relTimer);
    relTimer = setTimeout(() => {
      contourIndex = null;      // после движения/drag года индекс устарел — заново
      contourTries = 0;
      updateRelations();
    }, 900);
  };
  window.chronomap.map.on('moveend', scheduleRelations);
  window.chronomap.map.on('idle', scheduleRelations);
  window.chronomap.map.on('render', scheduleRelations);
  scheduleRelations();

  // — мост для попапов карты (map-app.js вызывает window.CHRONO_LINK) —
  window.CHRONO_LINK = {
    findEntity: name => findEntity(name),
    findEvent: title => findEvent(title),
    openItem: (kind, id) => openItem(kind, id),
  };

  window.FEED = {
    go, dates: () => dates, current: () => dates[idx], setIdx: i => go(i),
    _contour: () => contourIndex ? [...contourIndex.keys()].slice(0, 40) : null,
    _year: () => currentYear(),
    _refresh: () => scheduleRender(),
    _active: () => DATA.entities.filter(e => e.start <= currentYear() && e.end >= currentYear()).length,
    _dbg: () => ({
      tableTouchAgo: Date.now() - tableTouch, src, srcAgo: Date.now() - srcT,
      idxYear: dates[idx], suppress
    }),
  };
}

/* ---------------------------------------------------------- даты */

function nearestIdx(year) {
  let best = 0, bd = Infinity;
  for (let i = 0; i < dates.length; i++) {
    const d = Math.abs(dates[i] - year);
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}

function go(i) {
  applyStep(i);
}

/** Шаг по датам (‹ ›, свайп): всё — на выбранную дату одновременно. */
function applyStep(i) {
  i = Math.max(0, Math.min(dates.length - 1, i));
  const changed = i !== idx;
  idx = i;
  const D = dates[idx];
  mark('feed');
  if (window.chronomap && window.chronomap.state.year !== D) {
    suppress = true;
    window.chronomap.setYear(D);
    suppress = false;
    clearHighlight();
  }
  if (chart && !tableRecent()) {
    try {
      const [a, b] = chart.visibleYears();
      if (D < a || D > b) centerTable(D);        // вне рамки — подтягиваем; внутри не двигаем
    } catch (e) { /* chart ещё не готов */ }
  }
  render();                                  // метка, поле видимости, карточки — сразу
}

/* ---------------------------------------------------------- отрисовка */

function render() {
  const Y = currentYear();
  idx = nearestIdx(Y);                         // позиция ‹ › — ближайшая дата с событиями

  // центр — события выбранного дня (день-в-день, включая идущие)
  const evs = DATA.events
    .filter(e => e.year <= Y && Y <= (e.yearEnd || e.year))
    .sort((a, b) => a.year - b.year);
  $('#feed-date').textContent = formatYear(Y) + ' · событий: ' + evs.length;

  // рамка на шкале (окно масштаба) — в её пределах показываем «силуэты» соседей
  let fa = Y, fb = Y;
  try { const w = chart.visibleYears(); fa = w[0]; fb = w[1]; } catch (e) { /* chart не готов */ }
  const inFrame = e => e.year <= fb && (e.yearEnd || e.year) >= fa;
  const before = DATA.events
    .filter(e => e.year < Y && (e.yearEnd || e.year) < Y && inFrame(e))
    .sort((a, b) => b.year - a.year).slice(0, 3);
  const after = DATA.events
    .filter(e => e.year > Y && inFrame(e))
    .sort((a, b) => a.year - b.year).slice(0, 3);

  const list = $('#feed-list');
  let html = '';

  if (!evs.length && !before.length && !after.length) {
    html = '<div class="feed-empty">На ' + formatYear(Y) +
      ' в базе нет событий. Двигайтесь ‹ › — или добавьте файл в content/events/.</div>';
  } else {
    const sil = (e, side) => `<button class="feed-sil feed-sil-${side}" data-kind="event" data-id="${e.id}" ` +
      `title="${esc(e.name)} (${formatYear(e.year)})"><span class="fs-year">${formatYear(e.year)}</span>` +
      `<span class="fs-name">${esc(e.name)}</span></button>`;
    html += '<div class="feed-row">';
    html += '<div class="feed-sils">' + before.map(e => sil(e, 'before')).join('') + '</div>';
    html += '<div class="feed-center">';
    if (evs.length) {
      html += '<div class="feed-sec">Синхронные события</div>';
      for (const e of evs) {
        const color = ICON_COLOR[e.icon] || '#0b63d6';
        const badge = ICON_LABELS[e.icon] || 'событие';
        const when = e.yearEnd ? formatYear(e.year) + ' — ' + formatYear(e.yearEnd) : formatYear(e.year);
        html += `<article class="feed-card" id="fc-${e.id}" data-kind="event" data-id="${e.id}">
          <div class="fc-meta">
            <span class="fc-badge" style="background:${color}">${badge}</span>
            <span class="fc-year">${when}</span>
          </div>
          <h5>${esc(e.name)}</h5>
          ${e.summary ? `<p>${esc(e.summary)}</p>` : ''}
        </article>`;
      }
    } else {
      html += '<div class="feed-empty feed-empty-mid">В этот день событий нет — соседние по краям рамки</div>';
    }
    html += '</div>';
    html += '<div class="feed-sils">' + after.map(e => sil(e, 'after')).join('') + '</div>';
    html += '</div>';
  }

  list.innerHTML = html;
  list.scrollTop = 0;
  lastRender = Date.now();
  updateRelations();
  try { if (chart && chart.draw) chart.draw(); } catch (e) { /* красная черта на таблице */ }
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ---------------------------------------------------------- клики ленты */

$('#feed-list').addEventListener('click', e => {
  const card = e.target.closest('.feed-card, .feed-chip, .feed-sil');
  if (!card) return;
  const btn = e.target.closest('.feed-to-map');
  if (btn) {
    e.stopPropagation();
    flyToEntity(card.dataset.id);
    return;
  }
  openItem(card.dataset.kind, card.dataset.id);
});

function openItem(kind, id) {
  const coll = kind === 'event' ? DATA.events : DATA.entities;
  const obj = coll.find(x => x.id === id);
  if (!obj) return;

  // дата ленты
  if (kind === 'event') {
    const i = dates.indexOf(obj.year);
    if (i >= 0) applyStep(i);
  } else {
    let i = dates.findIndex(y => y >= obj.start && y <= obj.end);
    if (i < 0) i = nearestIdx(obj.start);
    applyStep(i);
  }

  // статья откроется её же штатной механикой (#e/id, #v/id)
  const prefix = kind === 'event' ? 'v' : 'e';
  if (location.hash !== `#${prefix}/${id}`) location.hash = `#${prefix}/${id}`;

  // подсветить карточку в ленте
  const el = document.getElementById((kind === 'event' ? 'fc-' : 'fch-') + id);
  if (el) {
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    el.style.outline = '2px solid var(--accent-2)';
    setTimeout(() => { el.style.outline = ''; }, 2200);
  }

  // если у сущности есть контур — показать его на карте
  if (kind === 'entity') flyToEntity(id, true);
}

/* ---------------------------------------------------------- связки контуров */

const norm = s => String(s == null ? '' : s)
  .toLowerCase().replace(/ё/g, 'е')
  .replace(/[«»"'`.,()]/g, '')
  .replace(/\s+/g, ' ').trim();

function nameKeys(entity) {
  return [norm(entity.name), ...(entity.aliases || []).map(norm)].filter(k => k.length > 2);
}

/** Похожи ли названия: точное равенство или одно — начало другого (достаточно длинное). */
function namesMatch(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.length >= 6 && b.startsWith(a)) return true;
  if (b.length >= 6 && a.startsWith(b)) return true;
  return false;
}

function findEntity(contourName) {
  const n = norm(contourName);
  if (!n) return null;
  return DATA.entities.find(e => nameKeys(e).some(k => namesMatch(k, n))) || null;
}

function findEvent(mapTitle) {
  const n = norm(mapTitle);
  if (!n) return null;
  return DATA.events.find(e => namesMatch(norm(e.name), n)) || null;
}

/** Индекс названий контуров, которые сейчас есть в данных карты. */
let contourIndex = null;   // Map<имя, GeoJSON-фичи[]>
let contourTries = 0;

function rebuildContourIndex() {
  const map = window.chronomap && window.chronomap.map;
  if (!map || !window.chronomap.ready) return false;
  const layerIds = ['fill-countries', 'fill-empires', 'fill-regions']
    .filter(id => { try { return !!map.getLayer(id); } catch (e) { return false; } });
  if (!layerIds.length) return false;

  const index = new Map();
  const add = f => {
    const name = f.properties && (f.properties.name_ru || f.properties.name);
    if (!name) return;
    const key = norm(name);
    if (!index.has(key)) index.set(key, []);
    const arr = index.get(key);
    if (arr.length < 40) arr.push(f);
  };

  for (const id of layerIds) {
    try { map.queryRenderedFeatures({ layers: [id] }).forEach(add); } catch (e) {}
    try {
      const srcId = map.getLayer(id).source;
      if (srcId) map.querySourceFeatures(srcId).forEach(add);   // и за пределами экрана
    } catch (e) {}
  }
  if (!index.size) return false;   // тайлы ещё грузятся — попробуем позже
  contourIndex = index;
  contourTries = 0;
  return true;
}

/** Строит индекс названий контуров (для попапов и «⌖»-связок). */
function updateRelations() {
  if (!DATA) return;
  if (!contourIndex && !rebuildContourIndex()) {
    // тайлы ещё грузятся — повторяем (до 20 раз)
    if (contourTries++ < 20) setTimeout(updateRelations, 1500);
  }
}

function featuresFor(entity) {
  if (!contourIndex) return [];
  for (const k of nameKeys(entity)) {
    for (const [name, feats] of contourIndex) {
      if (namesMatch(k, name)) return feats;
    }
  }
  return [];
}

function featuresByExactName(name) {
  if (!contourIndex) return [];
  const n = norm(name);
  return contourIndex.get(n) || [];
}

/** Перелёт к контуру сущности + подсветка. quiet — не дёргать ленту. */
function flyToEntity(id, quiet) {
  const e = DATA.entities.find(x => x.id === id);
  if (!e || !contourIndex && !rebuildContourIndex()) return;
  const feats = featuresFor(e);
  if (!feats.length) return;
  showHighlight(feats);

  // границы по всем версиям контура
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = c => {
    if (typeof c[0] === 'number') {
      minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0]);
      minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1]);
    } else c.forEach(walk);
  };
  feats.forEach(f => f.geometry && walk(f.geometry.coordinates));

  if (minX === Infinity) return;
  const map = window.chronomap.map;
  map.fitBounds([[minX, minY], [maxX, maxY]],
    { padding: { top: 70, bottom: 70, left: 70, right: 340 }, duration: 1500, maxZoom: 6.5, essential: true });
}

/* Подсветка контуров на карте */
function ensureHighlightLayers() {
  const map = window.chronomap.map;
  if (map.getLayer('link-hl-line')) return;
  map.addSource('link-hl', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({
    id: 'link-hl-fill', type: 'fill', source: 'link-hl',
    paint: { 'fill-color': '#d9a441', 'fill-opacity': 0.16 }
  });
  map.addLayer({
    id: 'link-hl-line', type: 'line', source: 'link-hl',
    paint: {
      'line-color': '#1c7a4a', 'line-width': 2.4, 'line-opacity': 0.95,
      'line-dasharray': [4, 2]
    }
  });
}

function showHighlight(features) {
  const map = window.chronomap.map;
  if (!window.chronomap.ready) return;
  try {
    ensureHighlightLayers();
    map.getSource('link-hl').setData({
      type: 'FeatureCollection',
      features: features.filter(f => f.geometry)
    });
  } catch (e) { console.warn('highlight:', e); }
}

function clearHighlight() {
  const map = window.chronomap && window.chronomap.map;
  if (!map) return;
  try {
    if (map.getSource('link-hl')) {
      map.getSource('link-hl').setData({ type: 'FeatureCollection', features: [] });
    }
  } catch (e) {}
}

/* ---------------------------------------------------------- свайп */

function wireSwipe() {
  const zone = document.querySelector('.feed-zone');
  if (!zone) return;
  let x0 = 0, y0 = 0, t0 = 0, active = false;

  zone.addEventListener('touchstart', e => {
    if (e.target.closest('button.feed-to-map')) return;
    const t = e.touches[0];
    x0 = t.clientX; y0 = t.clientY; t0 = Date.now(); active = true;
  }, { passive: true });

  zone.addEventListener('touchend', e => {
    if (!active) return;
    active = false;
    const t = e.changedTouches[0];
    const dx = t.clientX - x0, dy = t.clientY - y0;
    if (Date.now() - t0 > 900) return;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.4) return;
    if (dx < 0) go(idx + 1); else go(idx - 1);   // влево → позже, вправо → раньше
  }, { passive: true });
}

/* Поиск «⌖ на карту» по кнопке в ленте (делегирование уже выше) */
document.addEventListener('click', e => {
  const b = e.target.closest('.feed-to-map');
  if (!b) return;
  e.stopPropagation();
  flyToEntity(b.dataset.eid || b.closest('[data-id]')?.dataset.id);
});
