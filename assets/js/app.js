// Главная страница: загрузка данных, панель управления, подсказки, статьи.
import { Chart } from './chart.js';
import { formatYear, formatSpan, formatAxisYear, ticksForRange } from './scale.js';
import { ICON_LABELS } from './icons.js';
import { renderMarkdown, stripFrontmatter } from './md.js';
import { parseHistoricalYear } from './year-input.js';

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
  era: 'эпоха', nature: 'природный процесс', hominin: 'вид / линия гоминин',
};
const KIND_LABEL = { migration: 'переселение', invasion: 'вторжение', trade: 'торговля', diffusion: 'распространение' };

let DATA = null, chart = null;
let densityCache = null, densityCacheMode = null, densityCacheEntities = null;
let syncVerticalScaleControls = () => {};
let minimapDrawFrame = 0, pendingTableViewFrame = 0, pendingTableView = null;
let filterUpdateFrame = 0, filterNeedsRebuild = false, filterNeedsFit = false;

init();

async function init() {
  const res = await fetch('data/index.json', { cache: 'no-cache' });
  DATA = await res.json();
  window.DATA = DATA;

  chart = new Chart($('#chart'), DATA, {
    // На главной таблица использует ограниченное окно просмотра с панорамированием внутри полотна.
    autoHeight: !!document.querySelector('.table-zone'),
    onHover: showTip,
    onSelect: hit => {
      if (hit.kind === 'entity') {
        // Выбор в таблице управляет картой, но не зумом самой таблицы.
        if (window.CHRONO_LINK && window.CHRONO_LINK.selectEntityFromTable) {
          window.CHRONO_LINK.selectEntityFromTable(hit.obj.id, hit.year);
        }
      }
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
    onDateChange: year => { if (window.chronomap?.setYear) window.chronomap.setYear(year); },
  });
  window.chart = chart;   // удобно для отладки из консоли браузера
  buildFilters();
  buildLegend();
  wireToolbar();
  wireSearch();
  wirePanel();
  wireMinimap();
  wireYearJump();
  syncView();
  // MapLibre-скрипт загружен раньше модулей: можно подписаться сразу,
  // без периодического ожидания хука даты.
  if (window.chronomap && typeof window.chronomap.onYearChange === 'function') {
    window.chronomap.onYearChange(() => { drawMinimap(); chart.draw(); });
  }
  window.addEventListener('resize', () => drawMinimap());
  if (location.hash) openFromHash();
  window.addEventListener('hashchange', openFromHash);
  window.dispatchEvent(new Event('chrono:app-ready'));
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
      <div class="more">${regions.join(' · ')} — щёлкните, чтобы показать государство на карте</div>`;
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
  const minSpan = Math.min(chart.minVisibleYears, chart.scale.yearMax - chart.scale.yearMin);
  const maxSpan = Math.min(chart.maxVisibleYears, chart.scale.yearMax - chart.scale.yearMin);
  const spanFromSlider = value => maxSpan * Math.pow(minSpan / maxSpan, Number(value) / 1000);
  const spanToSlider = span => {
    const safe = Math.max(minSpan, Math.min(maxSpan, Number(span) || maxSpan));
    return maxSpan <= minSpan ? 0 : Math.round(1000 * Math.log(maxSpan / safe) / Math.log(maxSpan / minSpan));
  };
  const selectedYear = () => {
    const year = window.chronomap?.state?.year;
    if (Number.isFinite(year)) return year;
    const [a, b] = chart.visibleYears();
    return (a + b) / 2;
  };
  const zoomAroundDate = factor => {
    const [a, b] = chart.visibleYears();
    chart.setVisibleSpan((b - a) / factor, selectedYear(), 'zoom');
  };

  zr.addEventListener('input', () => chart.setVisibleSpan(spanFromSlider(zr.value), selectedYear(), 'zoom'));
  $('#zoomIn').onclick = () => zoomAroundDate(1.6);
  $('#zoomOut').onclick = () => zoomAroundDate(1 / 1.6);
  document.querySelectorAll('[data-span]').forEach(button => {
    button.onclick = () => {
      const span = button.dataset.span === 'all' ? maxSpan : Number(button.dataset.span);
      chart.setVisibleSpan(span, selectedYear(), 'zoom');
    };
  });

  const verticalRange = $('#verticalRange'), verticalOut = $('#verticalOut');
  const verticalMax = () => chart.verticalMaxScale();
  const sliderToVertical = value => Math.exp(Math.log(verticalMax()) * (Number(value) / 1000));
  const verticalToSlider = value => verticalMax() <= 1 ? 0
    : Math.round(1000 * Math.log(Math.max(1, value)) / Math.log(verticalMax()));
  const updateVerticalOut = () => {
    if (verticalOut) verticalOut.textContent = `×${chart.verticalScale.toFixed(1).replace('.', ',')}`;
    if (verticalRange) verticalRange.value = String(verticalToSlider(chart.verticalScale));
  };
  syncVerticalScaleControls = updateVerticalOut;
  verticalRange.addEventListener('input', () => {
    chart.setVerticalScale(sliderToVertical(verticalRange.value));
    updateVerticalOut();
  });
  $('#verticalZoomOut').onclick = () => {
    chart.setVerticalScale(chart.verticalScale / 1.25);
    updateVerticalOut();
  };
  $('#verticalZoomIn').onclick = () => {
    chart.setVerticalScale(chart.verticalScale * 1.25);
    updateVerticalOut();
  };

  updateVerticalOut();
  window.addEventListener('resize', updateVerticalOut);
  $('#chkLinear').onchange = e => {
    chart.setScaleMode(e.target.checked ? 'linear' : 'poster', 'zoom');
  };
  const togglePop = (id, btn) => {
    const pop = $('#' + id);
    pop.hidden = !pop.hidden;
    btn.classList.toggle('on', !pop.hidden);
    if (id === 'legend' && !pop.hidden) buildLegend();
  };
  $('#btnFilters').onclick = e => togglePop('filters', e.currentTarget);
  $('#btnLegend').onclick = e => togglePop('legend', e.currentTarget);
  document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => {
    $('#' + button.dataset.close).hidden = true;
    $('#btn' + button.dataset.close[0].toUpperCase() + button.dataset.close.slice(1)).classList.remove('on');
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      $('#filters').hidden = true; $('#legend').hidden = true; $('#results').hidden = true;
      closePanel();
      document.querySelectorAll('.btn.toggle').forEach(button => button.classList.remove('on'));
    }
    // На сфокусированной таблице стрелки панорамируют её, не меняя выбранный год.
    if (e.target !== $('#chart')) return;
    const delta = chart.plotW() * 0.25;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      chart.panByScroll(e.key === 'ArrowRight' ? delta : -delta, 0, 'pan');
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      chart.panByScroll(0, e.key === 'ArrowDown' ? 60 : -60, 'pan');
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1.5, 'zoom');
    } else if (e.key === '-') {
      e.preventDefault();
      chart.zoomAt(chart.plotX() + chart.plotW() / 2, 1 / 1.5, 'zoom');
    }
  });
  zr.value = String(spanToSlider(chart.visibleYears()[1] - chart.visibleYears()[0]));
  chart._spanToSlider = spanToSlider;
}

function wireYearJump() {
  const form = $('#year-jump-form');
  const input = $('#year-input');
  const era = $('#year-era');
  const error = $('#year-input-error');
  if (!form || !input || !era || !error) return;

  const moveYear = delta => {
    const map = window.chronomap;
    if (!map || !map.state || typeof map.setYear !== 'function') return;
    let next = map.state.year + delta;
    // В исторической нумерации года 0 нет: между 1 до н.э. и 1 н.э. перескакиваем его.
    if (map.state.year < 0 && next === 0) next = 1;
    else if (map.state.year > 0 && next === 0) next = -1;
    map.setYear(next);
  };
  $('#year-prev')?.addEventListener('click', () => moveYear(-1));
  $('#year-next')?.addEventListener('click', () => moveYear(1));

  const clearError = () => {
    error.textContent = '';
    input.removeAttribute('aria-invalid');
    era.removeAttribute('aria-invalid');
  };
  const updateInputLimit = () => {
    const limit = era.value === 'bce' ? Math.abs(chart.scale.yearMin) : chart.scale.yearMax;
    input.max = String(Math.floor(limit));
  };
  updateInputLimit();
  input.addEventListener('input', clearError);
  era.addEventListener('change', () => { updateInputLimit(); clearError(); });
  form.addEventListener('submit', e => {
    e.preventDefault();
    const year = parseHistoricalYear(input.value, era.value);
    const min = chart.scale.yearMin, max = chart.scale.yearMax;
    if (year == null) {
      error.textContent = 'Введите целый год от 1 и выберите эру: до н.э. или н.э.';
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      return;
    }
    if (year < min || year > max) {
      error.textContent = `Допустимый диапазон: ${formatYear(min)} — ${formatYear(max)}.`;
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      return;
    }
    if (!window.chronomap || typeof window.chronomap.setYear !== 'function') {
      error.textContent = 'Шкала ещё загружается. Попробуйте ещё раз.';
      input.focus();
      return;
    }
    clearError();
    window.chronomap.setYear(year);
    input.value = '';
  });
}

function syncView(_instance, source) {
  const [a, b] = chart.visibleYears();
  if (source === 'pan' || source === 'zoom' || source === 'navigate') {
    pendingTableView = {
      source,
      start: a,
      end: b,
      center: chart.yearOf(chart.plotX() + chart.plotW() / 2),
    };
    if (!pendingTableViewFrame) {
      pendingTableViewFrame = requestAnimationFrame(() => {
        pendingTableViewFrame = 0;
        const detail = pendingTableView;
        pendingTableView = null;
        if (detail) window.dispatchEvent(new CustomEvent('chrono:tableview', { detail }));
      });
    }
  }
  const spanLabel = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(b - a));
  $('#spanOut').textContent = `${spanLabel} лет на экране`;
  $('#status').textContent =
    `${formatYear(a, true)} — ${formatYear(b, true)} · объектов: ${DATA.meta.counts.entities}`;
  if (chart._spanToSlider) $('#zoomRange').value = chart._spanToSlider(b - a);
  syncVerticalScaleControls();
  drawMinimap();
  // рамка сдвинулась → в ленте обновить силуэты событий по краям
  if (window.FEED && window.FEED._refresh) window.FEED._refresh();
}

function queueFilterUpdate(rebuild, fitRows) {
  filterNeedsRebuild ||= rebuild;
  filterNeedsFit ||= fitRows;
  if (filterUpdateFrame) return;
  filterUpdateFrame = requestAnimationFrame(() => {
    filterUpdateFrame = 0;
    const doRebuild = filterNeedsRebuild;
    const doFitRows = filterNeedsFit;
    filterNeedsRebuild = false;
    filterNeedsFit = false;
    if (doRebuild) { chart.rebuild(); chart.clampView(); }
    if (doFitRows && chart.fitRows && !chart.autoHeight) chart.fitRowsToView();
    else chart.draw();
  });
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
  const fe = $('#fEras'); fe.innerHTML = '';
  for (const era of DATA.eras) {
    const b = el('button', '', era.name);
    b.style.background = era.color + '66';
    b.onclick = () => { chart.zoomToRange(era.start, era.end, 0.03, 'zoom'); syncView(); };
    fe.appendChild(b);
  }
  $('#filters').addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.region) {
      t.checked ? chart.filters.regions.add(t.dataset.region) : chart.filters.regions.delete(t.dataset.region);
      queueFilterUpdate(true, true);
    } else if (t.dataset.type) {
      t.checked ? chart.filters.types.add(t.dataset.type) : chart.filters.types.delete(t.dataset.type);
      queueFilterUpdate(true, false);
    }
  });
  const labelsToggle = $('#chkLabels');
  if (labelsToggle) labelsToggle.onchange = e => { chart.filters.showLabels = e.target.checked; chart.draw(); };
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
  const eras = $('#legendEras');
  for (const era of DATA.eras) {
    const b = el('button', '', `${era.name}`);
    b.style.background = era.color + '66';
    b.onclick = () => { chart.zoomToRange(era.start, era.end, 0.03, 'zoom'); syncView(); };
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
    chart.zoomToRange(obj.start, obj.end, 0.35, 'navigate');
    chart.scrollToLane(obj.spans[0].lane);
  } else if (kind === 'event') {
    chart.setVisibleSpan(Math.max(300, (obj.yearEnd || obj.year) - obj.year + 300), obj.year, 'navigate');
    chart.scrollToLane(obj.lane);
  } else if (kind === 'migration') {
    chart.zoomToRange(obj.start, obj.end, 0.3, 'navigate');
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
  if (!cv) return;
  let grab = null; // pointerId, смещение от указателя до выбранной даты и ширина окна
  let pendingU = null, rafId = 0;

  const uOf = e => {
    const r = cv.getBoundingClientRect();
    return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
  };
  const spanNow = () => {
    const s = chart.visibleYears()[1] - chart.visibleYears()[0];
    if (!Number.isFinite(s) || s <= 0) return 500;
    return Math.max(chart.minVisibleYears, Math.min(chart.maxVisibleYears, s));
  };
  const apply = u => {
    if (!grab) return;
    const y = Math.round(chart.scale.year(Math.max(0, Math.min(1, u))));
    chart.setVisibleSpan(grab.span, y);
    if (window.chronomap && window.chronomap.state) window.chronomap.setYear(y);
  };
  const queueApply = u => {
    pendingU = u;
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      const next = pendingU;
      pendingU = null;
      if (grab && next != null) apply(next);
    });
  };
  const flushApply = u => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    pendingU = null;
    if (grab) apply(u);
  };
  const finish = e => {
    if (!grab || e.pointerId !== grab.pointerId) return;
    if (Math.abs(e.clientX - grab.startX) > 3) grab.moved = true;
    if (grab.moved) flushApply(uOf(e) - grab.off);
    else {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0; pendingU = null;
    }
    const pointerId = grab.pointerId;
    grab = null;
    if (cv.hasPointerCapture && cv.hasPointerCapture(pointerId)) cv.releasePointerCapture(pointerId);
  };

  cv.addEventListener('pointerdown', e => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const u = uOf(e);
    const scale = chart.scale;
    const [va, vb] = chart.visibleYears();
    const sa = scale.unit(va), sb = scale.unit(vb);
    const inBox = u >= sa && u <= sb && (sb - sa) < 0.9;
    const anchor = window.chronomap?.state?.year ?? (va + vb) / 2;
    grab = {
      pointerId: e.pointerId,
      startX: e.clientX,
      moved: false,
      off: inBox ? u - scale.unit(anchor) : 0,
      span: spanNow(),
    };
    try { cv.setPointerCapture(e.pointerId); } catch (err) {}
    cv.focus({ preventScroll: true });
    if (!inBox) apply(u);
  });

  cv.addEventListener('pointermove', e => {
    if (!grab || e.pointerId !== grab.pointerId) return;
    if (Math.abs(e.clientX - grab.startX) > 3) grab.moved = true;
    if (grab.moved) queueApply(uOf(e) - grab.off);
  });
  cv.addEventListener('pointerup', finish);
  cv.addEventListener('pointercancel', e => {
    if (!grab || e.pointerId !== grab.pointerId) return;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0; pendingU = null; grab = null;
  });
  cv.addEventListener('lostpointercapture', e => {
    if (grab && e.pointerId === grab.pointerId) {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0; pendingU = null; grab = null;
    }
  });

  cv.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const direction = e.key === 'ArrowLeft' ? -1 : 1;
      if (window.FEED?.step) window.FEED.step(direction);
    } else if (e.key === 'PageUp' || e.key === 'PageDown') {
      e.preventDefault();
      const amount = Math.max(1, Math.round(spanNow() / 10));
      const direction = e.key === 'PageDown' ? 1 : -1;
      window.chronomap?.setYear(window.chronomap.state.year + direction * amount);
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      const year = e.key === 'Home' ? chart.scale.yearMin : chart.scale.yearMax;
      window.chronomap?.setYear(year);
    }
  });
  drawMinimap();
}

function getMinimapDensity() {
  const mode = chart.scale.mode;
  if (densityCache && densityCacheMode === mode && densityCacheEntities === DATA.entities) return densityCache;
  const N = 240;
  const counts = new Array(N).fill(0);
  for (const e of DATA.entities) {
    const a = Math.max(0, Math.min(N - 1, Math.floor(chart.scale.unit(e.start) * N)));
    const b = Math.max(0, Math.min(N - 1, Math.ceil(chart.scale.unit(e.end) * N)));
    for (let i = a; i <= b; i++) counts[i]++;
  }
  densityCache = { counts, max: Math.max(...counts, 1) };
  densityCacheMode = mode;
  densityCacheEntities = DATA.entities;
  return densityCache;
}

function updateMinimapA11y(cv, a, b) {
  if (!chart) return;
  const min = Math.round(chart.scale.yearMin);
  const max = Math.round(chart.scale.yearMax);
  const year = Math.round(window.chronomap?.state?.year ?? (a + b) / 2);
  cv.setAttribute('aria-valuemin', String(min));
  cv.setAttribute('aria-valuemax', String(max));
  cv.setAttribute('aria-valuenow', String(year));
  cv.setAttribute('aria-valuetext', `${formatYear(year)}; видимый диапазон: ${formatYear(a)} — ${formatYear(b)}`);
}

function drawMinimap() {
  if (minimapDrawFrame) return;
  minimapDrawFrame = requestAnimationFrame(() => {
    minimapDrawFrame = 0;
    renderMinimap();
  });
}

function renderMinimap() {
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
  // Плотность неизменяемой базы кэшируем; при перетаскивании меняются только рамка и дата.
  const { counts, max } = getMinimapDensity();
  const N = counts.length;
  ctx.beginPath();
  ctx.moveTo(0, H);
  for (let i = 0; i < N; i++) ctx.lineTo(i / (N - 1) * W, H - 3 - (counts[i] / max) * (H - 18));
  ctx.lineTo(W, H);
  ctx.closePath();
  ctx.fillStyle = 'rgba(70,90,120,0.28)'; ctx.fill();
  ctx.strokeStyle = 'rgba(70,90,120,0.6)'; ctx.lineWidth = 1; ctx.stroke();
  // Метки всей шкалы.
  ctx.font = '9px "Segoe UI", sans-serif'; ctx.fillStyle = '#7a7568'; ctx.textAlign = 'center';
  const yMin = DATA.meta?.yearMin ?? chart.scale.yearMin;
  const yMax = DATA.meta?.yearMax ?? chart.scale.yearMax;
  const ticks = ticksForRange(chart.scale, yMin, yMax, W, 46);
  let lastLabelRight = -Infinity;
  for (const tick of ticks) {
    const x = ux(tick.year);
    ctx.strokeStyle = 'rgba(0,0,0,0.12)';
    ctx.beginPath(); ctx.moveTo(x, 11); ctx.lineTo(x, H); ctx.stroke();
    const label = formatAxisYear(tick.year, tick.step);
    const labelWidth = ctx.measureText(label).width;
    if (x > 8 && x < W - 8 && x - labelWidth / 2 > lastLabelRight + 5) {
      ctx.fillText(label, x, H - 1);
      lastLabelRight = x + labelWidth / 2;
    }
  }
  const [a, b] = chart.visibleYears();
  const x0 = ux(a), x1 = ux(b);
  ctx.fillStyle = 'rgba(11,99,214,0.14)';
  ctx.fillRect(x0, 0, Math.max(2, x1 - x0), H);
  ctx.strokeStyle = '#0b63d6'; ctx.lineWidth = 1.5;
  ctx.strokeRect(x0 + .5, .5, Math.max(2, x1 - x0) - 1, H - 1);
  // Красная черта выбранной даты (только на главной, где есть карта с датой):
  // ровно на годе — при зажатии рамки к краю шкалы середина окошка ≠ дате,
  // при обычном зуме (рамка симметрична) она и есть середина окошка.
  if (window.chronomap) {
    const xc = Math.max(0, Math.min(W, ux(window.chronomap.state.year)));
    ctx.strokeStyle = '#d13b3b'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(xc, 0); ctx.lineTo(xc, H); ctx.stroke();
    ctx.fillStyle = '#d13b3b';
    ctx.beginPath();
    ctx.moveTo(xc - 5, 0); ctx.lineTo(xc + 5, 0); ctx.lineTo(xc, 7);
    ctx.closePath(); ctx.fill();
  }
  updateMinimapA11y(cv, a, b);
}
