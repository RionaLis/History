// Общая логика внутренних страниц (списки и статьи).
import { formatYear, formatSpan } from './scale.js';
import { renderMarkdown, stripFrontmatter } from './md.js';
import { ICON_LABELS, drawIcon } from './icons.js';

export const TYPE_LABEL = {
  state: 'государство', empire: 'империя', people: 'народ',
  culture: 'культура', polity: 'политии', colony: 'колония', confed: 'союз',
};
export const KIND_LABEL = {
  migration: 'переселение', invasion: 'вторжение', trade: 'торговля', diffusion: 'распространение',
};

export const BASE = '../';
export const $ = s => document.querySelector(s);

export async function loadData() {
  const r = await fetch(BASE + 'data/index.json', { cache: 'no-cache' });
  return r.json();
}

export function topbar(active) {
  const links = [['index.html', 'Таблица'], ['pages/regions.html', 'Регионы'],
                 ['pages/events.html', 'События'], ['pages/entity.html', 'Статьи'],
                 ['pages/about.html', 'О проекте']];
  return `<header class="topbar">
    <div class="brand"><span class="brand-mark"></span>
      <div><b>Хронолента мира</b><small>синхронологическая таблица · 3000 до н.э. — 2000 н.э.</small></div>
    </div>
    <nav class="nav">${links.map(([h, t]) =>
      `<a class="${t === active ? 'active' : ''}" href="${BASE}${h}">${t}</a>`).join('')}</nav>
  </header>`;
}

export function entityHref(kind, id) {
  return `${BASE}pages/entity.html?kind=${kind}&id=${encodeURIComponent(id)}`;
}
export function chartHref(kind, id) {
  const p = { entity: 'e', event: 'v', migration: 'm', region: 'r', era: 'a' }[kind] || 'e';
  return `${BASE}index.html#${p}/${id}`;
}

export function collections(data) {
  return { entity: data.entities, event: data.events, migration: data.migrations,
           region: data.regions, era: data.eras };
}

export function describe(obj, kind, data) {
  if (kind === 'entity') {
    const regs = (obj.regions || []).map(id =>
      (data.regions.find(r => r.id === id) || {}).short).filter(Boolean);
    return [TYPE_LABEL[obj.type] || obj.type, formatSpan(obj.start, obj.end), ...regs];
  }
  if (kind === 'event') {
    return [ICON_LABELS[obj.icon] || obj.icon,
      obj.yearEnd ? formatSpan(obj.year, obj.yearEnd) : formatYear(obj.year)];
  }
  if (kind === 'migration') return [KIND_LABEL[obj.kind] || obj.kind, formatSpan(obj.start, obj.end)];
  if (kind === 'region') return ['регион', `${obj.lanes.length} суб-региона`];
  if (kind === 'era') return ['эпоха', formatSpan(obj.start, obj.end)];
  return [];
}

export async function renderArticle(container, obj, kind, data) {
  const badges = describe(obj, kind, data)
    .map(t => `<span class="badge">${t}</span>`).join('');
  let md = '';
  try {
    const r = await fetch(BASE + obj.path, { cache: 'no-cache' });
    md = stripFrontmatter(await r.text()).body;
  } catch (e) { md = '*Текст статьи не найден.*'; }
  container.innerHTML = `
    <div class="panel-badges">${badges}
      <a class="badge" href="${chartHref(kind, obj.id)}">↗ показать на таблице</a>
      <a class="badge" href="${BASE + obj.path}" target="_blank">исходный .md</a>
    </div>
    <div class="article-body">${renderMarkdown(md)}</div>`;
  container.querySelectorAll('a.wikilink').forEach(a => {
    const name = a.dataset.wiki.toLowerCase();
    const all = collections(data);
    for (const [k, coll] of Object.entries(all)) {
      const hit = coll.find(x => (x.name || '').toLowerCase() === name
        || (x.short || '').toLowerCase() === name);
      if (hit) { a.href = entityHref(k, hit.id); return; }
    }
    a.classList.add('dead');
  });
}

export function iconCanvas(icon, size = 20) {
  const cv = document.createElement('canvas');
  cv.width = size * 2; cv.height = size * 2;
  cv.style.width = size + 'px'; cv.style.height = size + 'px';
  const cx = cv.getContext('2d');
  cx.setTransform(2, 0, 0, 2, 0, 0);
  drawIcon(cx, icon, size / 2, size / 2, size * 0.38, { halo: false });
  return cv;
}
