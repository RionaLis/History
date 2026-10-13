// Главная страница: загрузка данных, панель управления, подсказки, статьи.
import { Chart } from './chart.js';
import { formatYear, formatSpan } from './scale.js';
import { drawIcon, ICON_LABELS } from './icons.js';
import { renderMarkdown, stripFrontmatter } from './md.js';

const $ = s => document.querySelector(s);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};

const TYPE_LABEL = {
  state: 'государство', empire: 'империя', people: 'народ',
  culture: 'культура', polity: 'политии', colony: 'колония', confed: 'союз',
};
const KIND_LABEL = { migration: 'переселение', invasion: 'вторжение', trade: 'торговля', diffusion: 'распространение' };

let DATA = null, chart = null;

init();

async function init() {
  const res = await fetch('data/index.json', { cache: 'no-cache' });
  DATA = await res.json();
  window.DATA = DATA;

  chart = new Chart($('#chart'), DATA, {
    onHover: showTip,
    onSelect: hit => {
      if (hit.kind === 'entity') openDoc(hit.obj, 'entity');
      else if (hit.kind === 'event') openDoc(hit.obj, 'event');
      else if (hit.kind === 'migration') openDoc(hit.obj, 'migration');
      else if (hit.kind === 'lane') {
        const r = DATA.regions.find(r => r.id === hit.obj.regionId);
        if (r) openDoc(r, 'region');
      } else if (hit.kind === 'era') {
        openDoc(hit.obj, 'era');
      }
    },
    onView: syncView,
  });
  chart.fitRowsToView();
  window.chart = chart;   // удобно для отладки из консоли браузера
  buildFilters();
  buildLegend();
  wireToolbar();
  wireSearch();
  wirePanel();
  wireMinimap();
  syncView();
  window.addEventListener('resize', () => { drawMinimap(); });
  if (location.hash) openFromHash();
  window.addEventListener('hashchange', openFromHash);
}

/* ------------------------------------------------ подсказка */
function showTip(hit, ev) {
  const tip = $('#tip');
  if (!hit || !ev || !['entity', 'event', 'migration', 'lane', 'era'].includes(hit.kind)) {
    tip.hidden = true; return;
  }
  let html = '';
  if (hit.kind === 'entity') {
    const e = hit.obj;
    const regions = e.regions.map(id => (DATA.regions.find(r => r.id === id) || {}).short).filter(Boolean);
    html = `<h5>${e.name}</h5>
      <div class="dates">${TYPE_LABEL[e.type] || e.type} · ${formatSpan(e.start, e.end)}</div>
      <p>${e.summary || ''}</p>
      <div class="more">${regions.join(' · ')} — щёлкните для подробной статьи</div>`;
  } else if (hit.kind === 'event') {
    const e = hit.obj;
    const when = e.yearEnd ? formatSpan(e.year, e.yearEnd) : formatYear(e.year);
    html = `<h5>${e.name}</h5><div class="dates">${when} · ${ICON_LABELS[e.icon] || ''}</div>
      <p>${e.summary || ''}</p><div class="more">щёлкните для подробной статьи</div>`;
  } else if (hit.kind === 'migration') {
    const m = hit.obj;
    html = `<h5>${m.name}</h5>
      <div class="dates">${KIND_LABEL[m.kind] || m.kind} · ${formatSpan(m.start, m.end)}</div>
      <p>${m.summary || ''}</p>`;
  } else if (hit.kind === 'lane') {
    html = `<h5>${hit.obj.name}</h5><div class="dates">${hit.obj.regionName}</div>
      <div class="more">щёлкните — обзор региона</div>`;
  } else if (hit.kind === 'era') {
    html = `<h5>${hit.obj.name}</h5><div class="dates">${formatSpan(hit.obj.start, hit.obj.end)}</div>
      <div class="more">двойной клик — показать эпоху целиком</div>`;
  }
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 16, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}

/* ------------------------------------------------ тулбар */
function wireToolbar() {
  const zr = $('#zoomRange');
  const kToSlider = k => Math.round(1000 * Math.log(k) / Math.log(260));
  const sliderToK = v => Math.pow(260, v / 1000);
  zr.addEventListener('input', () => {
    const c = (chart.visibleYears()[0] + chart.visibleYears()[1]) / 2;
    chart.view.k = sliderToK(+zr.value);
    chart.clampView(); chart.centerOn(c);
  });
  $('#zoomIn').onclick = () => chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1.6);
  $('#zoomOut').onclick = () => chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1 / 1.6);
  document.querySelectorAll('[data-span]').forEach(b => {
    b.onclick = () => {
      const v = b.dataset.span;
      if (v === 'all') { chart.view.k = 1; chart.view.ux = 0; chart.draw(); syncView(); }
      else chart.setVisibleSpan(+v);
      syncView();
    };
  });
  $('#rowRange').addEventListener('input', e => chart.setRowUnit(+e.target.value));
  $('#fitRows').onclick = () => { chart.fitRowsToView(); $('#rowRange').value = Math.round(chart.rowUnit); };
  $('#chkLinear').onchange = e => {
    const c = (chart.visibleYears()[0] + chart.visibleYears()[1]) / 2;
    chart.scale.setMode(e.target.checked ? 'linear' : 'poster');
    chart.centerOn(c); drawMinimap();
  };
  const togglePop = (id, btn) => {
    const pop = $('#' + id);
    pop.hidden = !pop.hidden;
    btn.classList.toggle('on', !pop.hidden);
    if (id === 'legend' && !pop.hidden) buildLegend();
  };
  $('#btnFilters').onclick = e => togglePop('filters', e.currentTarget);
  $('#btnLegend').onclick = e => togglePop('legend', e.currentTarget);
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => {
    $('#' + b.dataset.close).hidden = true;
    $('#btn' + b.dataset.close[0].toUpperCase() + b.dataset.close.slice(1)).classList.remove('on');
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      $('#filters').hidden = true; $('#legend').hidden = true; $('#results').hidden = true;
      closePanel();
      document.querySelectorAll('.btn.toggle').forEach(b => b.classList.remove('on'));
    }
    if (e.target.tagName === 'INPUT') return;
    const step = chart.plotW() * 0.25 / chart.contentW();
    if (e.key === 'ArrowRight') { chart.view.ux += step; chart.clampView(); chart.draw(); syncView(); }
    if (e.key === 'ArrowLeft') { chart.view.ux -= step; chart.clampView(); chart.draw(); syncView(); }
    if (e.key === 'ArrowDown') { chart.view.vy += 60; chart.clampView(); chart.draw(); }
    if (e.key === 'ArrowUp') { chart.view.vy -= 60; chart.clampView(); chart.draw(); }
    if (e.key === '+' || e.key === '=') chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1.5);
    if (e.key === '-') chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1 / 1.5);
  });
  $('#zoomRange').value = kToSlider(chart.view.k);
  chart._kToSlider = kToSlider;
}

function syncView() {
  const [a, b] = chart.visibleYears();
  $('#spanOut').textContent = `${Math.round(b - a)} лет на экране`;
  $('#status').textContent =
    `${formatYear(a, true)} — ${formatYear(b, true)} · объектов: ${DATA.meta.counts.entities}, ` +
    `событий: ${DATA.meta.counts.events}`;
  if (chart._kToSlider) $('#zoomRange').value = chart._kToSlider(chart.view.k);
  drawMinimap();
}

/* ------------------------------------------------ фильтры */
function buildFilters() {
  const fr = $('#fRegions'); fr.innerHTML = '';
  for (const r of DATA.regions) {
    const lab = el('label', '', `<input type="checkbox" checked data-region="${r.id}">
      <span class="sw" style="background:${r.color}"></span>${r.short}`);
    fr.appendChild(lab);
  }
  const types = [...new Set(DATA.entities.map(e => e.type))];
  const ft = $('#fTypes'); ft.innerHTML = '';
  for (const t of types) {
    const n = DATA.entities.filter(e => e.type === t).length;
    ft.appendChild(el('label', '', `<input type="checkbox" checked data-type="${t}">
      ${TYPE_LABEL[t] || t} <span class="tagline">(${n})</span>`));
  }
  const fi = $('#fIcons'); fi.innerHTML = '';
  for (const ic of DATA.icons) {
    const n = DATA.events.filter(e => e.icon === ic.id).length;
    if (!n) continue;   // типы без событий не показываем
    fi.appendChild(el('label', '', `<input type="checkbox" checked data-icon="${ic.id}">
      ${ICON_LABELS[ic.id] || ic.name} <span class="tagline">(${n})</span>`));
  }
  const fe = $('#fEras'); fe.innerHTML = '';
  for (const era of DATA.eras) {
    const b = el('button', '', era.name);
    b.style.background = era.color + '66';
    b.onclick = () => { chart.zoomToRange(era.start, era.end, 0.03); syncView(); };
    fe.appendChild(b);
  }
  $('#filters').addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.region) {
      t.checked ? chart.filters.regions.add(t.dataset.region) : chart.filters.regions.delete(t.dataset.region);
      chart.rebuild(); if (chart.fitRows) chart.fitRowsToView(); else chart.draw();
    } else if (t.dataset.type) {
      t.checked ? chart.filters.types.add(t.dataset.type) : chart.filters.types.delete(t.dataset.type);
      chart.rebuild(); chart.draw();
    } else if (t.dataset.icon) {
      t.checked ? chart.filters.iconTypes.add(t.dataset.icon) : chart.filters.iconTypes.delete(t.dataset.icon);
      chart.draw();
    }
  });
  $('#chkEvents').onchange = e => { chart.filters.showEvents = e.target.checked; chart.draw(); };
  $('#chkMig').onchange = e => { chart.filters.showMigrations = e.target.checked; chart.draw(); };
  $('#chkLabels').onchange = e => { chart.filters.showLabels = e.target.checked; chart.draw(); };
  document.querySelectorAll('[data-all],[data-none]').forEach(a => {
    a.onclick = ev => {
      ev.preventDefault();
      const on = a.hasAttribute('data-all');
      const grp = a.dataset.all || a.dataset.none;
      const sel = { regions: '[data-region]', types: '[data-type]', icons: '[data-icon]' }[grp];
      document.querySelectorAll('#filters ' + sel).forEach(cb => {
        cb.checked = on;
        cb.dispatchEvent(new Event('change', { bubbles: true }));
      });
    };
  });
}

/* ------------------------------------------------ легенда */
function buildLegend() {
  const box = $('#legendIcons');
  if (box.dataset.ready) return;
  box.dataset.ready = '1';
  for (const ic of DATA.icons) {
    const row = el('div', 'row');
    const cv = el('canvas');
    cv.width = 48; cv.height = 48;
    const cx = cv.getContext('2d');
    cx.setTransform(2, 0, 0, 2, 0, 0);
    drawIcon(cx, ic.id, 12, 12, 9, { halo: false });
    row.appendChild(cv);
    row.appendChild(el('span', '', ICON_LABELS[ic.id] || ic.name));
    box.appendChild(row);
  }
  const lines = $('#legendLines');
  const styles = [['migration', 'переселение народа'], ['invasion', 'вторжение, завоевание'],
                  ['trade', 'торговая сеть']];
  for (const [kind, name] of styles) {
    const row = el('div', 'row');
    const cv = el('canvas'); cv.width = 110; cv.height = 24;
    cv.style.width = '55px'; cv.style.height = '12px';
    const cx = cv.getContext('2d');
    cx.setTransform(2, 0, 0, 2, 0, 0);
    cx.strokeStyle = { migration: '#5a4632', invasion: '#9c2b2b', trade: '#1f6f6a' }[kind];
    cx.lineWidth = 2;
    cx.setLineDash({ migration: [6, 4], invasion: [], trade: [2, 3] }[kind]);
    cx.beginPath(); cx.moveTo(2, 6); cx.lineTo(48, 6); cx.stroke();
    cx.setLineDash([]);
    cx.beginPath(); cx.moveTo(53, 6); cx.lineTo(44, 2); cx.lineTo(44, 10); cx.closePath();
    cx.fillStyle = cx.strokeStyle; cx.fill();
    row.appendChild(cv); row.appendChild(el('span', '', name));
    lines.appendChild(row);
  }
  const eras = $('#legendEras');
  for (const era of DATA.eras) {
    const b = el('button', '', `${era.name}`);
    b.style.background = era.color + '66';
    b.onclick = () => { chart.zoomToRange(era.start, era.end, 0.03); syncView(); };
    eras.appendChild(b);
  }
}

/* ------------------------------------------------ поиск */
function wireSearch() {
  const inp = $('#search'), box = $('#results');
  let items = [];
  const index = [
    ...DATA.entities.map(e => ({ id: e.id, kind: 'entity', name: e.name, obj: e,
      meta: `${TYPE_LABEL[e.type] || e.type} · ${formatSpan(e.start, e.end)}`,
      hay: (e.name + ' ' + (e.aliases || []).join(' ') + ' ' + (e.summary || '')).toLowerCase() })),
    ...DATA.events.map(e => ({ id: e.id, kind: 'event', name: e.name, obj: e,
      meta: `событие · ${formatYear(e.year, true)}`,
      hay: (e.name + ' ' + (e.summary || '')).toLowerCase() })),
    ...DATA.migrations.map(m => ({ id: m.id, kind: 'migration', name: m.name, obj: m,
      meta: `переселение · ${formatSpan(m.start, m.end)}`,
      hay: (m.name + ' ' + (m.summary || '')).toLowerCase() })),
    ...DATA.regions.map(r => ({ id: r.id, kind: 'region', name: r.name, obj: r,
      meta: 'регион', hay: r.name.toLowerCase() })),
  ];
  let sel = 0;
  const render = () => {
    box.innerHTML = '';
    items.slice(0, 40).forEach((it, i) => {
      const d = el('div', 'item' + (i === sel ? ' sel' : ''),
        `<div class="nm">${it.name}</div><div class="meta">${it.meta}</div>`);
      d.onclick = () => { choose(it); };
      box.appendChild(d);
    });
    box.hidden = !items.length;
  };
  const choose = it => {
    box.hidden = true;
    inp.blur();
    focusObject(it.kind, it.obj);
    openDoc(it.obj, it.kind);
  };
  inp.addEventListener('input', () => {
    const q = inp.value.trim().toLowerCase();
    chart.filters.query = q;
    if (q.length < 2) {
      items = []; chart.highlightIds = null; chart.draw(); render(); return;
    }
    items = index.filter(i => i.hay.includes(q)).sort((a, b) => {
      const ai = a.name.toLowerCase().indexOf(q), bi = b.name.toLowerCase().indexOf(q);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.name.length - b.name.length;
    });
    sel = 0;
    chart.highlightIds = new Set(items.map(i => i.id));
    chart.draw();
    render();
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, items.length - 1); render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
    if (e.key === 'Enter' && items[sel]) choose(items[sel]);
    if (e.key === 'Escape') { box.hidden = true; chart.highlightIds = null; chart.draw(); }
  });
  document.addEventListener('click', e => {
    if (!$('.search').contains(e.target)) box.hidden = true;
  });
}

function focusObject(kind, obj) {
  if (kind === 'entity') {
    chart.selectedId = obj.id;
    chart.zoomToRange(obj.start, obj.end, 0.35);
    chart.scrollToLane(obj.spans[0].lane);
  } else if (kind === 'event') {
    chart.setVisibleSpan(Math.max(300, (obj.yearEnd || obj.year) - obj.year + 300), obj.year);
    chart.scrollToLane(obj.lane);
  } else if (kind === 'migration') {
    chart.zoomToRange(obj.start, obj.end, 0.3);
    chart.scrollToLane(obj.points[0][1]);
  } else if (kind === 'region') {
    const first = obj.lanes[0];
    if (first) chart.scrollToLane(first.id);
  }
  chart.draw();
  syncView();
}

/* ------------------------------------------------ панель статьи */
let currentDoc = null;

function wirePanel() {
  $('#panelClose').onclick = closePanel;
  $('#panelFocus').onclick = () => {
    if (currentDoc) focusObject(currentDoc.kind, currentDoc.obj);
  };
  $('#panelBody').addEventListener('click', e => {
    const a = e.target.closest('a.wikilink');
    if (!a) return;
    e.preventDefault();
    const name = a.dataset.wiki.toLowerCase();
    const hit = DATA.entities.find(x => x.name.toLowerCase() === name)
      || DATA.events.find(x => x.name.toLowerCase() === name)
      || DATA.regions.find(x => x.name.toLowerCase() === name || x.short.toLowerCase() === name)
      || DATA.migrations.find(x => x.name.toLowerCase() === name);
    if (hit) {
      const kind = DATA.entities.includes(hit) ? 'entity'
        : DATA.events.includes(hit) ? 'event'
        : DATA.regions.includes(hit) ? 'region' : 'migration';
      openDoc(hit, kind); focusObject(kind, hit);
    }
  });
}

function closePanel() {
  $('#panel').hidden = true;
  chart.selectedId = null;
  currentDoc = null;
  history.replaceState(null, '', location.pathname + location.search);
  chart.draw();
}

async function openDoc(obj, kind) {
  currentDoc = { obj, kind };
  const panel = $('#panel');
  panel.hidden = false;
  $('#panelTitle').textContent = obj.name;
  $('#panelRaw').href = obj.path || '#';
  const body = $('#panelBody');
  body.innerHTML = '<p class="tagline">Загрузка…</p>';
  const prefix = { entity: 'e', event: 'v', migration: 'm', region: 'r', era: 'a' }[kind] || 'e';
  history.replaceState(null, '', `#${prefix}/${obj.id}`);
  if (kind === 'entity') chart.selectedId = obj.id;
  chart.draw();

  let html = '';
  if (obj.path) {
    try {
      const r = await fetch(obj.path, { cache: 'no-cache' });
      if (!r.ok) throw new Error(r.status);
      const { body: md } = stripFrontmatter(await r.text());
      html = renderMarkdown(md);
    } catch (err) {
      html = `<p class="tagline">Не удалось загрузить <code>${obj.path}</code>.</p>`;
    }
  }
  body.innerHTML = badges(obj, kind) + html + related(obj, kind);
}

function badges(obj, kind) {
  const b = [];
  if (kind === 'entity') {
    b.push(TYPE_LABEL[obj.type] || obj.type);
    b.push(formatSpan(obj.start, obj.end));
    for (const rid of obj.regions || []) {
      const r = DATA.regions.find(x => x.id === rid);
      if (r) b.push(r.short);
    }
  } else if (kind === 'event') {
    b.push(ICON_LABELS[obj.icon] || obj.icon);
    b.push(obj.yearEnd ? formatSpan(obj.year, obj.yearEnd) : formatYear(obj.year));
  } else if (kind === 'migration') {
    b.push(KIND_LABEL[obj.kind] || obj.kind);
    b.push(formatSpan(obj.start, obj.end));
  } else if (kind === 'region') {
    b.push('регион'); b.push(`${obj.lanes.length} суб-региона`);
  } else if (kind === 'era') {
    b.push('эпоха'); b.push(formatSpan(obj.start, obj.end));
  }
  return `<div class="panel-badges">${b.map(t => `<span class="badge">${t}</span>`).join('')}</div>`;
}

function related(obj, kind) {
  let links = [];
  if (kind === 'entity') {
    const lanes = new Set(obj.spans.map(s => s.lane));
    links = DATA.events
      .filter(e => lanes.has(e.lane) && e.year >= obj.start - 30 && e.year <= obj.end + 30)
      .slice(0, 10)
      .map(e => ({ obj: e, kind: 'event', label: `${formatYear(e.year, true)} — ${e.name}` }));
  } else if (kind === 'event') {
    const lane = obj.lane;
    links = DATA.entities
      .filter(e => e.spans.some(s => s.lane === lane) && obj.year >= e.start && obj.year <= e.end)
      .slice(0, 10)
      .map(e => ({ obj: e, kind: 'entity', label: e.name }));
  } else if (kind === 'region') {
    links = DATA.entities.filter(e => e.region === obj.id)
      .sort((a, b) => a.start - b.start).slice(0, 24)
      .map(e => ({ obj: e, kind: 'entity', label: `${e.name}` }));
  }
  if (!links.length) return '';
  const title = kind === 'entity' ? 'События этого времени'
    : kind === 'event' ? 'Государства и народы в это время' : 'Объекты региона';
  const html = links.map(l =>
    `<a class="badge" href="#" data-rel="${l.kind}:${l.obj.id}">${l.label}</a>`).join('');
  setTimeout(() => {
    document.querySelectorAll('#panelBody [data-rel]').forEach(a => {
      a.onclick = ev => {
        ev.preventDefault();
        const [kind, id] = a.dataset.rel.split(':');
        const coll = { entity: DATA.entities, event: DATA.events, region: DATA.regions,
                       migration: DATA.migrations }[kind];
        const o = coll.find(x => x.id === id);
        if (o) { openDoc(o, kind); focusObject(kind, o); }
      };
    });
  });
  return `<h2>${title}</h2><div class="relnav">${html}</div>`;
}

function openFromHash() {
  const m = /^#([evmra])\/(.+)$/.exec(location.hash);
  if (!m) return;
  const kind = { e: 'entity', v: 'event', m: 'migration', r: 'region', a: 'era' }[m[1]];
  const coll = { entity: DATA.entities, event: DATA.events, migration: DATA.migrations,
                 region: DATA.regions, era: DATA.eras }[kind];
  const o = coll.find(x => x.id === m[2]);
  if (o) { openDoc(o, kind); focusObject(kind, o); }
}

/* ------------------------------------------------ обзорная полоса */
function wireMinimap() {
  const cv = $('#minimap');
  let drag = false;
  const toYear = e => {
    const r = cv.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    return chart.scale.year(u);
  };
  cv.addEventListener('mousedown', e => { drag = true; chart.centerOn(toYear(e)); syncView(); });
  window.addEventListener('mousemove', e => { if (drag) { chart.centerOn(toYear(e)); syncView(); } });
  window.addEventListener('mouseup', () => drag = false);
  drawMinimap();
}

function drawMinimap() {
  const cv = $('#minimap');
  if (!cv || !chart) return;
  const dpr = devicePixelRatio || 1;
  const r = cv.getBoundingClientRect();
  cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = r.width, H = r.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#f6f3ec'; ctx.fillRect(0, 0, W, H);
  const ux = y => chart.scale.unit(y) * W;
  for (const era of DATA.eras) {
    ctx.fillStyle = era.color + 'cc';
    ctx.fillRect(ux(era.start), 0, ux(era.end) - ux(era.start), 11);
  }
  // плотность объектов по времени
  const N = 240;
  const counts = new Array(N).fill(0);
  for (const e of DATA.entities) {
    const a = Math.max(0, Math.floor(chart.scale.unit(e.start) * N));
    const b = Math.min(N - 1, Math.ceil(chart.scale.unit(e.end) * N));
    for (let i = a; i <= b; i++) counts[i]++;
  }
  const max = Math.max(...counts, 1);
  ctx.beginPath();
  ctx.moveTo(0, H);
  for (let i = 0; i < N; i++) ctx.lineTo(i / (N - 1) * W, H - 3 - (counts[i] / max) * (H - 18));
  ctx.lineTo(W, H);
  ctx.closePath();
  ctx.fillStyle = 'rgba(70,90,120,0.28)'; ctx.fill();
  ctx.strokeStyle = 'rgba(70,90,120,0.6)'; ctx.lineWidth = 1; ctx.stroke();
  // метки тысячелетий
  ctx.font = '9px "Segoe UI", sans-serif'; ctx.fillStyle = '#7a7568'; ctx.textAlign = 'center';
  for (let y = -3000; y <= 2000; y += 500) {
    const x = ux(y);
    ctx.strokeStyle = 'rgba(0,0,0,0.12)';
    ctx.beginPath(); ctx.moveTo(x, 11); ctx.lineTo(x, H); ctx.stroke();
    if (y % 1000 === 0) ctx.fillText(y === 0 ? '0' : (y < 0 ? '−' + (-y / 1000) + 'т' : y), x, H - 1);
  }
  const [a, b] = chart.visibleYears();
  const x0 = ux(a), x1 = ux(b);
  ctx.fillStyle = 'rgba(11,99,214,0.14)';
  ctx.fillRect(x0, 0, Math.max(2, x1 - x0), H);
  ctx.strokeStyle = '#0b63d6'; ctx.lineWidth = 1.5;
  ctx.strokeRect(x0 + .5, .5, Math.max(2, x1 - x0) - 1, H - 1);
}
