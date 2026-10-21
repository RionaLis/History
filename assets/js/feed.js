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
let dates = [];            // уникальные годы начала событий
let idx = 0;               // ближайшая дата события к выбранному году
let chart = null;          // таблица из assets/js/app.js
let booted = false;
let suppress = false;      // защищает от повторного рендера при нашем setYear

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

/* ---------------------------------------------------------- запуск */

const bootTimeout = setTimeout(() => {
  if (!booted) $('#feed-list').innerHTML = '<div class="feed-empty">Не удалось загрузить данные ленты — обновите страницу.</div>';
}, 60000);

function startWhenReady() {
  if (window.DATA && window.chart && window.chronomap) boot();
  else window.addEventListener('chrono:app-ready', boot, { once: true });
}

function boot() {
  if (booted || !window.DATA || !window.chart || !window.chronomap) return;
  booted = true;
  clearTimeout(bootTimeout);
  DATA = window.DATA;
  chart = window.chart;

  // Навигация идёт по реальным годам начала событий; события одного года
  // остаются одной синхронной группой, а промежуточные годы длинных событий
  // не становятся искусственными остановками.
  dates = [...new Set(DATA.events.map(e => e.year))].sort((a, b) => a - b);
  idx = nearestIdx(window.chronomap.state.year);

  window.CHRONO_LINK = {
    findEntity: (name, year) => findEntity(name, year),
    findEvent: title => findEvent(title),
    openItem: (kind, id) => openItem(kind, id),
    highlightEntity: id => flyToEntity(id, true, { popup: true }),
    // Карта → таблица: фокусируем полосу, не перемещая и не масштабируя карту.
    selectEntity: (id, year) => focusTableEntity(id, year),
    // Таблица → карта: сохраняем масштаб таблицы, синхронизируем год карты,
    // затем находим контур, приближаем его и открываем всплывающее окно.
    selectEntityFromTable: (id, year) => selectEntityOnMapFromTable(id, year),
  };
  window.FEED = {
    go,
    step: stepToEvent,
    dates: () => dates,
    current: () => dates[idx],
    setIdx: i => go(i),
    _contour: () => contourIndex ? [...contourIndex.keys()].slice(0, 40) : null,
    _year: () => currentYear(),
    _refresh: () => scheduleRender(),
    _active: () => DATA.entities.filter(e => e.start <= currentYear() && e.end >= currentYear()).length,
  };

  $('#feed-prev').addEventListener('click', () => stepToEvent(-1));
  $('#feed-next').addEventListener('click', () => stepToEvent(1));
  wireSwipe();
  render();

  // Карта — источник выбранного года. Если он вышел за видимый диапазон,
  // сдвигаем таблицу, сохраняя её масштаб.
  window.chronomap.onYearChange(y => {
    if (suppress) return;
    idx = nearestIdx(y);
    scheduleRender();
    if (!chart) return;
    try {
      const [a, b] = chart.visibleYears();
      if (y < a || y > b) centerTable(y);
    } catch (e) { /* chart ещё не готов */ }
  });

  // Панорамирование и локальный зум таблицы не меняют выбранный год на карте.
  // Только переход к объекту (поиск/кнопка «на таблице») синхронизирует центр.
  window.addEventListener('chrono:tableview', e => {
    const detail = e.detail || {};
    if (detail.source === 'navigate') {
      const y = Math.round(detail.center);
      if (y !== currentYear()) window.chronomap.setYear(y);
    }
  });

  // После движения карты обновляем индекс контуров для связки «контур ↔ статья».
  let relTimer = null;
  const scheduleRelations = () => {
    clearTimeout(relTimer);
    relTimer = setTimeout(() => {
      contourIndex = null;
      contourTries = 0;
      updateRelations();
    }, 900);
  };
  window.chronomap.map.on('moveend', scheduleRelations);
  window.chronomap.map.on('idle', scheduleRelations);
  window.chronomap.map.on('render', scheduleRelations);
  scheduleRelations();
}

startWhenReady();

function focusTableEntity(id, year) {
  const entity = DATA && DATA.entities.find(e => e.id === id);
  if (!entity || !chart) return false;
  chart.selectedId = id;
  chart.focusEntity(id, year, { width: 0.75, verticalScale: 3 });
  return true;
}

let mapSelectionSequence = 0;
function waitForMapIdle(map, callback, timeout = 2600) {
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    map.off('idle', finish);
    callback();
  };
  const timer = setTimeout(finish, timeout);
  map.once('idle', finish);
}

function selectEntityOnMapFromTable(id, year) {
  const entity = DATA && DATA.entities.find(e => e.id === id);
  const chrono = window.chronomap;
  const map = chrono && chrono.map;
  if (!entity || !map) return false;
  if (!chrono.ready) {
    const pending = ++mapSelectionSequence;
    map.once('load', () => {
      if (pending === mapSelectionSequence) selectEntityOnMapFromTable(id, year);
    });
    return true;
  }

  const sequence = ++mapSelectionSequence;
  const numericYear = Number(year);
  const targetYear = Number.isFinite(numericYear) ? Math.round(numericYear) : null;
  const needsYearChange = targetYear !== null && targetYear !== chrono.state.year;
  if (needsYearChange) chrono.setYear(targetYear);
  if (chrono.closeStatePopup) chrono.closeStatePopup();
  clearHighlight();

  const findAndFly = () => {
    if (sequence !== mapSelectionSequence) return;
    contourIndex = null;
    contourTries = 0;
    if (rebuildContourIndex() && flyToEntity(id, true, { popup: true })) return;

    // Query source features only covers loaded tiles. A quick world zoom loads
    // the country-boundary tiles even when the selected country was off-screen.
    if (map.getZoom() > 0.6) {
      waitForMapIdle(map, () => {
        if (sequence !== mapSelectionSequence) return;
        contourIndex = null;
        contourTries = 0;
        if (rebuildContourIndex()) flyToEntity(id, true, { popup: true });
      }, 3200);
      map.jumpTo({ center: [0, 20], zoom: 0.5 });
      return;
    }

    // At world zoom, give remote vector tiles one idle cycle to arrive.
    waitForMapIdle(map, () => {
      if (sequence !== mapSelectionSequence) return;
      contourIndex = null;
      contourTries = 0;
      if (rebuildContourIndex()) flyToEntity(id, true, { popup: true });
    }, 1800);
  };

  if (needsYearChange) waitForMapIdle(map, findAndFly);
  else findAndFly();
  return true;
}

/* ---------------------------------------------------------- даты */

function nearestIdx(year) {
  if (!dates.length) return -1;
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

/** Переход к ближайшему реальному году события относительно выбранной даты. */
function stepToEvent(direction) {
  if (!dates.length) return;
  const year = currentYear();
  let next = -1;
  if (direction < 0) {
    for (let i = dates.length - 1; i >= 0; i--) {
      if (dates[i] < year) { next = i; break; }
    }
  } else {
    next = dates.findIndex(date => date > year);
  }
  if (next >= 0) applyStep(next);
}

/** Все стрелки и свайп используют одну навигацию по соседним событиям. */
function applyStep(i) {
  if (!dates.length) return;
  i = Math.max(0, Math.min(dates.length - 1, i));
  const D = dates[i];
  const changed = D !== currentYear();
  idx = i;
  if (changed && window.chronomap) {
    suppress = true;
    try { window.chronomap.setYear(D); }
    finally { suppress = false; }
    clearHighlight();
  }
  if (chart) {
    try {
      const [a, b] = chart.visibleYears();
      if (D < a || D > b) centerTable(D);
    } catch (e) { /* chart ещё не готов */ }
  }
  render();
}

/* ---------------------------------------------------------- отрисовка */

function render() {
  const Y = currentYear();
  idx = nearestIdx(Y);
  const canPrev = dates.length > 0 && Y > dates[0];
  const canNext = dates.length > 0 && Y < dates[dates.length - 1];
  ['feed-prev', 'btn-back'].forEach(id => { const b = $('#' + id); if (b) b.disabled = !canPrev; });
  ['feed-next', 'btn-fwd'].forEach(id => { const b = $('#' + id); if (b) b.disabled = !canNext; });

  // центр — события выбранного дня (день-в-день, включая идущие)
  const evs = DATA.events
    .filter(e => e.year <= Y && Y <= (e.yearEnd || e.year))
    .sort((a, b) => a.year - b.year);
  $('#feed-date').textContent = formatYear(Y) + ' · событий: ' + evs.length;

  // По три ближайших события с каждой стороны, независимо от рамки масштаба таблицы.
  const before = DATA.events
    .filter(e => e.year < Y && (e.yearEnd || e.year) < Y)
    .sort((a, b) => b.year - a.year).slice(0, 3);
  const after = DATA.events
    .filter(e => e.year > Y)
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
      html += '<div class="feed-empty feed-empty-mid">В этот день событий нет — ближайшие события показаны слева и справа</div>';
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
  const sideEvent = e.target.closest('.feed-sil');
  if (sideEvent) {
    // Боковой силуэт только выбирает дату: статья открывается отдельным
    // кликом по карточке события после переноса в центр ленты.
    e.preventDefault();
    selectEventDate(sideEvent.dataset.id);
    return;
  }

  const card = e.target.closest('.feed-card, .feed-chip');
  if (!card) return;
  const btn = e.target.closest('.feed-to-map');
  if (btn) {
    e.stopPropagation();
    flyToEntity(card.dataset.id);
    return;
  }
  openItem(card.dataset.kind, card.dataset.id);
});

function selectEventDate(id) {
  const event = DATA.events.find(x => x.id === id);
  if (!event) return;
  const i = dates.indexOf(event.year);
  if (i >= 0) applyStep(i);
}

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
  return [
    norm(entity.name), norm(entity.label), norm(entity.nameOhm),
    ...(entity.aliases || []).map(norm),
  ].filter(k => k.length > 2);
}

/** Похожи ли названия: точное равенство или одно — начало другого (достаточно длинное). */
function namesMatch(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.length >= 6 && b.startsWith(a)) return true;
  if (b.length >= 6 && a.startsWith(b)) return true;
  return false;
}

function findEntity(contourName, year) {
  const n = norm(contourName);
  if (!n) return null;
  const matches = DATA.entities.filter(e => nameKeys(e).some(k => namesMatch(k, n)));
  const numericYear = Number(year);
  if (Number.isFinite(numericYear)) {
    const active = matches.find(e => e.start <= numericYear && e.end >= numericYear);
    if (active) return active;
  }
  return matches[0] || null;
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
  const queriedSources = new Set();
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
      const layer = map.getLayer(id);
      const srcId = layer && layer.source;
      const sourceLayer = layer && (layer.sourceLayer || layer['source-layer']);
      const sourceKey = srcId + ':' + (sourceLayer || '');
      if (srcId && !queriedSources.has(sourceKey)) {
        queriedSources.add(sourceKey);
        const params = sourceLayer ? { sourceLayer } : undefined;
        map.querySourceFeatures(srcId, params).forEach(add);   // и за пределами экрана
      }
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

function featureYear(value) {
  if (value != null && value !== '' && Number.isFinite(Number(value))) return Number(value);
  const match = /^(-?\d+)/.exec(String(value == null ? '' : value));
  return match ? Number(match[1]) : null;
}

function featuresFor(entity) {
  if (!contourIndex) return [];
  for (const k of nameKeys(entity)) {
    for (const [name, feats] of contourIndex) {
      if (!namesMatch(k, name)) continue;
      const year = currentYear();
      const active = feats.filter(f => {
        const props = f.properties || {};
        const start = featureYear(props.start_date);
        const end = featureYear(props.end_date);
        return (start === null || year >= start) && (end === null || year <= end);
      });
      return active.length ? active : feats;
    }
  }
  return [];
}

function featuresByExactName(name) {
  if (!contourIndex) return [];
  const n = norm(name);
  return contourIndex.get(n) || [];
}

/** Минимальная дуга долготы вокруг геометрии (обрабатывает антимеридиан). */
function longitudeBounds(values) {
  if (!values.length) return null;
  const xs = [...new Set(values.map(x => ((x % 360) + 360) % 360))].sort((a, b) => a - b);
  if (xs.length === 1) return [xs[0], xs[0]];
  let gap = -1, gapAt = 0;
  for (let i = 0; i < xs.length; i++) {
    const next = i === xs.length - 1 ? xs[0] + 360 : xs[i + 1];
    const size = next - xs[i];
    if (size > gap) { gap = size; gapAt = i; }
  }
  let west = xs[(gapAt + 1) % xs.length];
  let east = xs[gapAt];
  if (east < west) east += 360;
  while (west > 180) { west -= 360; east -= 360; }
  while (west < -180) { west += 360; east += 360; }
  return [west, east];
}

/** Перелёт к контуру сущности + подсветка. quiet — не дёргать ленту. */
function flyToEntity(id, quiet, options = {}) {
  const e = DATA.entities.find(x => x.id === id);
  if (!e || !contourIndex && !rebuildContourIndex()) return false;
  const feats = featuresFor(e);
  if (!feats.length) return false;
  showHighlight(feats);

  // Границы выбранного временного контура; дуга долгот учитывает переход
  // через 180°, иначе Россия и другие страны у антимеридиана ошибочно дают весь мир.
  const longitudes = [];
  let minY = Infinity, maxY = -Infinity;
  const walk = c => {
    if (typeof c[0] === 'number') {
      longitudes.push(c[0]);
      minY = Math.min(minY, c[1]);
      maxY = Math.max(maxY, c[1]);
    } else c.forEach(walk);
  };
  feats.forEach(f => f.geometry && walk(f.geometry.coordinates));

  const lng = longitudeBounds(longitudes);
  if (!lng || minY === Infinity) return false;
  const [west, east] = lng;
  const map = window.chronomap.map;
  const bounds = [[west, minY], [east, maxY]];
  const center = [(west + east) / 2, (minY + maxY) / 2];
  let zoom = map.getZoom();
  try {
    const camera = map.cameraForBounds(bounds, { padding: 28, maxZoom: 6.5 });
    if (camera && Number.isFinite(camera.zoom)) zoom = camera.zoom;
  } catch (e) { /* если bounds не поддержаны проекцией — используем текущий зум */ }
  zoom = Math.max(0.5, Math.min(6.5, zoom));
  map.flyTo({ center, zoom, duration: 1500, essential: true });
  if (options.popup && window.chronomap.showStatePopup) {
    window.chronomap.showStatePopup(feats[0], e, center);
  }
  return true;
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
    if (dx < 0) stepToEvent(1); else stepToEvent(-1);   // влево → позже, вправо → раньше
  }, { passive: true });
}

/* Поиск «⌖ на карту» по кнопке в ленте (делегирование уже выше) */
document.addEventListener('click', e => {
  const b = e.target.closest('.feed-to-map');
  if (!b) return;
  e.stopPropagation();
  flyToEntity(b.dataset.eid || b.closest('[data-id]')?.dataset.id);
});
