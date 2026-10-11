(() => {
  "use strict";

  const DATA = window.HISTORY_DATA;
  const app = document.getElementById("app");
  const searchInput = document.getElementById("searchInput");
  const searchResults = document.getElementById("searchResults");
  const tooltip = document.getElementById("timelineTooltip");
  const DOMAIN_START = DATA.meta.start;
  const DOMAIN_END = DATA.meta.end;
  const DOMAIN_SPAN = DOMAIN_END - DOMAIN_START;
  const ZOOM_FACTOR = 1.55;
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 9;
  const TIME_WARP = 1.22;
  const MAX_TIMELINE_FACTOR = 36;
  const MAX_TIMELINE_WIDTH = 180000;

  const state = {
    branch: "states",
    zoomLevel: 1,
    center: -2500,
    viewRange: null,
    detailLevel: "major",
    selectedRegions: new Set(),
    pendingFocusYear: null
  };

  // Order mirrors a broad geographic sweep: Europe, Mediterranean, West Asia,
  // South and East Asia, then Africa and the Americas.
  const STATE_TRACK_ORDER = DATA.stateTrackOrder || ["europe", "mediterranean", "egypt", "levant", "iran", "south-asia", "east-asia", "africa", "americas"];
  const RULER_TRACK_ORDER = DATA.rulerTrackOrder || ["rulers-europe", "rulers-mediterranean", "rulers-egypt", "rulers-west-asia", "rulers-iran", "rulers-india", "rulers-china"];
  const BRANCHES = [
    { id: "states", label: "Государства", eyebrow: "ПОЛИТИЧЕСКАЯ КАРТА", icon: "◈", count: DATA.events.length },
    { id: "rulers", label: "Правители", eyebrow: "ДИНАСТИИ И ЛИЧНОСТИ", icon: "♙", count: DATA.rulers.length },
    { id: "science", label: "Наука и открытия", eyebrow: "ЗНАНИЯ И ИЗОБРЕТЕНИЯ", icon: "✳", count: DATA.scienceEvents.length },
    { id: "arts", label: "Искусство", eyebrow: "ИСКУССТВО И КУЛЬТУРА", icon: "❋", count: DATA.artEvents.length }
  ];
  const DETAIL_LEVELS = [
    { id: "major", label: "Основные", note: "только ключевые повороты" },
    { id: "regional", label: "Региональные", note: "события регионального масштаба" },
    { id: "all", label: "Все события", note: "вся доступная детализация" }
  ];
  const CATEGORY_NAMES = {
    states: "Государства и общества", rulers: "Правители", science: "Наука и изобретения", arts: "Искусство и культура"
  };
  const KIND_NAMES = {
    society: "общество", city: "город", state: "государство", monument: "памятник", law: "право", war: "военный конфликт",
    politics: "политика", trade: "торговля", religion: "религия", contact: "контакт культур", industry: "экономика и технологии",
    disaster: "катастрофа", treaty: "договор", invention: "изобретение", discovery: "открытие", text: "литература",
    painting: "живопись", music: "музыка"
  };
  const ALL_RECORDS = [
    ...DATA.events.map(item => ({ item, type: "event" })),
    ...DATA.scienceEvents.map(item => ({ item, type: "event" })),
    ...DATA.artEvents.map(item => ({ item, type: "event" })),
    ...DATA.rulers.map(item => ({ item, type: "ruler" })),
    ...(DATA.persons || []).map(item => ({ item, type: "person" })),
    ...(DATA.eras || []).map(item => ({ item, type: "era" }))
  ];

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }
  function formatNumber(value) { return Math.round(value).toLocaleString("ru-RU"); }
  function formatYear(year) {
    const y = Math.round(year);
    if (y < 0) return `${formatNumber(Math.abs(y))} г. до н. э.`;
    if (y === 0) return "рубеж эр";
    return `${formatNumber(y)} г. н. э.`;
  }
  function formatAxisYear(year) {
    const y = Math.round(year);
    if (y === 0) return "рубеж эр";
    if (y < 0) return `${formatNumber(Math.abs(y))} до н. э.`;
    return `${formatNumber(y)} н. э.`;
  }
  function recordDate(item, type) {
    if (type === "ruler") return `${formatYear(item.start)} — ${formatYear(item.end)}`;
    if (type === "person") {
      const prefix = item.approx ? "ок. " : "";
      return `${prefix}${formatYear(item.born)} — ${prefix}${formatYear(item.died)}`;
    }
    if (type === "era") return `${formatYear(item.from)} — ${formatYear(item.to)}`;
    return item.dateLabel || formatYear(item.year);
  }
  function tooltipAttributes(item, type) {
    return `data-tooltip data-tip-title="${escapeHTML(item.title || item.name)}" data-tip-date="${escapeHTML(recordDate(item, type))}" data-tip-summary="${escapeHTML(item.summary || "")}" aria-describedby="timelineTooltip"`;
  }

  function normalizedRange(center, span) {
    span = Math.max(1, Math.min(DOMAIN_SPAN, span));
    let start = center - span / 2;
    let end = center + span / 2;
    if (start < DOMAIN_START) { end += DOMAIN_START - start; start = DOMAIN_START; }
    if (end > DOMAIN_END) { start -= end - DOMAIN_END; end = DOMAIN_END; }
    start = Math.max(DOMAIN_START, start);
    end = Math.min(DOMAIN_END, end);
    return { start, end, span: end - start };
  }
  function getRange() {
    if (state.viewRange) return { ...state.viewRange, span: state.viewRange.end - state.viewRange.start };
    return normalizedRange(state.center, DOMAIN_SPAN / Math.pow(ZOOM_FACTOR, state.zoomLevel - 1));
  }
  function closestZoomLevel(span) {
    let best = MIN_ZOOM;
    let difference = Infinity;
    for (let level = MIN_ZOOM; level <= MAX_ZOOM; level++) {
      const candidate = DOMAIN_SPAN / Math.pow(ZOOM_FACTOR, level - 1);
      const current = Math.abs(Math.log(candidate / Math.max(1, span)));
      if (current < difference) { difference = current; best = level; }
    }
    return best;
  }
  function setCurrentRange(center, span) {
    const range = normalizedRange(center, span);
    state.viewRange = { start: range.start, end: range.end };
    state.center = (range.start + range.end) / 2;
    state.zoomLevel = closestZoomLevel(range.span);
    state.pendingFocusYear = state.center;
  }
  function focusWindow(start, end, context = 1.16) {
    const from = Math.max(DOMAIN_START, Math.min(start, end));
    const to = Math.min(DOMAIN_END, Math.max(start, end));
    setCurrentRange((from + to) / 2, Math.max(50, (to - from) * context));
  }
  function rangeSizeLabel(span) {
    if (span >= 1000) return `≈ ${formatNumber(span / 1000)} тыс. лет`;
    return `≈ ${formatNumber(span)} лет`;
  }
  function scaleLabel(range) {
    const factor = Math.min(MAX_TIMELINE_FACTOR, DOMAIN_SPAN / range.span);
    return factor < 10 ? factor.toFixed(1) : Math.round(factor).toLocaleString("ru-RU");
  }
  function getLabelWidth() { return window.innerWidth <= 650 ? 156 : 238; }
  function getTimelineViewportWidth() {
    const pageWidth = Math.min(window.innerWidth, 1680);
    const horizontalPadding = window.innerWidth <= 760 ? 16 : Math.min(70, Math.max(18, window.innerWidth * 0.044));
    return Math.max(280, pageWidth - horizontalPadding * 2);
  }
  function getChartWidth() {
    const base = getTimelineViewportWidth() * 4 - getLabelWidth();
    const range = getRange();
    const factor = Math.min(MAX_TIMELINE_FACTOR, DOMAIN_SPAN / Math.max(50, range.span));
    return Math.max(400, Math.min(MAX_TIMELINE_WIDTH, Math.round(base * factor)));
  }
  function timeFraction(year) {
    const linear = Math.max(0, Math.min(1, (year - DOMAIN_START) / DOMAIN_SPAN));
    return Math.pow(linear, TIME_WARP);
  }
  function xAt(year, range, width) { return timeFraction(year) * width; }
  function yearAtX(x, width) {
    const fraction = Math.max(0, Math.min(1, x / Math.max(1, width)));
    return DOMAIN_START + Math.pow(fraction, 1 / TIME_WARP) * DOMAIN_SPAN;
  }

  function niceStep(raw) {
    const power = Math.pow(10, Math.floor(Math.log10(Math.max(1, raw))));
    const fraction = raw / power;
    return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
  }
  function getTicks(width) {
    const step = niceStep(DOMAIN_SPAN / Math.max(8, width / 145));
    const ticks = [DOMAIN_START];
    let current = Math.ceil(DOMAIN_START / step) * step;
    if (current <= DOMAIN_START) current += step;
    for (; current < DOMAIN_END; current += step) ticks.push(Math.round(current));
    ticks.push(DOMAIN_END);
    return [...new Set(ticks)];
  }
  function gridMarkup(ticks, range, width) {
    return ticks.map(year => `<i class="plot-gridline" style="left:${Math.max(0, Math.min(width, xAt(year, range, width))).toFixed(1)}px" aria-hidden="true"></i>`).join("");
  }
  function axisMarkup(ticks, range, width) {
    let lastLabelX = -Infinity;
    return `<div class="axis-row"><div class="axis-label sticky-label"><span>ВРЕМЯ</span><small>слева направо</small></div><div class="axis-plot" style="width:${width}px">${ticks.map(year => {
      const x = Math.max(0, Math.min(width, xAt(year, range, width)));
      const edge = x < 22 ? "at-start" : x > width - 22 ? "at-end" : "";
      const showLabel = x - lastLabelX >= 88 || year === DOMAIN_END;
      if (showLabel) lastLabelX = x;
      return `<span class="axis-tick ${edge}" style="left:${x.toFixed(1)}px"><i></i>${showLabel ? `<b>${escapeHTML(formatAxisYear(year))}</b>` : ""}</span>`;
    }).join("")}</div></div>`;
  }

  function branchEvents(branch) {
    if (branch === "science") return DATA.scienceEvents;
    if (branch === "arts") return DATA.artEvents;
    return DATA.events;
  }
  function stateTracks() {
    const byId = new Map(DATA.stateTracks.map(track => [track.id, track]));
    return STATE_TRACK_ORDER.map(id => byId.get(id)).filter(Boolean);
  }
  function tracksForBranch(branch) {
    if (branch === "science") return DATA.scienceTracks;
    if (branch === "arts") return DATA.artTracks;
    if (branch === "rulers") {
      const byId = new Map(DATA.rulerTracks.map(track => [track.id, track]));
      return RULER_TRACK_ORDER.map(id => byId.get(id)).filter(Boolean);
    }
    return stateTracks();
  }
  function visibleTracks(branch) {
    const tracks = tracksForBranch(branch);
    if (branch !== "states" || state.selectedRegions.size === 0) return tracks;
    return tracks.filter(track => state.selectedRegions.has(track.id));
  }
  function stateTrackById(id) { return DATA.stateTracks.find(track => track.id === id); }
  function visibleAtDetailLevel(item) {
    if (state.detailLevel === "major") return item.level === "major";
    if (state.detailLevel === "regional") return item.level !== "minor";
    return true;
  }

  function layoutPeriods(periods, range, width) {
    const candidates = periods.map(period => {
      const from = Math.max(period.from, DOMAIN_START);
      const to = Math.min(period.to, DOMAIN_END);
      return { ...period, left: xAt(from, range, width), right: xAt(to, range, width) };
    }).filter(period => period.to >= DOMAIN_START && period.from <= DOMAIN_END)
      .sort((a, b) => a.left - b.left || a.right - b.right);
    const slotEnds = [];
    return candidates.map(period => {
      let slot = slotEnds.findIndex(end => period.left > end + 3);
      if (slot < 0) slot = slotEnds.length;
      slotEnds[slot] = period.right;
      return { ...period, slot };
    });
  }
  function layoutEvents(events, range, width) {
    const candidates = events.filter(event => event.year >= DOMAIN_START && event.year <= DOMAIN_END)
      .sort((a, b) => a.year - b.year || a.title.localeCompare(b.title, "ru"));
    const slotLastX = [];
    let lastLabelX = -Infinity;
    const minSeparation = 30;
    return candidates.map(event => {
      const x = xAt(event.year, range, width);
      let slot = slotLastX.findIndex(lastX => x - lastX >= minSeparation);
      if (slot < 0) slot = slotLastX.length;
      slotLastX[slot] = x;
      const labelGap = 148;
      const canLabel = event.level === "major" || (state.detailLevel === "all" && event.level === "regional");
      const showLabel = canLabel && x - lastLabelX >= labelGap;
      if (showLabel) lastLabelX = x;
      return { event, x, slot, showLabel };
    });
  }
  function renderEventMarker(layout, trackColor, top, width) {
    const event = layout.event;
    const labelClass = layout.x > width - 100 ? "label-to-left" : "";
    const date = recordDate(event, "event");
    return `<a class="event-marker mark-${escapeHTML(event.kind || "event")} level-${escapeHTML(event.level || "major")}" href="#event/${escapeHTML(event.id)}" style="left:${layout.x.toFixed(1)}px;top:${top}px;--marker-color:${escapeHTML(trackColor)}" aria-label="${escapeHTML(event.title)}, ${escapeHTML(date)}" ${tooltipAttributes(event, "event")}><span class="marker-dot" aria-hidden="true"></span>${layout.showLabel ? `<span class="marker-label ${labelClass}">${escapeHTML(event.title)}</span>` : ""}</a>`;
  }
  function renderPeriodBand(period, trackColor) {
    const bandWidth = Math.max(5, period.right - period.left);
    return `<button class="period-band" type="button" style="left:${period.left.toFixed(1)}px;top:${10 + period.slot * 10}px;width:${bandWidth.toFixed(1)}px;--period-color:${escapeHTML(trackColor)}" data-action="focus-period" data-track="${escapeHTML(period.trackId)}" data-period-index="${period.periodIndex}" title="${escapeHTML(period.name)} · нажмите, чтобы открыть регион крупнее">${bandWidth > 96 ? `<span>${escapeHTML(period.name)}</span>` : ""}</button>`;
  }

  function renderTimeRow(track, branch, range, ticks, width) {
    const allTrackEvents = branchEvents(branch).filter(event => event.track === track.id);
    const visible = allTrackEvents.filter(visibleAtDetailLevel);
    const laidOut = layoutEvents(visible, range, width);
    let periodLayouts = [];
    if (branch === "states") {
      const tagged = track.periods.map((period, index) => ({ ...period, periodIndex: index, trackId: track.id }));
      periodLayouts = layoutPeriods(tagged, range, width);
    }
    const periodSlots = periodLayouts.length ? Math.max(...periodLayouts.map(period => period.slot)) + 1 : 0;
    const eventSlots = laidOut.length ? Math.max(...laidOut.map(entry => entry.slot)) + 1 : 0;
    const rowHeight = branch === "states" ? Math.max(86, 24 + periodSlots * 10 + eventSlots * 24 + 24) : Math.max(88, 32 + eventSlots * 25 + 24);
    const baseTop = branch === "states" ? 30 + periodSlots * 10 : 28;
    const periodHTML = periodLayouts.map(period => renderPeriodBand(period, track.color)).join("");
    const markersHTML = laidOut.map(entry => renderEventMarker(entry, track.color, baseTop + entry.slot * 24, width)).join("");
    const focusTitle = branch === "states" ? "Сфокусировать регион и добавить к сравнению" : "Увеличить ближайший временной отрезок";
    return `<div class="track-row" style="--row-height:${rowHeight}px;--track-color:${escapeHTML(track.color)}">
      <div class="track-label sticky-label"><div class="track-name-line"><span class="track-swatch" aria-hidden="true"></span><strong>${escapeHTML(track.name)}</strong></div><p>${escapeHTML(track.description || "")}</p>
        <div class="track-actions"><span class="track-count">${allTrackEvents.length} ${allTrackEvents.length === 1 ? "событие" : "событий"}</span><button class="track-focus" type="button" data-action="focus-track" data-branch="${escapeHTML(branch)}" data-track="${escapeHTML(track.id)}" title="${focusTitle}" aria-label="${focusTitle}">↗</button></div>
      </div>
      <div class="track-plot" style="width:${width}px;height:${rowHeight}px">${gridMarkup(ticks, range, width)}${periodHTML}${markersHTML}${laidOut.length || periodLayouts.length ? "" : `<span class="empty-track-note">На шкале пока нет отмеченных событий</span>`}</div>
    </div>`;
  }

  function layoutRulers(rulers, range, width) {
    const visible = rulers.filter(ruler => ruler.end >= DOMAIN_START && ruler.start <= DOMAIN_END).sort((a, b) => a.start - b.start || a.end - b.end);
    const slotLastX = [];
    return visible.map(ruler => {
      const x = xAt(Math.max(ruler.start, DOMAIN_START), range, width);
      let slot = slotLastX.findIndex(lastX => x - lastX >= 126);
      if (slot < 0) slot = slotLastX.length;
      slotLastX[slot] = x;
      const left = Math.max(0, Math.min(width - 130, x - 3));
      const start = Math.max(ruler.start, DOMAIN_START);
      const end = Math.min(ruler.end, DOMAIN_END);
      const spanLeft = Math.max(0, xAt(start, range, width) - left);
      const spanWidth = Math.max(6, xAt(end, range, width) - xAt(start, range, width));
      return { ruler, x, slot, left, spanLeft, spanWidth };
    });
  }
  function renderRulerRow(track, range, ticks, width) {
    const rulers = DATA.rulers.filter(ruler => ruler.track === track.id);
    const placed = layoutRulers(rulers, range, width);
    const slots = placed.length ? Math.max(...placed.map(entry => entry.slot)) + 1 : 1;
    const height = Math.max(96, 28 + slots * 36);
    const entries = placed.map(entry => `<a class="ruler-entry" href="#ruler/${escapeHTML(entry.ruler.id)}" style="left:${entry.left.toFixed(1)}px;top:${10 + entry.slot * 36}px;--reign-left:${entry.spanLeft.toFixed(1)}px;--reign-width:${entry.spanWidth.toFixed(1)}px;--track-color:${escapeHTML(track.color)}" aria-label="${escapeHTML(entry.ruler.name)}, ${escapeHTML(recordDate(entry.ruler, "ruler"))}" ${tooltipAttributes(entry.ruler, "ruler")}><span class="ruler-name">${escapeHTML(entry.ruler.name)}</span><span class="ruler-dates">${escapeHTML(formatYear(entry.ruler.start))} — ${escapeHTML(formatYear(entry.ruler.end))}</span><span class="reign-bar" aria-hidden="true"></span></a>`).join("");
    return `<div class="track-row ruler-track-row" style="--row-height:${height}px;--track-color:${escapeHTML(track.color)}"><div class="track-label sticky-label"><div class="track-name-line"><span class="track-swatch" aria-hidden="true"></span><strong>${escapeHTML(track.name)}</strong></div><p>Наведите на имя или нажмите, чтобы открыть справку.</p><div class="track-actions"><span class="track-count">${rulers.length} ${rulers.length === 1 ? "правитель" : "правителей"}</span></div></div><div class="track-plot ruler-plot" style="width:${width}px;height:${height}px">${gridMarkup(ticks, range, width)}${entries}${placed.length ? "" : `<span class="empty-track-note">На шкале пока нет отмеченных правителей</span>`}</div></div>`;
  }

  function personColor(person) {
    const palette = DATA.personPalettes?.polity || {};
    return palette[person.polityKey] || "#7d9383";
  }
  function personLegendMarkup() {
    const seen = new Set();
    const items = [];
    for (const person of DATA.persons || []) {
      const key = person.polityKey;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(`<span class="person-legend-item"><i style="--person-color:${escapeHTML(personColor(person))}"></i>${escapeHTML(person.polity)}</span>`);
    }
    return items.join("");
  }
  function layoutPersons(persons, range, width) {
    const cardWidth = window.innerWidth <= 650 ? 116 : 136;
    const visible = persons.filter(person => person.died >= DOMAIN_START && person.born <= DOMAIN_END).sort((a, b) => a.born - b.born || a.name.localeCompare(b.name, "ru"));
    const slotEnds = [];
    return visible.map(person => {
      const startX = xAt(Math.max(person.born, DOMAIN_START), range, width);
      const endX = xAt(Math.min(person.died, DOMAIN_END), range, width);
      const labelLeft = Math.max(0, Math.min(width - cardWidth, startX - 5));
      let slot = slotEnds.findIndex(end => labelLeft > end + 5);
      if (slot < 0) slot = slotEnds.length;
      slotEnds[slot] = labelLeft + cardWidth;
      return { person, startX, endX, labelLeft, slot, cardWidth };
    });
  }
  function renderPersonRow(group, range, ticks, width) {
    const people = (DATA.persons || []).filter(person => person.group === group.id);
    const placed = layoutPersons(people, range, width);
    const slots = placed.length ? Math.max(...placed.map(item => item.slot)) + 1 : 1;
    const height = Math.max(84, 25 + slots * 38);
    const peopleHTML = placed.map(entry => {
      const { person } = entry;
      const color = personColor(person);
      const top = 8 + entry.slot * 38;
      const barWidth = Math.max(7, entry.endX - entry.startX);
      const date = recordDate(person, "person");
      return `<a class="person-life-bar" href="#person/${escapeHTML(person.id)}" style="left:${entry.startX.toFixed(1)}px;top:${top + 26}px;width:${barWidth.toFixed(1)}px;--person-color:${escapeHTML(color)}" aria-label="${escapeHTML(person.name)} · ${escapeHTML(date)}" ${tooltipAttributes(person, "person")}><i></i></a><a class="person-life-label" href="#person/${escapeHTML(person.id)}" style="left:${entry.labelLeft.toFixed(1)}px;top:${top}px;width:${entry.cardWidth}px;--person-color:${escapeHTML(color)}" ${tooltipAttributes(person, "person")}><strong>${escapeHTML(person.name)}</strong><small>${escapeHTML(date)}</small></a>`;
    }).join("");
    return `<div class="track-row person-track-row" style="--row-height:${height}px;--track-color:#829486"><div class="track-label sticky-label"><div class="track-name-line"><span class="track-swatch" aria-hidden="true"></span><strong>${escapeHTML(group.name)}</strong></div><p>Продолжительность жизни; цвет — по государству или политическому контексту.</p><div class="track-actions"><span class="track-count">${people.length} ${people.length === 1 ? "персона" : "персон"}</span></div></div><div class="track-plot person-plot" style="width:${width}px;height:${height}px">${gridMarkup(ticks, range, width)}${peopleHTML}${placed.length ? "" : `<span class="empty-track-note">На шкале пока нет персон из этой группы</span>`}</div></div>`;
  }
  function renderPeopleSection(range, ticks, width, labelWidth) {
    return `<div class="people-section-head" style="width:${getTimelineViewportWidth()}px"><div class="people-head-copy"><span class="eyebrow">ОТДЕЛЬНАЯ ЛИНИЯ · ГОДЫ ЖИЗНИ</span><strong>Личности и их эпохи</strong><p>Полосы показывают жизнь человека, а не годы правления. Цвет каждой полосы обозначает государство или политический контекст.</p></div><div class="person-color-tools"><span class="person-color-label">ГОСУДАРСТВО</span><div class="person-legend">${personLegendMarkup()}</div></div></div><div class="track-section-title people-divider"><span>ИЗВЕСТНЫЕ ЛИЧНОСТИ</span><i></i><small>${(DATA.persons || []).length} персон</small></div>${(DATA.personGroups || []).map(group => renderPersonRow(group, range, ticks, width)).join("")}`;
  }

  function quickJumpOptions() {
    const eras = DATA.eras.map(era => `<option value="era|${escapeHTML(era.id)}">${escapeHTML(era.name)}</option>`).join("");
    const periods = stateTracks().flatMap(track => track.periods.map((period, index) => `<option value="period|${escapeHTML(track.id)}|${index}">${escapeHTML(track.name)} — ${escapeHTML(period.name)}</option>`)).join("");
    return `<option value="">Перейти к эпохе или государству…</option><optgroup label="Эпохи">${eras}</optgroup><optgroup label="Регионы и государства">${periods}</optgroup>`;
  }
  function regionFilterMarkup() {
    const selected = state.selectedRegions;
    const all = selected.size === 0;
    return `<div class="region-filter"><div class="filter-heading"><span>РЕГИОНЫ</span><small>${all ? "показаны все" : `выбрано ${selected.size}`}</small></div><div class="region-chips"><button type="button" class="region-chip ${all ? "is-active" : ""}" data-region-filter="all" aria-pressed="${all}">Все регионы</button>${stateTracks().map(track => `<button type="button" class="region-chip ${selected.has(track.id) ? "is-active" : ""}" data-region-filter="${escapeHTML(track.id)}" style="--region-color:${escapeHTML(track.color)}" aria-pressed="${selected.has(track.id)}"><i></i>${escapeHTML(track.name)}</button>`).join("")}</div><small class="region-hint">Клик по периоду фокусирует этот регион; выберите другие названия, чтобы добавить линии к сравнению.</small></div>`;
  }
  function detailLevelMarkup() {
    const current = DETAIL_LEVELS.find(level => level.id === state.detailLevel);
    return `<div class="detail-level-control"><div class="filter-heading"><span>ДЕТАЛИЗАЦИЯ СОБЫТИЙ</span><small>${escapeHTML(current?.note || "")}</small></div><div class="detail-level-buttons" role="group" aria-label="Выбор детализации событий">${DETAIL_LEVELS.map(level => `<button type="button" class="detail-level-button ${state.detailLevel === level.id ? "is-active" : ""}" data-detail-level="${level.id}" aria-pressed="${state.detailLevel === level.id}">${level.label}</button>`).join("")}</div></div>`;
  }

  function timelineGeometry(scroll) {
    const inner = scroll?.querySelector(".timeline-inner");
    if (!scroll || !inner) return null;
    const computed = getComputedStyle(inner);
    const chartWidth = parseFloat(computed.getPropertyValue("--chart-width")) || 1;
    const labelWidth = parseFloat(computed.getPropertyValue("--label-width")) || getLabelWidth();
    return { chartWidth, labelWidth, plotWidth: Math.max(1, scroll.clientWidth - labelWidth) };
  }
  function updateVisibleRange() {
    if (currentTooltipTarget) hideTooltip();
    const scroll = document.getElementById("timelineScroll");
    const geometry = timelineGeometry(scroll);
    if (!geometry) return;
    const startX = Math.max(0, Math.min(geometry.chartWidth, scroll.scrollLeft));
    const endX = Math.max(startX, Math.min(geometry.chartWidth, startX + geometry.plotWidth));
    const fromYear = yearAtX(startX, geometry.chartWidth);
    const toYear = yearAtX(endX, geometry.chartWidth);
    state.center = yearAtX((startX + endX) / 2, geometry.chartWidth);
    const from = document.getElementById("visibleFrom");
    const to = document.getElementById("visibleTo");
    if (from) from.textContent = formatAxisYear(fromYear);
    if (to) to.textContent = formatAxisYear(toYear);
  }
  function renderTimeline() {
    closePanel();
    const previousScroll = document.getElementById("timelineScroll");
    const previousGeometry = timelineGeometry(previousScroll);
    const oldAnchorYear = previousGeometry
      ? yearAtX(previousScroll.scrollLeft + previousGeometry.plotWidth / 2, previousGeometry.chartWidth)
      : null;
    const range = getRange();
    const width = getChartWidth();
    const labelWidth = getLabelWidth();
    const ticks = getTicks(width);
    const branch = BRANCHES.find(item => item.id === state.branch) || BRANCHES[0];
    const tracks = visibleTracks(branch.id);
    const allTracks = tracksForBranch(branch.id);
    const descriptions = {
      states: "Шкала нелинейная и занимает около четырёх ширин экрана. Прокрутите её по горизонтали: полный период доступен и после увеличения.",
      rulers: "Каждая полоса показывает период правления. Наведите на имя для краткой справки; щелчок откроет статью.",
      science: "От земледелия и письма до открытий и инженерных решений XIX века; прокрутите шкалу, чтобы увидеть весь период.",
      arts: "Архитектура, литература, изобразительное искусство и музыка — отдельные линии на общей прокручиваемой шкале."
    };
    const eventCount = branch.id === "states" ? DATA.events.length : branch.id === "science" ? DATA.scienceEvents.length : branch.id === "arts" ? DATA.artEvents.length : DATA.rulers.length;
    const rangeLabel = branch.id === "states" ? `${state.selectedRegions.size || allTracks.length} из ${allTracks.length} регионов` : branch.id === "rulers" ? "правителей в выборке" : "записей в ветке";
    const legend = branch.id === "rulers"
      ? `<span><i class="legend-reign"></i> годы правления</span>`
      : `${branch.id === "states" ? `<span><i class="legend-band"></i> период государства</span>` : `<span><i class="legend-dot"></i> событие / открытие</span>`}<span><i class="legend-major"></i> основное</span><span><i class="legend-regional"></i> региональное</span><span><i class="legend-minor"></i> дополнительная деталь</span>`;
    const sectionTitle = branch.id === "rulers" ? "ПРАВЯЩИЕ ДИНАСТИИ И ПЕРСОНЫ" : branch.id === "states" ? "РЕГИОНЫ И ПОЛИТИЧЕСКИЕ ПРОЦЕССЫ" : branch.id === "science" ? "ЗНАНИЕ И ТЕХНОЛОГИИ" : "ФОРМЫ ИСКУССТВА";
    const rows = branch.id === "rulers" ? tracks.map(track => renderRulerRow(track, range, ticks, width)).join("") : tracks.map(track => renderTimeRow(track, branch.id, range, ticks, width)).join("");
    const people = branch.id === "states" ? renderPeopleSection(range, ticks, width, labelWidth) : "";
    const detailControls = branch.id === "rulers" ? `<div class="detail-level-explainer"><span class="filter-heading">ШКАЛА ПРАВЛЕНИЙ</span><p>Показывает интервалы власти; нажмите на имя для справки о правителе.</p></div>` : detailLevelMarkup();
    const filters = `<div class="map-filters">${detailControls}${branch.id === "states" ? regionFilterMarkup() : ""}</div>`;

    app.innerHTML = `<div class="timeline-page">
      <section class="hero-section">
        <div class="hero-topline"><span class="eyebrow"><i></i> ИНТЕРАКТИВНЫЙ ИСТОРИЧЕСКИЙ АТЛАС</span><span class="hero-period">12 000 до н. э. <b>—</b> 1900 н. э.</span></div>
        <div class="hero-main"><div class="hero-copy"><h1>История,<br><em>которую можно развернуть.</em></h1><p>Сопоставляйте цивилизации, правителей, открытия и произведения искусства на одной живой шкале времени.</p><a class="hero-link" href="#about">Как устроена карта <span aria-hidden="true">↗</span></a></div><div class="hero-aside"><div class="hero-compass" aria-hidden="true"><span class="compass-ring"></span><span class="compass-line"></span><span class="compass-dot"></span><b>AH</b></div><div class="hero-stats"><div><strong>${formatNumber(DATA.events.length + DATA.scienceEvents.length + DATA.artEvents.length)}</strong><span>событий<br>в демо-карте</span></div><div><strong>${(DATA.persons || []).length}</strong><span>персон<br>на нижней шкале</span></div></div></div></div>
        <div class="hero-bottom"><span>ОТ ПЕРВЫХ ПОСЕЛЕНИЙ</span><i></i><span>ДО МИРА 1900 ГОДА</span><a href="#timeline" aria-label="Перейти к хронологии">↓</a></div>
      </section>
      <section class="explorer-section" id="timeline">
        <div class="section-heading"><div><span class="eyebrow">ХРОНОЛОГИЧЕСКАЯ КАРТА</span><h2>Одна шкала.<br><em>Много историй.</em></h2></div><p>Первый масштаб показывает целую картину и только основные события. Введите свой диапазон дат, выберите регионы и настройте плотность событий.</p></div>
        <div class="branch-tabs" role="tablist" aria-label="Исторические слои">${BRANCHES.map(item => `<button class="branch-tab ${item.id === branch.id ? "is-active" : ""}" type="button" role="tab" aria-selected="${item.id === branch.id}" data-branch="${item.id}"><span class="branch-icon" aria-hidden="true">${item.icon}</span><span>${item.label}</span><small>${item.count}</small></button>`).join("")}</div>
        ${filters}
        <div class="map-toolbar">
          <label class="jump-select"><span>БЫСТРЫЙ ПЕРЕХОД</span><select id="quickJump">${quickJumpOptions()}</select><b aria-hidden="true">⌄</b></label>
          <form class="date-range-form" id="dateRangeForm"><span class="date-range-title">ПЕРЕЙТИ К ДАТАМ</span><label>ОТ<input id="dateFrom" type="number" step="1" min="${DOMAIN_START}" max="${DOMAIN_END}" value="${Math.round(range.start)}" aria-label="Начало временного диапазона"></label><label>ДО<input id="dateTo" type="number" step="1" min="${DOMAIN_START}" max="${DOMAIN_END}" value="${Math.round(range.end)}" aria-label="Конец временного диапазона"></label><button type="submit">Применить</button><small class="date-range-hint">Отрицательное число = до н. э.</small><span id="rangeError" class="range-error" aria-live="polite"></span></form>
          <div class="map-controls" aria-label="Управление масштабом"><button type="button" class="control-square" data-action="pan-left" title="Сдвинуть шкалу назад" aria-label="Сдвинуть шкалу назад">←</button><button type="button" class="control-square" data-action="zoom-out" title="Уменьшить масштаб" aria-label="Уменьшить масштаб" ${state.zoomLevel <= MIN_ZOOM ? "disabled" : ""}>−</button><div class="zoom-readout"><strong>×${scaleLabel(range)}</strong><span>${rangeSizeLabel(range.span)} · фокус</span></div><button type="button" class="control-square control-plus" data-action="zoom-in" title="Увеличить масштаб" aria-label="Увеличить масштаб" ${state.zoomLevel >= MAX_ZOOM ? "disabled" : ""}>+</button><button type="button" class="control-square" data-action="pan-right" title="Сдвинуть шкалу вперёд" aria-label="Сдвинуть шкалу вперёд">→</button><button type="button" class="control-reset" data-action="reset-zoom">Весь период</button></div>
        </div>
        <div class="map-summary"><div class="map-summary-copy"><span class="summary-kicker">${escapeHTML(branch.eyebrow)}</span><strong>${escapeHTML(branch.label)}</strong><p>${escapeHTML(descriptions[branch.id])}</p></div><div class="map-legend">${legend}</div></div>
        <div class="visible-range"><span>В ОКНЕ ПРОСМОТРА</span><strong id="visibleFrom">—</strong><i></i><strong id="visibleTo">—</strong><small>${escapeHTML(formatNumber(eventCount))} ${escapeHTML(rangeLabel)} · ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА ↔</small></div>
        <div class="timeline-scroll" id="timelineScroll" tabindex="0" aria-label="Полная хронология; прокручивайте по горизонтали от 12 000 года до н. э. до 1900 года"><div class="timeline-inner" id="timelineInner" style="--chart-width:${width}px;--label-width:${labelWidth}px">${axisMarkup(ticks, range, width)}<div class="track-section-title"><span>${sectionTitle}</span><i></i><small>${tracks.length} линий</small></div>${rows}${people}</div></div>
        <div class="timeline-footnote"><span class="footnote-mark">i</span><p>Шкала нелинейна: более поздние века показаны подробнее. Полный диапазон от 12 000 до н. э. до 1900 н. э. остаётся в карте при любом увеличении; прокручивайте её по горизонтали или задайте даты выше. Отрицательные годы — до н. э., нулевой год — математическая граница.</p><a href="#about">О датах и данных <span aria-hidden="true">↗</span></a></div>
      </section>
      <section class="era-strip" aria-label="Исторические эпохи"><div><span class="eyebrow">СТАТЬИ ОБ ЭПОХАХ</span><h2>Куда отправимся?</h2></div><div class="era-cards">${DATA.eras.map(era => `<a class="era-card" href="#era/${escapeHTML(era.id)}" style="--era-color:${escapeHTML(era.color)}" ${tooltipAttributes(era, "era")}><span class="era-dates">${escapeHTML(formatAxisYear(era.from))} — ${escapeHTML(formatAxisYear(era.to))}</span><strong>${escapeHTML(era.short)}</strong><span class="era-arrow" aria-hidden="true">↗</span></a>`).join("")}</div></section>
      <section class="editorial-note"><span class="note-index">01 / 04</span><div><span class="eyebrow">КАК ЧИТАТЬ КАРТУ</span><h2>Связи становятся видны,<br><em>когда истории рядом.</em></h2></div><p>Выберите один регион или несколько, задайте точные границы дат и настройте плотность событий. Отдельная нижняя линия сопоставляет годы жизни известных персон с историей регионов.</p><a href="#about">Подробнее о проекте <span aria-hidden="true">↗</span></a></section>
    </div>`;
    updateNav("timeline");
    const scroll = document.getElementById("timelineScroll");
    const geometry = timelineGeometry(scroll);
    if (scroll && geometry) {
      const focusYear = Number.isFinite(state.pendingFocusYear) ? state.pendingFocusYear : Number.isFinite(oldAnchorYear) ? oldAnchorYear : state.center;
      const targetX = xAt(focusYear, range, geometry.chartWidth);
      scroll.scrollLeft = Math.max(0, Math.min(scroll.scrollWidth - scroll.clientWidth, targetX - geometry.plotWidth / 2));
      scroll.addEventListener("scroll", updateVisibleRange, { passive: true });
      state.pendingFocusYear = null;
      updateVisibleRange();
    }
  }

  function currentTrackName(item, type) {
    if (type === "era") return "Всемирная хронология";
    if (type === "person") return `${item.activityLabel} · ${item.polity}`;
    if (type === "ruler") return tracksForBranch("rulers").find(track => track.id === item.track)?.name || "Правители";
    if (item.branch === "states") return stateTrackById(item.track)?.name || "Исторический процесс";
    if (item.branch === "science") return DATA.scienceTracks.find(track => track.id === item.track)?.name || "Наука и изобретения";
    if (item.branch === "arts") return DATA.artTracks.find(track => track.id === item.track)?.name || "Искусство";
    return "История";
  }
  let currentTooltipTarget = null;
  function showTooltip(target) {
    if (!tooltip || !target) return;
    tooltip.querySelector("[data-tip-title]").textContent = target.dataset.tipTitle || "";
    tooltip.querySelector("[data-tip-date]").textContent = target.dataset.tipDate || "";
    tooltip.querySelector("[data-tip-summary]").textContent = target.dataset.tipSummary || "";
    tooltip.hidden = false;
    requestAnimationFrame(() => {
      if (tooltip.hidden) return;
      const rect = target.getBoundingClientRect();
      const box = tooltip.getBoundingClientRect();
      const margin = 12;
      let left = rect.left + rect.width / 2 - box.width / 2;
      left = Math.max(margin, Math.min(window.innerWidth - box.width - margin, left));
      let top = rect.top - box.height - 12;
      if (top < margin) top = Math.min(window.innerHeight - box.height - margin, rect.bottom + 12);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(margin, top)}px`;
    });
  }
  function hideTooltip() {
    currentTooltipTarget = null;
    if (tooltip) tooltip.hidden = true;
  }
  function closePanel() { hideTooltip(); }
  function getRecord(type, id) {
    if (type === "ruler") return DATA.rulers.find(item => item.id === id);
    if (type === "person") return (DATA.persons || []).find(item => item.id === id);
    if (type === "era") return DATA.eras.find(item => item.id === id);
    return ALL_RECORDS.find(record => record.type === "event" && record.item.id === id)?.item;
  }
  function relatedRecords(type, item) {
    if (type === "ruler") return DATA.rulers.filter(other => other.id !== item.id && other.track === item.track).sort((a, b) => Math.abs(a.start - item.start) - Math.abs(b.start - item.start)).slice(0, 3).map(other => ({ item: other, type: "ruler" }));
    if (type === "person") return (DATA.persons || []).filter(other => other.id !== item.id && (other.group === item.group || other.polityKey === item.polityKey)).sort((a, b) => Math.abs(a.born - item.born) - Math.abs(b.born - item.born)).slice(0, 4).map(other => ({ item: other, type: "person" }));
    if (type === "era") {
      const events = [...DATA.events, ...DATA.scienceEvents, ...DATA.artEvents].filter(other => other.year >= item.from && other.year <= item.to);
      return events.sort((a, b) => a.year - b.year).slice(0, 4).map(other => ({ item: other, type: "event" }));
    }
    return branchEvents(item.branch).filter(other => other.id !== item.id && other.track === item.track).sort((a, b) => Math.abs(a.year - item.year) - Math.abs(b.year - item.year)).slice(0, 4).map(other => ({ item: other, type: "event" }));
  }
  function inlineMarkdown(text) {
    let html = escapeHTML(text);
    const code = [];
    html = html.replace(/`([^`]+)`/g, (_match, value) => {
      const token = `@@INLINE_CODE_${code.length}@@`;
      code.push(`<code>${value}</code>`);
      return token;
    });
    html = html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_match, target, label) => `<span class="wiki-ref" title="Заметка Obsidian: ${target}">${label || target.split("/").pop()}</span>`);
    html = html.replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:|#)[^)\s]+)\)/gi, (_match, label, url) => `<a href="${url}"${/^https?:\/\//i.test(url) ? ' target="_blank" rel="noopener noreferrer"' : ""}>${label}</a>`);
    html = html.replace(/&lt;(https?:\/\/[^&<>]+)&gt;/gi, (_match, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    html = html.replace(/~~([^~]+)~~/g, "<del>$1</del>");
    return html.replace(/@@INLINE_CODE_(\d+)@@/g, (_match, index) => code[Number(index)] || "");
  }
  function renderMarkdown(markdown) {
    const lines = String(markdown || "").replace(/\r/g, "").split("\n");
    const html = [];
    let paragraph = [];
    let listType = "";
    let codeFence = false;
    let codeLines = [];
    const flushParagraph = () => {
      if (paragraph.length) html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (listType) html.push(`</${listType}>`);
      listType = "";
    };
    const flushCode = () => {
      html.push(`<pre><code>${escapeHTML(codeLines.join("\n"))}</code></pre>`);
      codeLines = [];
      codeFence = false;
    };
    const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim());
    const isTableRule = line => {
      const values = cells(line);
      return values.length > 0 && values.every(value => /^:?-{3,}:?$/.test(value));
    };
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (codeFence) {
        if (/^```/.test(trimmed)) flushCode();
        else codeLines.push(lines[i]);
        continue;
      }
      if (/^```/.test(trimmed)) { flushParagraph(); flushList(); codeFence = true; continue; }
      if (!trimmed) { flushParagraph(); flushList(); continue; }
      if (trimmed.includes("|") && i + 1 < lines.length && isTableRule(lines[i + 1].trim())) {
        flushParagraph(); flushList();
        const headers = cells(trimmed);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim().includes("|")) { rows.push(cells(lines[i])); i++; }
        i--;
        const head = headers.map(cell => `<th>${inlineMarkdown(cell)}</th>`).join("");
        const body = rows.map(row => `<tr>${headers.map((_h, column) => `<td>${inlineMarkdown(row[column] || "")}</td>`).join("")}</tr>`).join("");
        html.push(`<div class="prose-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
        continue;
      }
      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) { flushParagraph(); flushList(); const level = Math.min(3, heading[1].length); html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
      const bullet = trimmed.match(/^[-*+]\s+(.+)$/);
      const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (bullet || numbered) {
        flushParagraph();
        const nextType = bullet ? "ul" : "ol";
        if (listType !== nextType) { flushList(); html.push(`<${nextType}>`); listType = nextType; }
        html.push(`<li>${inlineMarkdown((bullet || numbered)[1])}</li>`);
        continue;
      }
      const quote = trimmed.match(/^>\s?(.*)$/);
      if (quote) { flushParagraph(); flushList(); html.push(`<blockquote><p>${inlineMarkdown(quote[1])}</p></blockquote>`); continue; }
      if (/^(---+|\*\*\*+|___+)$/.test(trimmed)) { flushParagraph(); flushList(); html.push('<hr class="prose-divider">'); continue; }
      flushList();
      paragraph.push(trimmed);
    }
    if (codeFence) flushCode();
    flushParagraph(); flushList();
    return html.join("");
  }

  function routeName(type) {
    if (type === "person" || type === "ruler" || type === "era") return type;
    return "event";
  }
  function renderDetail(type, id) {
    closePanel();
    const item = getRecord(type, id);
    if (!item) {
      app.innerHTML = `<section class="not-found"><span class="eyebrow">СТРАНИЦА НЕ НАЙДЕНА</span><h1>Этой записи пока нет.</h1><p>Вернитесь к карте и выберите другую запись.</p><a class="button-primary" href="#timeline">Вернуться к хронологии</a></section>`;
      updateNav("timeline");
      return;
    }
    const date = recordDate(item, type);
    const trackName = currentTrackName(item, type);
    const category = type === "era" ? "историческая эпоха" : type === "ruler" ? (item.title || "правитель") : type === "person" ? item.activityLabel : (KIND_NAMES[item.kind] || CATEGORY_NAMES[item.branch] || "событие");
    const markdown = typeof item.body === "string" ? item.body : Array.isArray(item.detail) ? item.detail.join("\n\n") : "";
    const summary = item.summary || "";
    const related = relatedRecords(type, item);
    const year = type === "ruler" ? item.start : type === "person" ? item.born : type === "era" ? item.from : item.year;
    const branchName = type === "ruler" ? "Правители" : type === "person" ? "Личности" : type === "era" ? "Эпохи" : CATEGORY_NAMES[item.branch];
    const wordCount = (markdown + " " + summary).replace(/[#*`\[\]]/g, "").split(/\s+/).filter(Boolean).length;
    const readingTime = Math.max(1, Math.round(wordCount / 180));
    const relatedHTML = related.length ? related.map(record => `<a class="related-link" href="#${routeName(record.type)}/${escapeHTML(record.item.id)}"><span>${escapeHTML(record.item.title || record.item.name)}</span><small>${escapeHTML(recordDate(record.item, record.type))}</small><b aria-hidden="true">↗</b></a>`).join("") : `<p class="related-empty">Для этой записи скоро появятся связанные материалы.</p>`;
    app.innerHTML = `<div class="detail-page"><div class="detail-crumbs"><a href="#timeline">Хронология</a><span>/</span><a href="#timeline">${escapeHTML(branchName)}</a><span>/</span><span>${escapeHTML(item.title || item.name)}</span></div><div class="detail-grid"><article class="detail-article"><div class="detail-kicker"><span class="detail-dot"></span>${escapeHTML(category)}<i></i>${escapeHTML(trackName)}</div><div class="detail-date">${escapeHTML(date)}</div><h1>${escapeHTML(item.title || item.name)}</h1>${summary ? `<p class="detail-lead">${escapeHTML(summary)}</p>` : ""}<div class="detail-byline"><span class="byline-mark">AH</span><span>КАРТА ИСТОРИИ</span><i></i><span>${readingTime} МИН ЧТЕНИЯ</span></div><div class="detail-prose">${renderMarkdown(markdown || summary)}</div><div class="detail-tags">${(item.tags || []).map(tag => `<span>#${escapeHTML(tag)}</span>`).join("")}</div><div class="detail-endnote"><span>✳</span><p>Материал из расширяемой редакционной базы Adam's History. Для публикации добавьте в заметку проверяемые источники и при необходимости уточните датировки.</p></div></article><aside class="detail-aside"><div class="context-card"><span class="eyebrow">КООРДИНАТА ВО ВРЕМЕНИ</span><strong>${escapeHTML(date)}</strong><div class="context-ruler"><span style="left:${Math.max(2, Math.min(98, timeFraction(year) * 100)).toFixed(1)}%"></span></div><div class="context-range"><span>${escapeHTML(formatAxisYear(DOMAIN_START))}</span><span>${escapeHTML(formatAxisYear(DOMAIN_END))}</span></div><button type="button" class="button-primary" data-action="show-on-map" data-type="${type}" data-id="${escapeHTML(item.id)}">Показать на карте <span aria-hidden="true">↗</span></button></div><div class="related-card"><span class="eyebrow">РЯДОМ НА ШКАЛЕ</span><h3>Связанные истории</h3>${relatedHTML}</div><a class="back-map-link" href="#timeline">← Вернуться к карте</a></aside></div></div>`;
    updateNav("timeline");
  }

  function renderAbout() {
    closePanel();
    app.innerHTML = `<div class="about-page"><div class="detail-crumbs"><a href="#timeline">Хронология</a><span>/</span><span>О проекте</span></div><section class="about-hero"><span class="eyebrow">ЗАМЫСЕЛ ПРОЕКТА</span><h1>Увидеть историю<br><em>в связях и масштабе.</em></h1><p>Adam's History — интерактивный исторический атлас от 12 000 года до н. э. до 1900 года н. э. с тематическими ветвями, персональными линиями и статьями об эпохах.</p></section><section class="about-grid"><article><span class="about-number">01</span><h2>Сравнивать регионы</h2><p>Линии государств упорядочены географически. Выберите один регион или несколько для сравнения; шкала целиком доступна горизонтальной прокруткой.</p></article><article><span class="about-number">02</span><h2>Настраивать масштаб</h2><p>Шкала нелинейна: более поздним векам отведено больше места. Введите точные даты, перейдите к эпохе или увеличьте временной отрезок — прокрутка по всей истории сохранится.</p></article><article><span class="about-number">03</span><h2>Читать разные истории</h2><p>Правители, наука, искусство и годы жизни персон показаны отдельными слоями. Цвет персон зависит только от государства или политического контекста.</p></article></section><section class="about-data-note"><div class="about-data-symbol">i</div><div><span class="eyebrow">О ДАННЫХ</span><h2>Редактируемая база в Markdown</h2><p>События, персоны, правители, регионы и эпохи хранятся как заметки с YAML frontmatter и Markdown-текстом. Их можно вести в Obsidian; скрипт без сторонних библиотек собирает <code>content-index.json</code> для статического сайта.</p></div></section><section class="about-howto"><span class="eyebrow">КАК ПОПОЛНЯТЬ КАРТУ</span><h2>Редактируйте заметки, а не код.</h2><ol><li><b>Откройте папку <code>content/</code> как vault в Obsidian.</b> Готовые шаблоны лежат в <code>content/templates/</code>.</li><li><b>Создайте заметку события или персоны.</b> Укажите уникальный <code>id</code>, год, ветку и точный ID линии; краткая справка задаётся в YAML, полная статья — обычным Markdown-текстом ниже.</li><li><b>Проверьте и соберите индекс:</b> выполните <code>python3 scripts/build_content.py</code>. Скрипт проверит обязательные поля, уровни детализации и ссылки на линии.</li><li><b>Опубликуйте проект вместе с <code>content-index.json</code>.</b> Для GitHub Pages не нужен сервер или сборщик; исходные заметки остаются в репозитории.</li></ol><a class="button-primary" href="#timeline">Открыть хронологию <span aria-hidden="true">↗</span></a></section></div>`;
    updateNav("about");
  }

  function updateNav(active) {
    document.querySelectorAll("[data-nav]").forEach(link => {
      const isActive = link.dataset.nav === active;
      link.classList.toggle("is-active", isActive);
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }
  function routeInfo() {
    const hash = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (!hash || hash === "timeline") return { page: "timeline" };
    if (hash === "about") return { page: "about" };
    if (hash.startsWith("event/")) return { page: "detail", type: "event", id: hash.slice(6) };
    if (hash.startsWith("ruler/")) return { page: "detail", type: "ruler", id: hash.slice(6) };
    if (hash.startsWith("person/")) return { page: "detail", type: "person", id: hash.slice(7) };
    if (hash.startsWith("era/")) return { page: "detail", type: "era", id: hash.slice(4) };
    return { page: "timeline" };
  }
  function renderRoute() {
    const route = routeInfo();
    if (route.page === "about") renderAbout();
    else if (route.page === "detail") renderDetail(route.type, route.id);
    else renderTimeline();
  }

  function jumpToEra(eraId) {
    const era = DATA.eras.find(item => item.id === eraId);
    if (!era) return;
    state.branch = "states";
    state.selectedRegions.clear();
    focusWindow(era.from, era.to, 1.14);
    renderTimeline();
    document.getElementById("timeline")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function jumpToPeriod(trackId, index) {
    const track = stateTrackById(trackId);
    const period = track?.periods[Number(index)];
    if (!track || !period) return;
    state.branch = "states";
    state.selectedRegions = new Set([track.id]);
    focusWindow(period.from, period.to, 1.22);
    renderTimeline();
    document.getElementById("timeline")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function focusTrack(branch, trackId) {
    state.branch = branch;
    const track = tracksForBranch(branch).find(item => item.id === trackId);
    if (!track) return;
    if (branch === "states" && track.periods?.length) {
      const nearest = track.periods.reduce((best, current) => Math.abs((current.from + current.to) / 2 - state.center) < Math.abs((best.from + best.to) / 2 - state.center) ? current : best);
      state.selectedRegions = new Set([trackId]);
      focusWindow(nearest.from, nearest.to, 1.28);
    } else {
      const records = branch === "rulers" ? DATA.rulers.filter(item => item.track === trackId) : branchEvents(branch).filter(item => item.track === trackId);
      if (records.length) {
        const nearest = records.reduce((best, current) => {
          const y = branch === "rulers" ? current.start : current.year;
          const bestY = branch === "rulers" ? best.start : best.year;
          return Math.abs(y - state.center) < Math.abs(bestY - state.center) ? current : best;
        });
        const year = branch === "rulers" ? (nearest.start + nearest.end) / 2 : nearest.year;
        focusWindow(year - 250, year + 250, 1.5);
      }
    }
    renderTimeline();
    document.getElementById("timeline")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function showOnMap(type, id) {
    const item = getRecord(type, id);
    if (!item) return;
    const year = type === "ruler" ? (item.start + item.end) / 2 : type === "person" ? item.born : type === "era" ? (item.from + item.to) / 2 : item.year;
    state.branch = type === "ruler" ? "rulers" : type === "person" || type === "era" ? "states" : item.branch;
    if (type === "event" && item.branch === "states") state.selectedRegions = new Set([item.track]);
    if (type === "person" || type === "era") state.selectedRegions.clear();
    if (type === "era") focusWindow(item.from, item.to, 1.14);
    else focusWindow(type === "person" ? item.born : year - 350, type === "person" ? item.died : year + 350, type === "person" ? 1.35 : 1.45);
    closePanel();
    const alreadyTimeline = routeInfo().page === "timeline";
    if (location.hash !== "#timeline") location.hash = "#timeline";
    if (alreadyTimeline) renderTimeline();
    requestAnimationFrame(() => document.getElementById("timeline")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
  function panTimeline(direction) {
    const scroll = document.getElementById("timelineScroll");
    const geometry = timelineGeometry(scroll);
    if (!scroll || !geometry) return;
    const step = Math.max(120, geometry.plotWidth * 0.72);
    scroll.scrollLeft = Math.max(0, Math.min(scroll.scrollWidth - scroll.clientWidth, scroll.scrollLeft + direction * step));
    updateVisibleRange();
  }
  function toggleRegion(regionId) {
    if (regionId === "all") state.selectedRegions.clear();
    else if (state.selectedRegions.size === 0) state.selectedRegions.add(regionId);
    else {
      if (state.selectedRegions.has(regionId)) state.selectedRegions.delete(regionId);
      else state.selectedRegions.add(regionId);
    }
    renderTimeline();
  }
  function selectDetailLevel(levelId) {
    if (DETAIL_LEVELS.some(level => level.id === levelId)) { state.detailLevel = levelId; renderTimeline(); }
  }
  function selectQuickJump(value) {
    if (!value) return;
    const parts = value.split("|");
    if (parts[0] === "era") jumpToEra(parts[1]);
    if (parts[0] === "period") jumpToPeriod(parts[1], parts[2]);
  }
  function applyDateRange() {
    const fromInput = document.getElementById("dateFrom");
    const toInput = document.getElementById("dateTo");
    const error = document.getElementById("rangeError");
    if (!fromInput || !toInput || !error) return;
    const from = fromInput.valueAsNumber;
    const to = toInput.valueAsNumber;
    error.textContent = "";
    if (!Number.isFinite(from) || !Number.isFinite(to)) { error.textContent = "Укажите обе границы диапазона."; return; }
    if (from < DOMAIN_START || to > DOMAIN_END) { error.textContent = "Доступный интервал: −12 000…1900."; return; }
    if (from >= to) { error.textContent = "Начальная дата должна быть раньше конечной."; return; }
    setCurrentRange((from + to) / 2, to - from);
    renderTimeline();
    document.getElementById("timeline")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function searchMatches(query) {
    const normalized = query.trim().toLocaleLowerCase("ru-RU");
    if (normalized.length < 2) return [];
    return ALL_RECORDS.filter(({ item }) => [item.title, item.name, item.summary, item.dateLabel, ...(item.tags || [])].join(" ").toLocaleLowerCase("ru-RU").includes(normalized)).slice(0, 9);
  }
  function renderSearchResults(query) {
    const matches = searchMatches(query);
    if (query.trim().length < 2) { searchResults.hidden = true; searchResults.innerHTML = ""; return; }
    const list = matches.map(({ item, type }) => {
      const route = routeName(type);
      const icon = type === "person" ? "♙" : type === "ruler" ? "♜" : type === "era" ? "◷" : "◉";
      return `<a class="search-result" href="#${route}/${escapeHTML(item.id)}"><span class="search-result-icon">${icon}</span><span><strong>${escapeHTML(item.title || item.name)}</strong><small>${escapeHTML(recordDate(item, type))} · ${escapeHTML(currentTrackName(item, type))}</small></span><b aria-hidden="true">↗</b></a>`;
    }).join("");
    searchResults.innerHTML = `<div class="search-results-heading">РЕЗУЛЬТАТЫ ПОИСКА <span>${matches.length}${matches.length === 9 ? "+" : ""}</span></div>${list || `<div class="search-empty">Ничего не найдено. Попробуйте другое слово.</div>`}`;
    searchResults.hidden = false;
  }

  document.addEventListener("pointerover", event => {
    const target = event.target.closest?.("[data-tooltip]");
    if (!target || target === currentTooltipTarget) return;
    currentTooltipTarget = target;
    showTooltip(target);
  });
  document.addEventListener("pointerout", event => {
    const target = event.target.closest?.("[data-tooltip]");
    if (target && target === currentTooltipTarget && !target.contains(event.relatedTarget)) hideTooltip();
  });
  document.addEventListener("focusin", event => {
    const target = event.target.closest?.("[data-tooltip]");
    if (!target) return;
    currentTooltipTarget = target;
    showTooltip(target);
  });
  document.addEventListener("focusout", event => {
    const target = event.target.closest?.("[data-tooltip]");
    if (target && target === currentTooltipTarget && !target.contains(event.relatedTarget)) hideTooltip();
  });

  document.addEventListener("click", event => {
    const target = event.target;
    const actionButton = target.closest("[data-action]");
    if (actionButton) {
      const action = actionButton.dataset.action;
      if (action === "focus-track") focusTrack(actionButton.dataset.branch, actionButton.dataset.track);
      else if (action === "focus-period") jumpToPeriod(actionButton.dataset.track, actionButton.dataset.periodIndex);
      else if (action === "jump-era") jumpToEra(actionButton.dataset.era);
      else if (action === "zoom-in" || action === "zoom-out") {
        const range = getRange();
        setCurrentRange(state.center, action === "zoom-in" ? range.span / ZOOM_FACTOR : range.span * ZOOM_FACTOR);
        renderTimeline();
      } else if (action === "reset-zoom") {
        state.viewRange = null; state.zoomLevel = 1; state.center = -2500; state.pendingFocusYear = -2500; renderTimeline();
      } else if (action === "pan-left" || action === "pan-right") {
        panTimeline(action === "pan-left" ? -1 : 1);
      } else if (action === "show-on-map") showOnMap(actionButton.dataset.type, actionButton.dataset.id);
      return;
    }
    const branchButton = target.closest(".branch-tab[data-branch]");
    if (branchButton) { state.branch = branchButton.dataset.branch; renderTimeline(); return; }
    const regionButton = target.closest("[data-region-filter]");
    if (regionButton) { toggleRegion(regionButton.dataset.regionFilter); return; }
    const detailButton = target.closest("[data-detail-level]");
    if (detailButton) { selectDetailLevel(detailButton.dataset.detailLevel); return; }
    if (!target.closest(".header-search")) searchResults.hidden = true;
  });

  document.addEventListener("change", event => {
    if (event.target.id === "quickJump") { selectQuickJump(event.target.value); event.target.value = ""; }
  });
  document.addEventListener("submit", event => {
    if (event.target.id === "dateRangeForm") { event.preventDefault(); applyDateRange(); }
  });
  searchInput.addEventListener("input", event => renderSearchResults(event.target.value));
  searchInput.addEventListener("focus", () => { if (searchInput.value.trim().length >= 2) renderSearchResults(searchInput.value); });
  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); searchInput.focus(); searchInput.select(); }
    if (event.key === "Escape") { closePanel(); searchResults.hidden = true; searchInput.blur(); }
  });
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (routeInfo().page === "timeline") renderTimeline(); }, 160);
  });
  window.addEventListener("hashchange", renderRoute);
  renderRoute();
})();
