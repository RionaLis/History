/**
 * Хронокарта — основной скрипт.
 * Ничего править не обязательно: все настройки — в js/config.js.
 * (Код бесплатен, как и данные OpenHistoricalMap, лицензия MIT.)
 */
(function () {
  'use strict';

  var C = window.CHRONO;

  /* ======================== Утилиты ======================== */

  function $(sel) { return document.querySelector(sel); }

  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  /** «331 до н.э.» / «1492» — для большой надписи. */
  function fmtYear(y) {
    if (y <= 0) return Math.max(1, -y) + ' до н.э.';
    return String(y);
  }

  /** «331 дн.э.» — короткий вариант для бейджей. */
  function fmtYearShort(y) {
    if (y <= 0) return Math.max(1, -y) + ' дн.э.';
    return String(y);
  }

  /** Разбор даты вида «1917-11-07», «1917-11», «1917», «-0065». */
  function fmtDate(s) {
    if (s == null || s === '') return null;
    var m = /^(-?)(\d+)(?:-(\d\d))?(?:-(\d\d))?$/.exec(String(s));
    if (!m) return String(s); // нестандартная запись — показываем как есть
    var bc = m[1] === '-';
    var y = parseInt(m[2], 10);
    if (bc) return y + ' до н.э.';
    if (y === 0) return '1 до н.э.';
    if (!m[3]) return String(y);
    if (!m[4]) return m[3] + '.' + y;
    return m[4] + '.' + m[3] + '.' + y;
  }

  /** Стабильный «псевдослучайный» пастельный цвет по названию. */
  function hashColor(name) {
    var h = 5381;
    for (var i = 0; i < name.length; i++) h = ((h << 5) + h + name.charCodeAt(i)) >>> 0;
    var hue = h % 360;
    var light = 68 + (h >> 8) % 10; // 68–77%
    return 'hsl(' + hue + ', 44%, ' + light + '%)';
  }

  /* =============== Шкала: год <-> позиция ================== */

  var SEG = (function () {
    var segs = [], cum = 0, total = 0, i;
    for (i = 0; i < C.timelineSegments.length; i++) {
      var s = C.timelineSegments[i];
      segs.push({ from: s.from, to: s.to, weight: s.weight, cum: cum });
      cum += s.weight;
    }
    total = cum;
    return { segs: segs, total: total };
  })();

  function yearToPos(year) {
    year = clamp(year, C.minYear, C.maxYear);
    var segs = SEG.segs, s;
    for (var i = 0; i < segs.length; i++) {
      s = segs[i];
      if (year <= s.to || i === segs.length - 1) {
        var t = (year - s.from) / (s.to - s.from);
        t = clamp(t, 0, 1);
        return (s.cum + t * s.weight) / SEG.total;
      }
    }
    return 1;
  }

  function posToYear(pos) {
    pos = clamp(pos, 0, 1);
    var p = pos * SEG.total, segs = SEG.segs;
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      if (p <= s.cum + s.weight || i === segs.length - 1) {
        var t = (p - s.cum) / s.weight;
        t = clamp(t, 0, 1);
        return s.from + t * (s.to - s.from);
      }
    }
    return C.maxYear;
  }

  function windowForYear(y) {
    var W = C.eventWindows;
    for (var i = 0; i < W.length; i++) if (y <= W[i].untilYear) return W[i].window;
    return W[W.length - 1].window;
  }

  /* ========================= Состояние ===================== */

  var state = {
    year: C.defaultYear,
    pos: yearToPos(C.defaultYear),
    projection: C.defaultView.projection,
    playing: false,
    tab: 'events'   // активная вкладка панели: events | people
  };

  // Параметры ссылки: ?y=-331&v=globe&lat=..&lon=..&z=..
  (function readUrl() {
    var q = new URLSearchParams(location.search);
    var y = parseInt(q.get('y'), 10);
    if (!isNaN(y)) state.year = clamp(y, C.minYear, C.maxYear);
    var v = q.get('v');
    if (v === 'globe' || v === 'mercator') state.projection = v;
    state.pos = yearToPos(state.year);
    state.urlLat = parseFloat(q.get('lat'));
    state.urlLon = parseFloat(q.get('lon'));
    state.urlZ = parseFloat(q.get('z'));
  })();

  var eventsData = null;          // FeatureCollection из assets/map/data/events.geojson
  var peopleData = null;          // список персон из assets/map/data/people.json
  var modernData = null;          // линии современных границ (Natural Earth)
  var yearHooks = [];             // уведомления о смене года (мост к ленте/таблице)
  var styleReady = false;
  var firstIdle = false;
  var lastFilterAt = 0;
  var lastFilteredYear = null;
  var lastEventsFilterAt = 0;
  var lastEventsFilterYear = null;
  var eventsFilterTimer = null;
  var panelRenderAt = 0;
  var panelRenderTimer = null;

  /* ========================= Элементы ====================== */

  var elYear = $('#year-display');
  var elSlider = $('#year-slider');
  var elTicks = $('#ticks');
  var elPlay = $('#btn-play');
  var elPanelList = $('#events-list');
  var elPeopleList = $('#people-list');
  var elPanelYear = $('#panel-year');
  var elFab = $('#events-fab');
  var elLoader = $('#loader');
  var elError = $('#error-banner');

  /* ========================== Карта ======================== */

  var center = C.defaultView.center;
  if (!isNaN(state.urlLon) && !isNaN(state.urlLat)) center = [state.urlLon, state.urlLat];
  var zoom = C.defaultView.zoom;
  if (!isNaN(state.urlZ)) zoom = clamp(state.urlZ, 0.5, 16);

  var map = new maplibregl.Map({
    container: 'map',
    style: 'assets/map/style/map-style.json',
    center: center,
    zoom: zoom,
    minZoom: 0.5,
    maxZoom: 16,
    attributionControl: false,
    fadeDuration: 200
  });
  // Проекцию применим, когда стиль загрузится (см. styledata/load ниже):
  // до этого момента setProjection в MapLibre бросает ошибку.

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'bottom-right');
  map.addControl(new maplibregl.AttributionControl({
    compact: true,
    customAttribution: 'Данные: <a href="https://www.openhistoricalmap.org/copyright" target="_blank" rel="noopener">OpenHistoricalMap</a>'
  }), 'bottom-left');

  /* ==================== Фильтр по году ===================== */

  var pendingFilterTimer = null;

  var lastFilterError = null;

  function doFilter() {
    try {
      map.filterByDate(String(state.year));
      lastFilterAt = Date.now();
      lastFilteredYear = state.year;
      lastFilterError = null;
    } catch (e) {
      lastFilterError = String(e && e.message || e);
      console.warn('filterByDate:', e);
    }
  }

  function applyDateFilter(force) {
    if (!styleReady || typeof map.filterByDate !== 'function') return;
    if (force) {
      clearTimeout(pendingFilterTimer);
      pendingFilterTimer = null;
      doFilter();
      return;
    }
    if (state.year === lastFilteredYear && !pendingFilterTimer) return;
    var elapsed = Date.now() - lastFilterAt;
    if (elapsed >= C.filterThrottleMs) {
      doFilter();
    } else if (!pendingFilterTimer) {
      // «хвостовой» вызов: последний год после бурной перетаскивки не потеряется
      pendingFilterTimer = setTimeout(function () {
        pendingFilterTimer = null;
        doFilter();
      }, C.filterThrottleMs - elapsed);
    }
  }

  /* ===================== Слои событий ====================== */

  function addEventsLayers() {
    if (map.getLayer('events-dots')) return;
    map.addSource('events', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({
      id: 'events-dots',
      type: 'circle',
      source: 'events',
      paint: {
        'circle-color': [
          'match', ['get', 'kind'],
          'битва', C.eventKindColors['битва'] || '#c0392b',
          'договор', C.eventKindColors['договор'] || '#2f6fb5',
          'основание', C.eventKindColors['основание'] || '#2e9e63',
          'культура', C.eventKindColors['культура'] || '#d9a441',
          C.eventKindColors['другое'] || '#8e63c7'
        ],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 3.2, 4, 4.5, 8, 6, 12, 7],
        'circle-stroke-color': '#fff8ee',
        'circle-stroke-width': 1.2,
        'circle-opacity': 0.95
      }
    });
    if (eventsData) map.getSource('events').setData(eventsData);
    updateEventsFilter();
  }

  function updateEventsFilter() {
    if (eventsFilterTimer) { clearTimeout(eventsFilterTimer); eventsFilterTimer = null; }
    if (!styleReady || !map.getLayer('events-dots')) return;
    var w = windowForYear(state.year), y = state.year;
    map.setFilter('events-dots', [
      'all',
      ['>=', ['get', 'year'], y - w],
      ['<=', ['get', 'year'], y + w]
    ]);
    lastEventsFilterAt = Date.now();
    lastEventsFilterYear = y;
  }

  // При перетаскивании временной шкалы применяем фильтр карты не чаще,
  // чем задано в config.js; отложенный вызов всегда использует последний год.
  function scheduleEventsFilter(force) {
    if (!styleReady || !map.getLayer('events-dots')) return;
    if (!force && state.year === lastEventsFilterYear) return;
    var delay = C.filterThrottleMs - (Date.now() - lastEventsFilterAt);
    if (force || delay <= 0) {
      clearTimeout(eventsFilterTimer);
      eventsFilterTimer = null;
      updateEventsFilter();
    } else if (!eventsFilterTimer) {
      eventsFilterTimer = setTimeout(function () {
        eventsFilterTimer = null;
        updateEventsFilter();
      }, delay);
    }
  }

  /* ============ Слой современных границ (Natural Earth) ==== */

  function addModernBorders() {
    if (map.getLayer('modern-borders')) return;
    map.addSource('modern-borders', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });
    map.addLayer({
      id: 'modern-borders',
      type: 'line',
      source: 'modern-borders',
      layout: { visibility: 'none' }, // по умолчанию выключен (см. меню «Слои»)
      paint: {
        'line-color': '#5b54a0',
        'line-dasharray': [3, 2],
        'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.7, 6, 1.1, 10, 1.5],
        'line-opacity': 0.85
      }
    });
    if (modernData) map.getSource('modern-borders').setData(modernData);
  }

  /* ==================== Панель «В это время» ================ */

  function visibleEvents() {
    if (!eventsData || !eventsData.features) return [];
    var y = state.year, w = windowForYear(y);
    var list = [];
    for (var i = 0; i < eventsData.features.length; i++) {
      var f = eventsData.features[i];
      var ey = f.properties.year;
      if (ey >= y - w && ey <= y + w) list.push({ idx: i, f: f, diff: Math.abs(ey - y) });
    }
    list.sort(function (a, b) { return a.diff - b.diff; });
    return list.slice(0, C.maxEventsInPanel);
  }

  /* ===================== Панель: люди ====================== */

  /** Цвет точки по роли (чтобы панель читалась бегло). */
  function roleColor(role) {
    var r = String(role || '').toLowerCase();
    if (/философ|учёный|ученый|астроном|конструктор|изобрет|исследов|математ|биолог|врач|физик|химик|программист|географ|лётчик|летчик/.test(r)) return '#2f6fb5';
    if (/художник|живопис|поэт|писател|драматург|композитор|музык|режисс|скульптор|гуманист|певец|певиц|артист|телевед|балерин|поэз/.test(r)) return '#8e63c7';
    if (/фараон|император|царь|княз|королев|король|президент|премьер|халиф|хан|полковод|министр|политич|диктатор|правозащит|предприним|завоеват|генерал|чекист/.test(r)) return '#c0392b';
    if (/религиоз|святой|пророк|апостол|патриарх|митрополит|лама|гуру|расколов|игумен/.test(r)) return '#2e9e63';
    return '#d9a441';
  }

  /** Склонение: «52 года», «21 год», «45 лет». */
  function yearsWord(n) {
    var d10 = n % 10, d100 = n % 100;
    if (d10 === 1 && d100 !== 11) return 'год';
    if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return 'года';
    return 'лет';
  }

  /** Строка жизненного пути: «1452–1519», «563–483 до н.э.», «570 — н.в.». */
  function fmtLifespan(p) {
    var a = p.birth, b = p.death, pre = p.approx ? '≈ ' : '';
    if (b == null) return pre + (a <= 0 ? (-a) + ' до н.э. — н.в.' : a + ' — н.в.');
    if (a <= 0 && b <= 0) return pre + (-a) + '–' + (-b) + ' до н.э.';
    if (a <= 0) return pre + (-a) + ' до н.э. — ' + b;
    return pre + a + '–' + b;
  }

  function aliveAt(p, y) {
    return p.birth <= y && (p.death == null || y <= p.death);
  }

  /** Живые на выбранный год (порядок — значимость, лимит — peopleMax). */
  function visiblePeople() {
    if (!peopleData) return [];
    var y = state.year, out = [], i;
    for (i = 0; i < peopleData.length; i++) {
      var p = peopleData[i];
      if (aliveAt(p, y)) out.push({ p: p, age: y - p.birth });
      if (out.length >= C.peopleMax) break;
    }
    return out;
  }

  function renderPeople() {
    if (!elPeopleList) return;
    var list = visiblePeople();
    var h = '', i;
    for (i = 0; i < list.length; i++) {
      var p = list[i].p, age = list[i].age;
      var badge = age + ' ' + yearsWord(age);
      h += '<button class="ev-item person-item" data-pi="' + i + '">' +
           '<span class="ev-dot" style="background:' + roleColor(p.role) + '"></span>' +
           '<span class="ev-body">' +
             '<span class="ev-year">' + esc(badge) + '</span>' +
             '<span class="ev-title">' + esc(p.name) + '</span>' +
             '<span class="person-meta">' + esc(fmtLifespan(p)) + ' · ' + esc(p.role || '') + '</span>' +
             '<span class="person-note">' + esc(p.note || '') + '</span>' +
           '</span>' +
         '</button>';
    }
    if (!peopleData) h = '<p class="ev-empty">Список персон не загрузился. Проверьте файл data/people.json.</p>';
    else if (!list.length) h = '<p class="ev-empty">В ' + fmtYear(state.year) + ' среди персон никого нет в живых.</p>';
    elPeopleList.innerHTML = h;
  }

  /** Название эпохи для года (список — C.eras). */
  function eraForYear(y) {
    var E = C.eras || [];
    for (var i = 0; i < E.length; i++) if (y <= E[i].untilYear) return E[i].name;
    return E.length ? E[E.length - 1].name : '';
  }

  /** Переключение вкладок События / Люди. */
  function setTab(tab) {
    state.tab = (tab === 'people') ? 'people' : 'events';
    var isEv = state.tab === 'events';
    var tEv = $('#tab-events'), tPe = $('#tab-people');
    if (tEv) { tEv.classList.toggle('is-active', isEv); tEv.setAttribute('aria-selected', String(isEv)); }
    if (tPe) { tPe.classList.toggle('is-active', !isEv); tPe.setAttribute('aria-selected', String(!isEv)); }
    if (elPanelList) elPanelList.classList.toggle('is-hidden', !isEv);
    if (elPeopleList) elPeopleList.classList.toggle('is-hidden', isEv);
    renderPanel();
  }

  function renderPanel() {
    if (!elPanelList) return;
    if (panelRenderTimer) { clearTimeout(panelRenderTimer); panelRenderTimer = null; }

    var y = state.year;
    var w = windowForYear(y);

    // — события —
    if (!eventsData) {
      elPanelList.innerHTML = '<p class="ev-empty">События не загрузились. Проверьте файл data/events.geojson.</p>';
    } else {
      var list = visibleEvents();
      if (!list.length) {
        elPanelList.innerHTML = '<p class="ev-empty">Рядом с этим годом событий нет.<br>Покрутите шкалу времени.</p>';
      } else {
        var html = '';
        for (var i = 0; i < list.length; i++) {
          var p = list[i].f.properties;
          var color = C.eventKindColors[p.kind] || C.eventKindColors['другое'] || '#8e63c7';
          html +=
            '<button class="ev-item" data-idx="' + list[i].idx + '">' +
              '<span class="ev-dot" style="background:' + color + '"></span>' +
              '<span class="ev-body">' +
                '<span class="ev-year">' + esc(fmtYearShort(p.year)) + '</span>' +
                '<span class="ev-title">' + esc(p.title) + '</span>' +
              '</span>' +
            '</button>';
        }
        elPanelList.innerHTML = html;
      }
      var evN = Math.min(list.length, C.maxEventsInPanel);
      var evCount = $('#tab-events-n');
      if (evCount) evCount.textContent = evN;
    }

    // — люди —
    renderPeople();
    var pN = visiblePeople().length;
    var pCount = $('#tab-people-n');
    if (pCount) pCount.textContent = pN;

    // — подзаголовок: год · эпоха · окно —
    var sub = fmtYear(y) + ' · ' + eraForYear(y);
    if (state.tab === 'events') sub += ' · события ±' + w + ' лет';
    else sub += ' · живых в списке: ' + pN;
    elPanelYear.textContent = sub;

    // — мобильная кнопка —
    if (elFab) {
      elFab.textContent = (state.tab === 'events' ? 'События · ' : 'Люди · ') +
        (state.tab === 'events' ? (eventsData ? Math.min(visibleEvents().length, C.maxEventsInPanel) : 0) : pN);
    }
    panelRenderAt = Date.now();
  }

  function schedulePanelRender(force) {
    if (force || Date.now() - panelRenderAt >= C.filterThrottleMs) {
      clearTimeout(panelRenderTimer);
      panelRenderTimer = null;
      renderPanel();
    } else if (!panelRenderTimer) {
      panelRenderTimer = setTimeout(function () {
        panelRenderTimer = null;
        renderPanel();
      }, C.filterThrottleMs - (Date.now() - panelRenderAt));
    }
  }

  /* — связка с лентой: мост window.CHRONO_LINK (assets/js/feed.js) — */
  function linkBtn(kind, id, label) {
    if (!window.CHRONO_LINK || !id) return '';
    return '<button class="pop-feed-link" data-fk="' + kind + ':' + esc(id) + '">→ ' + esc(label) + '</button>';
  }

  function wirePopupLinks(popup) {
    if (!window.CHRONO_LINK) return;
    var node = popup.getElement && popup.getElement();
    if (!node) return;
    node.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.pop-feed-link') : null;
      if (!b) return;
      var parts = b.getAttribute('data-fk').split(':');
      window.CHRONO_LINK.openItem(parts[0], parts[1]);
    });
  }

  function showEventPopup(f) {
    var p = f.properties;
    var color = C.eventKindColors[p.kind] || C.eventKindColors['другое'] || '#8e63c7';
    var link = '';
    if (window.CHRONO_LINK) {
      var hit = window.CHRONO_LINK.findEvent(p.title);
      if (hit) link = linkBtn('event', hit.id, 'в ленту: ' + hit.name);
    }
    var html =
      '<div class="pop-event">' +
        '<span class="pop-kind" style="background:' + color + '">' + esc(p.kind || 'событие') + '</span>' +
        '<h4>' + esc(p.title) + '</h4>' +
        '<div class="pop-year">' + esc(fmtYear(p.year)) + '</div>' +
        '<p>' + esc(p.text || '') + '</p>' +
        link +
      '</div>';
    var popup = new maplibregl.Popup({ maxWidth: '280px', offset: 12 })
      .setLngLat(f.geometry.coordinates)
      .setHTML(html)
      .addTo(map);
    wirePopupLinks(popup);
  }

  function flyToEvent(f) {
    map.flyTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 5), duration: 1600 });
    showEventPopup(f);
  }

  /* ================ Клик по государству ==================== */

  var LEVELS = { 1: 'Империя, союз', 2: 'Государство', 3: 'Регион', 4: 'Область, провинция' };

  function statePopupHtml(p) {
    var name = p.name_ru || p.name || 'Без названия';
    var s = fmtDate(p.start_date);
    var e = fmtDate(p.end_date);
    var dates = (s || '…') + ' — ' + (e || 'по настоящее время');
    var lvl = LEVELS[p.admin_level] || '';
    var html =
      '<div class="pop-state">' +
        '<h4>' + esc(name) + '</h4>' +
        '<div class="pop-dates">' + esc(dates) + '</div>';
    if (lvl) html += '<div class="pop-level">' + esc(lvl) + '</div>';
    if (p.disputed && p.disputed !== 'no') {
      html += '<div class="pop-disputed">Граница оспаривается</div>';
    }
    html += '</div>';
    return html;
  }

  function existingLayers(ids) {
    var out = [];
    for (var i = 0; i < ids.length; i++) if (map.getLayer(ids[i])) out.push(ids[i]);
    return out;
  }

  /* ==================== Обработчики карты ================== */

  /* ==================== Инициализация стиля ================ */

  var interactionsBound = false;

  // Вызывается и на styledata (раньше), и на load (страховка).
  // Идемпотентна: повторный вызов не ломает и не дублирует обработчики.
  function initStyleDependent() {
    applyProjectionToMap();
    styleReady = true;
    applyDateFilter(true);
    try { addEventsLayers(); } catch (e) { console.warn('addEventsLayers:', e); }
    try { addModernBorders(); } catch (e) { console.warn('addModernBorders:', e); }
    Object.keys(LAYER_GROUPS).forEach(function (cbId) {
      try { applyLayerGroup(cbId); } catch (e) {}
    });
    renderPanel();
    if (!interactionsBound) {
      bindMapInteractions();
      interactionsBound = true;
    }
  }

  map.once('styledata', initStyleDependent);
  map.once('load', initStyleDependent);

  var styleFetchFailed = false;

  map.on('idle', function () {
    if (!firstIdle) { firstIdle = true; hideLoader(); }
    scheduleColorRefresh();
  });

  map.on('error', function (e) {
    if (e && e.error) {
      var msg = String(e.error.message || e.error);
      console.warn('Карта:', msg);
      // Пока стиль не готов — сетевая ошибка означает, что не загрузился
      // сам style.json (тайлы ещё не запрашивались). Имеет смысл повторить.
      if (!styleReady && /fetch|network|ajax/i.test(msg)) styleFetchFailed = true;
    }
  });

  var syncUrl = debounce(function () {
    try {
      var c = map.getCenter();
      var q = new URLSearchParams();
      q.set('y', String(state.year));
      q.set('v', state.projection);
      q.set('lat', c.lat.toFixed(2));
      q.set('lon', c.lng.toFixed(2));
      q.set('z', map.getZoom().toFixed(1));
      history.replaceState(null, '', location.pathname + '?' + q.toString() + location.hash);
    } catch (e) { /* например, при открытии файла напрямую */ }
  }, 400);

  map.on('moveend', function () {
    syncUrl();
    scheduleColorRefresh(); // цвета государств пересчитываем и после передвижения карты
  });

  function bindMapInteractions() {
    // курсор-указатель
    ['events-dots', 'fill-countries', 'fill-empires', 'fill-regions'].forEach(function (id) {
      if (!map.getLayer(id)) return;
      map.on('mouseenter', id, function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, function () { map.getCanvas().style.cursor = ''; });
    });

    map.on('click', function (e) {
      try {
        // 1. события
        var evLayers = existingLayers(['events-dots']);
        if (evLayers.length) {
          var evs = map.queryRenderedFeatures(e.point, { layers: evLayers });
          if (evs.length) { showEventPopup(evs[0]); return; }
        }
        // 2. государства: сначала заливки, потом линии
        var order = ['fill-empires', 'fill-countries', 'fill-regions',
                     'borders-empires', 'borders-countries', 'borders-regions'];
        var fs = map.queryRenderedFeatures(e.point, { layers: existingLayers(order) });
        if (fs.length) {
          var sp = fs[0].properties;
          var shtml = statePopupHtml(sp);
          if (window.CHRONO_LINK) {
            var ent = window.CHRONO_LINK.findEntity(sp.name_ru || sp.name);
            if (ent) shtml += linkBtn('entity', ent.id, 'в ленту: ' + ent.name);
          }
          var popup2 = new maplibregl.Popup({ maxWidth: '280px', offset: 8 })
            .setLngLat(e.lngLat)
            .setHTML(shtml)
            .addTo(map);
          wirePopupLinks(popup2);
        }
      } catch (err) { console.warn('click:', err); }
    });
  }

  /* ====== Цвета государств: стабильный цвет по названию ===== */

  var lastColorKey = null;

  function refreshFillColors() {
    if (!styleReady) return;
    var fills = existingLayers(['fill-empires', 'fill-countries', 'fill-regions']);
    if (!fills.length) return;
    var visible = fills.filter(function (id) {
      return map.getLayoutProperty(id, 'visibility') !== 'none';
    });
    if (!visible.length) return;

    var feats;
    try { feats = map.queryRenderedFeatures(undefined, { layers: visible }); }
    catch (e) { return; }

    var names = {};
    var count = 0;
    for (var i = 0; i < feats.length && count < 500; i++) {
      var n = feats[i].properties && feats[i].properties.name;
      if (n && !names[n]) { names[n] = true; count++; }
    }
    var list = Object.keys(names).sort();
    var key = list.join('\u0001');
    if (key === lastColorKey) return;
    lastColorKey = key;

    // Пока на экране нет подписанных заливок — просто базовый цвет
    if (!list.length) {
      fills.forEach(function (id) {
        try { map.setPaintProperty(id, 'fill-color', '#d8cfbc'); } catch (e) {}
      });
      return;
    }

    var expr = ['case'];
    for (var j = 0; j < list.length; j++) {
      expr.push(['==', ['get', 'name'], list[j]], hashColor(list[j]));
    }
    expr.push('#d8cfbc');

    fills.forEach(function (id) {
      try { map.setPaintProperty(id, 'fill-color', expr); }
      catch (e) { console.warn('fill-color (' + id + '):', e); }
    });
  }

  var scheduleColorRefresh = debounce(refreshFillColors, 350);

  /* ====================== Шкала времени ==================== */

  function setYear(y, opts) {
    opts = opts || {};
    y = Math.round(clamp(y, C.minYear, C.maxYear));
    var changed = y !== state.year;
    state.year = y;
    if (!opts.keepPos) state.pos = yearToPos(y);
    if (!opts.fromSlider && elSlider) elSlider.value = String(Math.round(state.pos * 10000));

    elYear.textContent = fmtYear(y);
    if (changed || opts.force) {
      for (var hi = 0; hi < yearHooks.length; hi++) {
        try { yearHooks[hi](y); } catch (e) { console.warn('yearHook:', e); }
      }
    }

    applyDateFilter(opts.force);
    if (changed || opts.force) scheduleEventsFilter(opts.force);
    if (changed || opts.force) schedulePanelRender(opts.force);
    scheduleColorRefresh(); // цвета — после смены года (дебаунс внутри)
    syncUrl();
  }

  function setFromSlider() {
    if (!elSlider) return;
    stopPlay();
    var pos = parseInt(elSlider.value, 10) / 10000;
    state.pos = pos;
    setYear(posToYear(pos), { keepPos: true, fromSlider: true });
  }

  if (elSlider) elSlider.addEventListener('input', setFromSlider);

  if (elSlider) elSlider.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault(); stopPlay(); setYear(state.year - 1);
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault(); stopPlay(); setYear(state.year + 1);
    } else if (e.key === 'Home') {
      e.preventDefault(); stopPlay(); setYear(C.minYear);
    } else if (e.key === 'End') {
      e.preventDefault(); stopPlay(); setYear(C.maxYear);
    }
  });

  $('#btn-back').addEventListener('click', function () {
    stopPlay();
    if (window.FEED && typeof window.FEED.step === 'function') window.FEED.step(-1);
  });
  $('#btn-fwd').addEventListener('click', function () {
    stopPlay();
    if (window.FEED && typeof window.FEED.step === 'function') window.FEED.step(1);
  });

  /* =================== Воспроизведение (▶) ================= */

  var rafId = null, lastTs = null;

  function tick(ts) {
    if (!state.playing) return;
    if (lastTs == null) lastTs = ts;
    var dt = Math.min(0.1, (ts - lastTs) / 1000);
    lastTs = ts;
    state.pos += C.playSpeed * dt;
    if (state.pos >= 1) {
      state.pos = 1;
      setYear(posToYear(1), { keepPos: true });
      stopPlay();
      return;
    }
    setYear(posToYear(state.pos), { keepPos: true });
    rafId = requestAnimationFrame(tick);
  }

  function startPlay() {
    if (state.pos >= 1) state.pos = 0;
    state.playing = true;
    lastTs = null;
    if (elPlay) {
      elPlay.textContent = '❚❚';
      elPlay.setAttribute('aria-label', 'Пауза');
    }
    rafId = requestAnimationFrame(tick);
  }

  function stopPlay() {
    if (!state.playing) return;
    state.playing = false;
    if (rafId) cancelAnimationFrame(rafId);
    if (elPlay) {
      elPlay.textContent = '▶';
      elPlay.setAttribute('aria-label', 'Играть');
    }
  }

  if (elPlay) elPlay.addEventListener('click', function () {
    state.playing ? stopPlay() : startPlay();
  });

  /* ======================= Засечки ========================= */

  (function buildTicks() {
    if (!elTicks) return;   // на главной засечки живут на шкале-полосе
    var html = '';
    for (var i = 0; i < C.timelineTicks.length; i++) {
      var y = C.timelineTicks[i];
      var pos = yearToPos(y) * 100;
      // первая и последняя подпись не должны свисать за край шкалы
      var cls = 'tick';
      if (pos < 3) cls += ' tick-start';
      else if (pos > 97) cls += ' tick-end';
      html += '<button class="' + cls + '" data-year="' + y + '" style="left:' + pos.toFixed(2) + '%">' +
              esc(fmtYearShort(y)) + '</button>';
    }
    elTicks.innerHTML = html;
    elTicks.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.tick') : null;
      if (!b) return;
      stopPlay();
      setYear(parseInt(b.getAttribute('data-year'), 10));
    });
  })();

  /* =================== Глобус / карта ====================== */

  var elProj = $('#btn-projection');

  // Безопасная установка проекции: до готовности стиля MapLibre кидает ошибку
  function applyProjectionToMap() {
    try { map.setProjection({ type: state.projection }); } catch (e) {}
  }

  function applyProjection() {
    applyProjectionToMap();
    if (elProj) {
      // подпись — то, куда переключит кнопка
      elProj.textContent = state.projection === 'globe' ? 'Карта' : 'Глобус';
      elProj.setAttribute('aria-pressed', state.projection === 'globe' ? 'true' : 'false');
    }
    syncUrl();
  }

  elProj.addEventListener('click', function () {
    state.projection = state.projection === 'globe' ? 'mercator' : 'globe';
    applyProjection();
  });

  /* ==================== Меню «Слои» ======================== */

  var LAYER_GROUPS = {
    'cb-fills':    ['fill-countries', 'fill-empires'],
    'cb-borders':  ['borders-countries', 'borders-empires'],
    'cb-labels':   ['labels-empires', 'labels-countries', 'labels-seas'],
    'cb-cities':   ['city-dots', 'labels-capitals', 'labels-cities'],
    'cb-regions':  ['fill-regions', 'borders-regions'],
    'cb-modern':   ['modern-borders'],
    'cb-events':   ['events-dots']
  };

  function applyLayerGroup(cbId) {
    var cb = document.getElementById(cbId);
    if (!cb || !styleReady) return;
    var vis = cb.checked ? 'visible' : 'none';
    var ids = LAYER_GROUPS[cbId] || [];
    ids.forEach(function (id) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
    });
    if (cbId === 'cb-events') {
      var panel = $('#events-panel');
      if (panel) panel.classList.toggle('is-hidden', !cb.checked);
      if (elFab) elFab.classList.toggle('is-hidden', !cb.checked);
    }
    if (cbId === 'cb-regions') scheduleColorRefresh();
  }

  Object.keys(LAYER_GROUPS).forEach(function (cbId) {
    var cb = document.getElementById(cbId);
    if (cb) cb.addEventListener('change', function () { applyLayerGroup(cbId); });
  });

  var elLayersBtn = $('#btn-layers');
  var elLayersMenu = $('#layers-menu');
  if (elLayersBtn && elLayersMenu) {
    elLayersBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      elLayersMenu.classList.toggle('is-open');
      elLayersBtn.setAttribute('aria-expanded', elLayersMenu.classList.contains('is-open') ? 'true' : 'false');
    });
    document.addEventListener('click', function (e) {
      if (!elLayersMenu.contains(e.target) && e.target !== elLayersBtn) {
        elLayersMenu.classList.remove('is-open');
      }
    });
  }

  /* ============= Мобильная кнопка «События» ================ */

  (function () {
    if (!elFab) return;
    elFab.addEventListener('click', function () {
      var panel = $('#events-panel');
      if (panel) panel.classList.toggle('is-open');
    });
    var close = $('#panel-close');
    if (close) close.addEventListener('click', function () {
      var panel = $('#events-panel');
      if (panel) panel.classList.remove('is-open');
    });
  })();

  /* ================ Клик по событию в панели =============== */

  if (elPanelList) {
    elPanelList.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.ev-item') : null;
      if (!b || !eventsData) return;
      hideHint();
      var idx = parseInt(b.getAttribute('data-idx'), 10);
      if (eventsData.features[idx]) flyToEvent(eventsData.features[idx]);
    });
  }

  /* =================== Клик по человеку ==================== */

  if (elPeopleList) {
    elPeopleList.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.person-item') : null;
      if (!b) return;
      hideHint();
      b.classList.toggle('is-open');   // раскрыть/скрыть заметку о человеке
    });
  }

  /* ==================== Вкладки панели ===================== */

  (function bindTabs() {
    var tabs = document.querySelectorAll('.panel-tab');
    for (var i = 0; i < tabs.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          hideHint();
          setTab(btn.getAttribute('data-tab'));
        });
      })(tabs[i]);
    }
  })();

  /* ===================== Подсказка ========================= */

  var hintEl = $('#hint');
  var hintHidden = false;

  function hideHint() {
    if (!hintEl || hintHidden) return;
    hintHidden = true;
    hintEl.classList.add('is-hidden');
    try { sessionStorage.setItem('chronomap-hint', '1'); } catch (e) {}
  }

  if (hintEl) {
    var hintSeen = false;
    try { hintSeen = sessionStorage.getItem('chronomap-hint') === '1'; } catch (e) {}
    if (hintSeen) { hintHidden = true; hintEl.classList.add('is-hidden'); }
    var hintClose = $('#hint-close');
    if (hintClose) hintClose.addEventListener('click', hideHint);
    setTimeout(hideHint, 15000);                       // просто через 15 секунд
    map.on('dragstart', hideHint);                     // или при первом движении
    map.on('zoomstart', hideHint);
    map.on('rotatestart', hideHint);
  }

  /* ==================== Кнопка «Домой» ===================== */

  (function bindHome() {
    var home = $('#btn-home');
    if (!home) return;
    home.addEventListener('click', function () {
      hideHint();
      stopPlay();
      map.flyTo({
        center: C.defaultView.center,
        zoom: C.defaultView.zoom,
        duration: 1500,
        essential: true
      });
    });
  })();

  /* ================ Быстрые прыжки (чипы) ================= */

  (function buildQuickJumps() {
    var wrap = $('#quick-jumps');
    if (!wrap || !C.quickJumps || !C.quickJumps.length) return;
    var html = '';
    for (var i = 0; i < C.quickJumps.length; i++) {
      var j = C.quickJumps[i];
      html += '<button class="qjump" data-qi="' + i + '" type="button">' +
              esc(j.label) + '</button>';
    }
    wrap.innerHTML = html;
    wrap.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.qjump') : null;
      if (!b) return;
      hideHint();
      stopPlay();
      var j = C.quickJumps[parseInt(b.getAttribute('data-qi'), 10)];
      if (!j) return;
      setYear(j.year);
      if (j.at) {
        map.flyTo({ center: j.at, zoom: j.zoom || 5.5, duration: 1800, essential: true });
      }
      // на мобильных чипы могут открывать панель — закрываем, если открыта
      var panel = $('#events-panel');
      if (panel) panel.classList.remove('is-open');
    });
  })();

  /* ===================== Загрузка данных =================== */

  fetch('assets/map/data/events.geojson')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      eventsData = data;
      // если стиль ещё грузится — данные подхватит initStyleDependent()
      if (styleReady && map.getSource('events')) map.getSource('events').setData(data);
      renderPanel();
      updateEventsFilter();
    })
    .catch(function (e) {
      console.warn('События не загрузились:', e);
      renderPanel();
    });

  // — люди (для вкладки «Кто тогда жил») —
  fetch('assets/map/data/people.json')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      // в файле есть поле с пояснением — нужен сам массив people
      peopleData = Array.isArray(data) ? data : (data && data.people) || [];
      renderPanel();
    })
    .catch(function (e) {
      console.warn('Люди не загрузились:', e);
      renderPanel();
    });

  // — линии современных границ (Natural Earth, оверлей) —
  fetch('assets/map/data/modern-borders.geojson')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      modernData = data;
      if (styleReady && map.getSource('modern-borders')) map.getSource('modern-borders').setData(data);
    })
    .catch(function (e) { console.warn('Современные границы не загрузились:', e); });

  /* ==================== Загрузчик и ошибки ================= */

  function hideLoader() {
    if (elLoader) elLoader.classList.add('is-hidden');
    clearTimeout(slowNoticeTimer);
    clearTimeout(hardStopTimer);
  }

  function showError(msg) {
    if (!elError) return;
    elError.textContent = msg;
    elError.classList.remove('is-hidden');
    setTimeout(function () { elError.classList.add('is-hidden'); }, 9000);
  }

  // Через 8 секунд — успокаивающая подсказка (данные большие)
  var slowNoticeTimer = setTimeout(function () {
    if (!firstIdle && elLoader) {
      var span = elLoader.querySelector('span');
      if (span) span.textContent = 'Загрузка занимает больше времени… Данные идут с сервера OpenHistoricalMap.';
    }
  }, 8000);

  // Если сам style.json упал по сети — пробуем ещё раз
  setTimeout(function () {
    if (!styleReady && styleFetchFailed) {
      styleFetchFailed = false;
      console.warn('Повторная загрузка стиля карты…');
      try { map.setStyle('style/map-style.json'); } catch (e) {}
    }
  }, 12000);

  // Жёсткий предел: если совсем ничего не пришло — сообщаем об ошибке
  var hardStopTimer = setTimeout(function () {
    if (!firstIdle) {
      hideLoader();
      showError('Карта не загрузилась. Проверьте интернет-соединение: данные приходят с сервера OpenHistoricalMap. Если ошибка повторяется — откройте консоль браузера (F12).');
    }
  }, C.loadTimeoutMs);

  /* ======================= Первый рендер =================== */

  elYear.textContent = fmtYear(state.year);
  if (elSlider) elSlider.value = String(Math.round(state.pos * 10000));
  document.title = 'Хронокарта · ' + fmtYear(state.year);
  applyProjection();

  // Небольшая поддержка для «своих рук»: открыть консоль браузера (F12)
  // и можно писать, например: chronomap.setYear(-44)
  window.chronomap = {
    map: map,
    state: state,
    setYear: setYear,
    onYearChange: function (fn) { yearHooks.push(fn); },
    get ready() { return styleReady; },
    get filteredYear() { return lastFilteredYear; },
    get filterError() { return lastFilterError; },
    get colorKey() { return lastColorKey; },
    refreshColors: refreshFillColors
  };

})();
