// Лендинг «Хрониста»: эпохи, счётчики, события и поиск — из data/index.json.
// Данные те же, что у карты и таблицы, отдельного индекса не нужно.
import { formatYear, formatSpan } from './scale.js';
import SNAPSHOT from './landing-data.js';

const DATA_URL = 'data/index.json';

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const setText = (sel, value) => {
  const el = $(sel);
  if (el && value != null) el.textContent = value;
};

function entityHref(kind, id) {
  return `pages/entity.html?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`;
}

function mapHref(kind, id) {
  const p = { entity: 'e', event: 'v', migration: 'm', region: 'r', era: 'a' }[kind] || 'e';
  return `map.html#${p}/${encodeURIComponent(id)}`;
}


/* ---------------- пиктограммы эпох ---------------- */
// Ключ — id эпохи из data/index.json. Линейные SVG в стиле остальных иконок сайта.
const ERA_ICONS = {
  // Неолит — колос
  neo: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M16 28.5V6.4"/>
    <path d="M16 6.4c1.7 1 2.4 2.6 2.1 4.7-1.7-.4-2.5-2-2.1-4.7Z"/>
    <path d="M16 6.4c-1.7 1-2.4 2.6-2.1 4.7 1.7-.4 2.5-2 2.1-4.7Z"/>
    <path d="M16 12.6c2.1.5 3.4 1.9 3.7 4-2 .2-3.4-1-3.7-4Z"/>
    <path d="M16 12.6c-2.1.5-3.4 1.9-3.7 4 2 .2 3.4-1 3.7-4Z"/>
    <path d="M16 18.6c2.1.5 3.4 1.9 3.7 4-2 .2-3.4-1-3.7-4Z"/>
    <path d="M16 18.6c-2.1.5-3.4 1.9-3.7 4 2 .2 3.4-1 3.7-4Z"/>
  </svg>`,
  // Ранние цивилизации — зиккурат
  early_civ: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M3.5 27h25"/>
    <path d="M8 27v-6h16v6"/>
    <path d="M11 21v-5.5h10V21"/>
    <path d="M14 15.5V10h4v5.5"/>
    <path d="M16 10V6"/>
  </svg>`,
  // Бронзовый век — бронзовый клинок
  bronze: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M16 4.5c1.5 2 2.2 4.4 2.2 7.2v5.3h-4.4v-5.3c0-2.8.7-5.2 2.2-7.2Z"/>
    <path d="M11.6 17h8.8"/>
    <path d="M16 17v7"/>
    <path d="M14 24h4"/>
  </svg>`,
  // Железный век — наковальня кузнеца
  iron: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M3.5 26.5h25"/>
    <path d="M7.5 26.5v-3.6h17v3.6"/>
    <path d="M11 22.9 12.6 18h6.8l1.6 4.9"/>
    <path d="M7.5 15h17v-2.6h-12c-2.4 0-4.2 1-5 2.6Z"/>
    <path d="M24.5 12.4c1.6.2 2.6 1 3 2.4h-3"/>
  </svg>`,
  // Античность — античный храм
  axial: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M4 27.5h24"/>
    <path d="M3.5 13h25L16 5 3.5 13Z"/>
    <path d="M6.5 13v14M11.2 13v14M16 13v14M20.8 13v14M25.5 13v14"/>
  </svg>`,
  // Раннее Средневековье — крепость
  early_med: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M4 27V12h4V9h4v3h8V9h4v3h4v15"/>
    <path d="M12.5 27v-6.5a3.5 3.5 0 0 1 7 0V27"/>
    <path d="M2 27h28"/>
  </svg>`,
  // Высокое и позднее Средневековье — готический собор
  high_med: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M3.5 27.5h25"/>
    <path d="M9 27.5V12l2.2-3.6L13.4 12v15.5"/>
    <path d="M18.6 27.5V12l2.2-3.6L23 12v15.5"/>
    <path d="M14.6 27.5v-6h2.8v6"/>
    <path d="M16 8.4V4.5"/>
  </svg>`,
  // Возрождение — циркуль
  renaissance: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <circle cx="16" cy="6" r="1.8"/>
    <path d="M16 7.8 10 25.5"/>
    <path d="M16 7.8 22 25.5"/>
    <path d="M11.4 21.4a8.8 8.8 0 0 0 9.2 0"/>
  </svg>`,
  // Новое время — каравелла
  early_mod: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M16 4.5v19"/>
    <path d="M16 7.5c-4.6 2.7-6.6 6.7-6.6 12.2H16V7.5Z"/>
    <path d="M18 10c3.7 2.2 5.3 5.5 5.3 9.7H18V10Z"/>
    <path d="M4.5 24h23L24 28H8l-3.5-4Z"/>
  </svg>`,
  // Индустриальная эпоха — завод с трубой
  modern: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M3 27h26"/>
    <path d="M4 27V17l6 3.2V17l6 3.2V14h4v13"/>
    <path d="M22 14V6h3.2v8"/>
    <path d="M26.8 9.4c1.7-.6 2.1-2 1.7-3.5"/>
  </svg>`,
  // Новейшее время — космическая ракета
  contemp: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M16 4c2.9 3.4 4.4 7 4.4 10.9l-1.9 4.1h-5l-1.9-4.1C11.6 11 13.1 7.4 16 4Z"/>
    <circle cx="16" cy="11.4" r="1.6"/>
    <path d="M11.5 16.6 8 21l4-1"/>
    <path d="M20.5 16.6 24 21l-4-1"/>
    <path d="M13.4 21.6c.6 3.1 1.5 5.2 2.6 6.4 1.1-1.2 2-3.3 2.6-6.4"/>
  </svg>`,
};


// Порядок и состав полосы эпох на главной. Даты берём из data/index.json,
// если эпоха там есть; «Возрождение» — витринная ступень лендинга
// (в базе эпох она не выделена отдельным периодом и открывается на 1500 г.).
const ERA_STRIP = [
  { id: 'neo',        name: 'Неолит' },
  { id: 'early_civ',  name: 'Ранние цивилизации' },
  { id: 'bronze',     name: 'Бронзовый век' },
  { id: 'iron',       name: 'Железный век' },
  { id: 'axial',      name: 'Античность' },
  { id: 'early_med',  name: 'Раннее Средневековье' },
  { id: 'high_med',   name: 'Высокое и позднее Средневековье' },
  { id: 'renaissance', name: 'Возрождение', start: 1400, end: 1600, year: 1500, virtual: true },
  { id: 'early_mod',  name: 'Новое время' },
  { id: 'modern',     name: 'Индустриальная эпоха' },
  { id: 'contemp',    name: 'Новейшее время' },
];

// на случай новых эпох в базе — запасной набор
const ERA_ICON_FALLBACKS = [ERA_ICONS.neo, ERA_ICONS.early_civ, ERA_ICONS.bronze, ERA_ICONS.iron];

/* ---------------- эпохи ---------------- */
function renderEras(eras) {
  const track = $('#lpEraTrack');
  if (!track) return;

  const byId = new Map((eras || []).map(e => [e.id, e]));

  const items = ERA_STRIP.map((item, i) => {
    const fromData = byId.get(item.id);
    const name = item.name || fromData?.name || '';
    const start = fromData?.start ?? item.start;
    const end = fromData?.end ?? item.end;
    const span = (start != null && end != null) ? formatSpan(start, end) : '';
    const icon = ERA_ICONS[item.id] || ERA_ICON_FALLBACKS[i % ERA_ICON_FALLBACKS.length];

    // реальная эпоха открывает её на карте/таблице, витринная — карту на нужный год
    const href = fromData
      ? mapHref('era', item.id)
      : `map.html?y=${encodeURIComponent(item.year ?? '')}`;

    const hint = fromData ? 'показать эпоху на карте' : 'открыть карту на этом периоде';
    return `<a class="lp-epoch" href="${href}" title="${esc(name)}${span ? ' · ' + esc(span) : ''} — ${hint}">
        <span class="lp-epoch-icon">${icon}</span>
        <span class="lp-epoch-name">${esc(name)}</span>
        ${span ? `<span class="lp-epoch-date">${esc(span)}</span>` : ''}
      </a>`;
  }).join('');

  track.insertAdjacentHTML('beforeend', items);
}

function wireEraArrows() {
  const track = $('#lpEraTrack');
  if (!track) return;
  document.querySelectorAll('[data-epoch]').forEach(btn => {
    btn.addEventListener('click', () => {
      const step = Math.max(220, track.clientWidth * 0.6);
      track.scrollBy({ left: btn.dataset.epoch === 'next' ? step : -step, behavior: 'smooth' });
    });
  });
}

/* ---------------- последние события ---------------- */
function renderEvents(events) {
  const list = $('#lpEvents');
  if (!list || !events?.length) return;

  const latest = events
    .slice()
    .sort((a, b) => (b.year - a.year) || a.name.localeCompare(b.name))
    .slice(0, 4);

  list.innerHTML = latest.map(ev => {
    const year = ev.yearEnd ? formatSpan(ev.year, ev.yearEnd) : formatYear(ev.year, true);
    const summary = (ev.summary || '').replace(/\s+/g, ' ').trim();
    return `<li class="lp-event">
      <a href="${mapHref('event', ev.id)}" title="${esc(ev.name)} — показать на карте">
        <span class="lp-event-thumb">${esc(year)}</span>
        <span class="lp-event-body">
          <span class="lp-event-date">${esc(formatYear(ev.year))}${ev.yearEnd ? ' — ' + esc(formatYear(ev.yearEnd)) : ''}</span>
          <span class="lp-event-name">${esc(ev.name)}</span>
          ${summary ? `<span class="lp-event-sum">${esc(summary)}</span>` : ''}
        </span>
        <span class="lp-event-arrow" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none"><path d="m9.5 6 6 6-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
      </a>
    </li>`;
  }).join('');
}

/* ---------------- счётчики ---------------- */
function renderCounts(data) {
  const counts = data.meta?.counts || {};
  const entities = counts.entities ?? data.entities?.length ?? 0;
  const events = counts.events ?? data.events?.length ?? 0;
  const regions = counts.regions ?? data.regions?.length ?? 0;
  const lanes = counts.lanes ?? (data.regions || []).reduce((n, r) => n + (r.lanes?.length || 0), 0);

  setText('#lpFactEntities', entities.toLocaleString('ru-RU'));
  setText('#lpFactEvents', events.toLocaleString('ru-RU'));
  setText('#lpFactRegions', regions);
  setText('#lpFactLanes', lanes);
  setText('#lpCardEntities', `${entities.toLocaleString('ru-RU')}+`);

  const note = $('.lp-events-note');
  if (note) {
    const eras = counts.eras ?? data.eras?.length ?? 0;
    note.innerHTML = `<span id="lpFactEvents">${events.toLocaleString('ru-RU')}</span> событие в базе · ${eras} эпох · отмечены на карте`;
  }
}

/* ---------------- поиск ---------------- */
function wireSearch(data) {
  const input = $('#lpSearch');
  const box = $('#lpResults');
  if (!input || !box) return;

  const KIND = { entity: 'статья', event: 'событие', region: 'регион', era: 'эпоха' };
  const index = [
    ...(data.entities || []).map(x => ({ kind: 'entity', id: x.id, name: x.name, meta: x.type })),
    ...(data.events || []).map(x => ({
      kind: 'event', id: x.id, name: x.name,
      meta: formatYear(x.year, true),
    })),
    ...(data.regions || []).map(x => ({ kind: 'region', id: x.id, name: x.name, meta: `${x.lanes?.length || 0} суб-региона` })),
    ...(data.eras || []).map(x => ({ kind: 'era', id: x.id, name: x.name, meta: formatSpan(x.start, x.end) })),
  ];

  const close = () => { box.hidden = true; box.innerHTML = ''; };

  const render = q => {
    const query = q.trim().toLowerCase();
    if (query.length < 2) return close();
    const hits = index
      .filter(x => (x.name || '').toLowerCase().includes(query))
      .slice(0, 8);
    if (!hits.length) {
      box.innerHTML = '<div class="lp-search-empty">Ничего не найдено — попробуйте другое слово.</div>';
      box.hidden = false;
      return;
    }
    box.innerHTML = hits.map(x => `<a href="${entityHref(x.kind, x.id)}">
        <span class="nm">${esc(x.name)}</span>
        <span class="meta">${esc(KIND[x.kind] || '')}${x.meta ? ' · ' + esc(x.meta) : ''}</span>
      </a>`).join('');
    box.hidden = false;
  };

  input.addEventListener('input', () => render(input.value));
  input.addEventListener('focus', () => { if (input.value.trim().length >= 2) render(input.value); });
  input.addEventListener('keydown', e => { if (e.key === 'Escape') { input.blur(); close(); } });
  document.addEventListener('click', e => {
    if (!$('#lpSearchWrap')?.contains(e.target)) close();
  });
}

/* ---------------- запуск ---------------- */
wireEraArrows();

/* ---------------- загрузка данных ---------------- */
async function loadIndex() {
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return { ...(await res.json()), source: 'live' };
  } catch (err) {
    // офлайн-режим (например, предпросмотр без сети): берём снимок из landing-data.js
    console.info('Хрониста: data/index.json недоступен, показываю сохранённый снимок', err);
    return {
      meta: { counts: SNAPSHOT.counts },
      eras: SNAPSHOT.eras,
      events: SNAPSHOT.events,
      entities: SNAPSHOT.entities,
      regions: [],
      source: 'snapshot',
    };
  }
}

const data = await loadIndex();
renderEras(data.eras);
renderEvents(data.events);
renderCounts(data);
wireSearch(data);
