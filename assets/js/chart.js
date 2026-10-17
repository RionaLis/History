// Отрисовка и интерактив синхронологической таблицы.
import { TimeScale, ticksForRange, formatAxisYear } from './scale.js';
import { computeLanes, layoutEntities } from './layout.js';
import { drawIcon } from './icons.js';

// Гоминины, народы и археологические культуры рисуются «мягко»: подпись — просто
// текст без плашки, лента почти без окантовки. Государства, империи и
// цивилизационные области остаются в рамке.
const SOFT_TYPES = new Set(['people', 'culture', 'nature', 'hominin']);

const MIG_STYLE = {
  migration: { color: '#3f3528', dash: [5, 3.5] },
  invasion: { color: '#8f2222', dash: [] },
  trade: { color: '#1b5f5a', dash: [2, 2.6] },
  diffusion: { color: '#3f4f7d', dash: [1, 2.6] },
};

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const v = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}
function shade(hex, f) {
  const [r, g, b] = hexToRgb(hex);
  const m = v => Math.max(0, Math.min(255, Math.round(f > 0 ? v + (255 - v) * f : v * (1 + f))));
  return `rgb(${m(r)},${m(g)},${m(b)})`;
}

export class Chart {
  constructor(canvas, data, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.data = data;
    this.scale = new TimeScale(data.scaleAnchors, 'poster');
    this.maxZoom = 100000;
    const defaultRange = data.meta?.defaultRange || [-12000, 2000];
    const defaultU0 = this.scale.unit(defaultRange[0]);
    const defaultU1 = this.scale.unit(defaultRange[1]);
    this.view = { k: 1 / (defaultU1 - defaultU0), ux: defaultU0, vy: 0 };
    // eraH = 0: лента эпох рисуется первой дорожкой региона «Весь мир» (wd_era)
    this.geom = { gutterW: 196, axisH: 32, eraH: 0, pad: 0 };
    this.eraLaneId = 'wd_era';
    this.rowUnit = 16;
    this.fitRows = true;
    this.filters = {
      regions: new Set(data.regions.map(r => r.id)),
      types: new Set(data.entities.map(e => e.type)),
      showEvents: false, showMigrations: true, showLabels: true,   // события пока скрыты
      iconTypes: new Set(data.icons.map(i => i.id)),
      query: '',
    };
    this.hover = null;
    this.selectedId = null;
    this.highlightIds = null;   // Set — подсветка результатов поиска
    this.onHover = opts.onHover || (() => {});
    this.onSelect = opts.onSelect || (() => {});
    this.onView = opts.onView || (() => {});
    // На главной страница прокручивается целиком: высота canvas следует
    // за полной раскладкой дорожек, а не за окном просмотра.
    this.autoHeight = !!opts.autoHeight;
    this._eventBoxes = [];
    this._migPaths = [];
    this._eraBoxes = [];
    this.rebuild();
    this._bindEvents();
  }

  // ---------- данные и раскладка ----------
  rebuild() {
    const regions = this.data.regions.filter(r => this.filters.regions.has(r.id));
    this.lanesLayout = computeLanes(regions, { rowUnit: this.rowUnit, regionGap: 7 });
    const laneIds = this.lanesLayout.lanes.map(l => l.id);
    const ents = this.data.entities.filter(e => this.filters.types.has(e.type));
    this.strips = layoutEntities(ents, laneIds);
    this.entityById = new Map(this.data.entities.map(e => [e.id, e]));
    this.syncStageHeight();
  }

  /** На главной выделяем место под все дорожки; таблица не обрезается по высоте. */
  syncStageHeight() {
    if (!this.autoHeight) return;
    const stage = this.canvas.closest('.stage');
    if (!stage) return;
    const height = Math.ceil(this.plotY() + this.lanesLayout.height + 1);
    stage.style.height = `${Math.max(300, height)}px`;
  }

  setRowUnit(v) { this.rowUnit = v; this.fitRows = false; this.rebuild(); this.clampView(); this.draw(); }

  fitRowsToView() {
    const regions = this.data.regions.filter(r => this.filters.regions.has(r.id));
    const wsum = regions.reduce((s, r) => s + r.lanes.reduce((a, l) => a + (l.weight || 1), 0), 0);
    const gaps = Math.max(0, regions.length - 1) * 7;
    const h = this.plotH() - gaps;
    this.rowUnit = Math.max(12, Math.min(44, h / Math.max(1, wsum)));
    this.fitRows = true;
    this.rebuild();
    this.view.vy = 0;
    this.draw();
  }

  // ---------- геометрия ----------
  cssSize() {
    const r = this.canvas.getBoundingClientRect();
    return { w: r.width, h: r.height };
  }
  plotX() { return this.geom.gutterW; }
  plotY() { return this.geom.axisH + this.geom.eraH; }
  plotW() { return Math.max(50, this.cssSize().w - this.geom.gutterW); }
  plotH() { return Math.max(50, this.cssSize().h - this.plotY()); }
  contentW() { return this.plotW() * this.view.k; }
  xOf(year) { return this.plotX() + (this.scale.unit(year) - this.view.ux) * this.contentW(); }
  yearOf(px) { return this.scale.year((px - this.plotX()) / this.contentW() + this.view.ux); }
  yOf(lane, t) { return this.plotY() + lane.y - this.view.vy + t * lane.h; }

  clampView() {
    const v = this.view;
    v.k = Math.max(1, Math.min(this.maxZoom, v.k));
    v.ux = Math.max(0, Math.min(1 - 1 / v.k, v.ux));
    const maxVy = Math.max(0, this.lanesLayout.height - this.plotH());
    v.vy = Math.max(0, Math.min(maxVy, v.vy));
  }

  visibleYears() {
    return [this.yearOf(this.plotX()), this.yearOf(this.plotX() + this.plotW())];
  }

  /** Сменить проекцию, не меняя видимые крайние даты. */
  setScaleMode(mode, source = 'programmatic') {
    if (this.scale.mode === mode) return;
    const [yearA, yearB] = this.visibleYears();
    this.scale.setMode(mode);
    const u0 = this.scale.unit(yearA), u1 = this.scale.unit(yearB);
    this.view.k = 1 / Math.max(1e-12, u1 - u0);
    this.view.ux = u0;
    this.clampView();
    this.draw();
    this.onView(this, source);
  }

  /** Подобрать масштаб так, чтобы на экране было ~span лет вокруг центра. */
  setVisibleSpan(span, center, source = 'programmatic') {
    const [a, b] = this.visibleYears();
    const c = center ?? (a + b) / 2;
    const y0 = Math.max(this.scale.yearMin, c - span / 2);
    const y1 = Math.min(this.scale.yearMax, y0 + span);
    const du = Math.max(1e-6, this.scale.unit(y1) - this.scale.unit(y0));
    this.view.k = 1 / du;
    // левый край окна — точно в y0: на нелинейной шкале unit(центр) ≠ середины
    // unit-окна, и «центровка по середине» уводила рамку в плотный участок.
    this.view.ux = this.scale.unit(y0);
    this.clampView();
    this.draw();
    this.onView(this, source);
  }

  centerOn(year, source = 'programmatic') {
    const u = this.scale.unit(year);
    this.view.ux = u - 0.5 / this.view.k;
    this.clampView();
    this.draw();
    this.onView(this, source);
  }

  zoomAt(px, factor, source = 'programmatic') {
    const uAt = (px - this.plotX()) / this.contentW() + this.view.ux;
    this.view.k *= factor;
    this.clampView();
    this.view.ux = uAt - (px - this.plotX()) / this.contentW();
    this.clampView();
    this.draw();
    this.onView(this, source);
  }

  zoomToRange(y0, y1, padFrac = 0.12, source = 'programmatic') {
    const u0 = this.scale.unit(y0), u1 = this.scale.unit(y1);
    const du = Math.max(1e-5, (u1 - u0) * (1 + padFrac * 2));
    this.view.k = 1 / du;
    this.clampView();
    this.view.ux = Math.max(0, u0 - (u1 - u0) * padFrac);
    this.clampView();
    this.draw();
    this.onView(this, source);
  }

  scrollToLane(laneId) {
    const lane = this.lanesLayout.byId.get(laneId);
    if (!lane) return;
    const target = lane.y + lane.h / 2 - this.plotH() / 2;
    this.view.vy = target;
    this.clampView();
  }

  // ---------- отрисовка ----------
  draw() {
    const dpr = window.devicePixelRatio || 1;
    const { w, h } = this.cssSize();
    if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#f7f5f0';
    ctx.fillRect(0, 0, w, h);
    this.clampView();

    const px = this.plotX(), py = this.plotY(), pw = this.plotW(), ph = this.plotH();
    ctx.save();
    ctx.beginPath(); ctx.rect(px, py, pw, ph); ctx.clip();
    this._drawBands(ctx);
    this._drawGrid(ctx);
    this._drawEraLane(ctx);
    this._drawRibbons(ctx);
    if (this.filters.showMigrations) this._drawMigrations(ctx);
    if (this.filters.showEvents) this._drawEvents(ctx);
    ctx.restore();

    this._drawGutter(ctx);
    this._drawAxis(ctx);
    this._drawScrollbar(ctx);
    this._drawTimeMarker(ctx);
  }

  /** Красная черта выбранной даты (с шкалой карты) на большой таблице. */
  _drawTimeMarker(ctx) {
    const st = window.chronomap && window.chronomap.state;
    if (!st || typeof st.year !== 'number') return;
    const px = this.plotX(), pw = this.plotW();
    const x = this.xOf(st.year);
    if (!(x >= px - 1 && x <= px + pw + 1)) return;
    const py = this.plotY(), ph = this.plotH();
    ctx.save();
    ctx.strokeStyle = '#d13b3b';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, py); ctx.lineTo(x, py + ph); ctx.stroke();
    // засечка на оси дат
    ctx.fillStyle = '#d13b3b';
    ctx.beginPath();
    ctx.moveTo(x - 5, py - 9); ctx.lineTo(x + 5, py - 9); ctx.lineTo(x, py - 1);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  _drawBands(ctx) {
    const px = this.plotX(), pw = this.plotW();
    for (const b of this.lanesLayout.bands) {
      const y = this.plotY() + b.y - this.view.vy;
      if (y + b.h < this.plotY() || y > this.plotY() + this.plotH()) continue;
      ctx.fillStyle = `hsla(${b.hue}, 30%, 94%, 1)`;
      ctx.fillRect(px, y, pw, b.h);
    }
    ctx.strokeStyle = 'rgba(0,0,0,0.07)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const l of this.lanesLayout.lanes) {
      const y = Math.round(this.yOf(l, 1)) + 0.5;
      if (y < this.plotY() || y > this.plotY() + this.plotH()) continue;
      ctx.moveTo(px, y); ctx.lineTo(px + pw, y);
    }
    ctx.stroke();
    // жирные границы макро-регионов, как на плакате
    ctx.strokeStyle = 'rgba(25,28,36,0.55)';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    for (const b of this.lanesLayout.bands) {
      for (const yy of [b.y, b.y + b.h]) {
        const y = Math.round(this.plotY() + yy - this.view.vy) + 0.5;
        if (y < this.plotY() - 1 || y > this.plotY() + this.plotH() + 1) continue;
        ctx.moveTo(px, y); ctx.lineTo(px + pw, y);
      }
    }
    ctx.stroke();
  }

  _drawGrid(ctx) {
    const px = this.plotX(), pw = this.plotW(), py = this.plotY(), ph = this.plotH();
    const [ya, yb] = this.visibleYears();
    const ticks = ticksForRange(this.scale, ya, yb, pw, 90);
    ctx.lineWidth = 1;
    for (const tick of ticks) {
      const x = Math.round(this.xOf(tick.year)) + 0.5;
      ctx.strokeStyle = tick.major ? 'rgba(40,40,50,0.22)' : 'rgba(40,40,50,0.09)';
      ctx.beginPath(); ctx.moveTo(x, py); ctx.lineTo(x, py + ph); ctx.stroke();
    }
    // рубеж эр
    const x0 = Math.round(this.xOf(0)) + 0.5;
    if (x0 > px && x0 < px + pw) {
      ctx.strokeStyle = 'rgba(160,40,40,0.55)'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x0, py); ctx.lineTo(x0, py + ph); ctx.stroke();
    }
  }

  _drawRibbons(ctx) {
    const py = this.plotY(), ph = this.plotH();
    const px = this.plotX(), pw = this.plotW();
    const labels = [];
    for (const lane of this.lanesLayout.lanes) {
      const ly = this.plotY() + lane.y - this.view.vy;
      if (ly + lane.h < py - 2 || ly > py + ph + 2) continue;
      const strips = this.strips.get(lane.id) || [];
      for (const s of strips) {
        const e = s.entity;
        const dim = this.highlightIds && !this.highlightIds.has(e.id);
        const sel = this.selectedId === e.id;
        const hov = this.hover && this.hover.kind === 'entity' && this.hover.id === e.id;
        for (const run of s.runs) {
          if (run[run.length - 1][0] < this.yearOf(px) || run[0][0] > this.yearOf(px + pw)) continue;
          ctx.beginPath();
          for (let i = 0; i < run.length; i++) {
            const x = this.xOf(run[i][0]), y = this.yOf(lane, run[i][1]);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          }
          for (let i = run.length - 1; i >= 0; i--) {
            ctx.lineTo(this.xOf(run[i][0]), this.yOf(lane, run[i][2]));
          }
          ctx.closePath();
          ctx.globalAlpha = dim ? 0.18 : 1;
          const soft = SOFT_TYPES.has(e.type);   // народы и культуры — мягкие поля
          let fillStyle;
          if (soft) {
            if (!window.hatchPatterns) window.hatchPatterns = {};
            if (!window.hatchPatterns[e.type]) {
              const c = document.createElement('canvas');
              c.width = 6; c.height = 6;
              const ctx2 = c.getContext('2d');
              ctx2.strokeStyle = e.color || '#5a4632';
              ctx2.lineWidth = 0.7;
              ctx2.beginPath();
              ctx2.moveTo(0, 0);
              ctx2.lineTo(6, 6);
              ctx2.stroke();
              window.hatchPatterns[e.type] = ctx2.createPattern(c, 'repeat');
            }
            fillStyle = window.hatchPatterns[e.type];
          } else {
            fillStyle = e.color;
          }
          ctx.fillStyle = (sel || hov) ? shade(e.color, 0.22) : fillStyle;
          ctx.fill();
          ctx.lineWidth = sel ? 2 : (hov ? 1.4 : (soft ? 1 : 0.6));
          ctx.strokeStyle = sel ? '#1b2a4a'
            : (hov ? 'rgba(20,25,40,.75)'
                   : (soft ? 'rgba(30,35,45,0.5)' : 'rgba(30,35,45,0.35)'));
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        if (this.filters.showLabels && !dim) labels.push({ lane, s });
      }
    }
    if (this.filters.showLabels) this._drawRibbonLabels(ctx, labels);
  }

  _drawRibbonLabels(ctx, labels) {
    const px = this.plotX(), pw = this.plotW();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    const cands = [];
    for (const { lane, s } of labels) {
      const e = s.entity;
      let best = null;
      for (const run of s.runs) {
        const xa = Math.max(px + 2, this.xOf(run[0][0]));
        const xb = Math.min(px + pw - 2, this.xOf(run[run.length - 1][0]));
        if (xb - xa < 26) continue;
        const cx = (xa + xb) / 2;
        const year = this.yearOf(cx);
        let t0 = null, t1 = null;
        for (let i = 1; i < run.length; i++) {
          if (year <= run[i][0]) {
            const a = run[i - 1], b = run[i];
            const f = b[0] === a[0] ? 0 : (year - a[0]) / (b[0] - a[0]);
            t0 = a[1] + (b[1] - a[1]) * f; t1 = a[2] + (b[2] - a[2]) * f;
            break;
          }
        }
        if (t0 == null) continue;
        const hpx = (t1 - t0) * lane.h;
        const score = Math.min(xb - xa, 400) * Math.min(hpx, 30);
        if (!best || score > best.score) best = { cx, y: this.yOf(lane, (t0 + t1) / 2), hpx, w: xb - xa, score };
      }
      if (!best || best.hpx < 7.5) continue;
      cands.push({ e, ...best });
    }
    // главная подпись — в том регионе, где лента крупнее; в остальных мельче
    const bestOf = new Map();
    for (const c of cands) {
      const prev = bestOf.get(c.e.id);
      if (!prev || c.score > prev.score) bestOf.set(c.e.id, c);
    }
    cands.sort((a, b) => b.score - a.score);
    const drawn = [];
    const hits = (r) => drawn.some(d =>
      r.x0 < d.x1 && r.x1 > d.x0 && r.y0 < d.y1 && r.y1 > d.y0);
    for (const c of cands) {
      const primary = bestOf.get(c.e.id) === c;
      const cap = primary ? 15 : 10.5;
      const fs = Math.max(8, Math.min(cap, c.hpx * 0.72));
      const soft = SOFT_TYPES.has(c.e.type);   // народ или культура — просто текст
      const setFont = (ls) => {
        ctx.font = soft
          ? `${fs.toFixed(1)}px "Segoe UI", system-ui, sans-serif`
          : `${fs < 10 ? '' : '600 '}${fs.toFixed(1)}px "Segoe UI", system-ui, sans-serif`;
        ctx.letterSpacing = `${ls.toFixed(2)}px`;
      };
      let ls = soft ? Math.max(0.3, fs * 0.08) : 0;
      setFont(ls);
      let text = c.e.label || c.e.name;
      let tw = ctx.measureText(text).width;
      // на длинных полосах народов текст «растягивается» разрядкой, как на плакате
      if (soft && text.length > 2 && tw < (c.w - 12) * 0.5) {
        const add = Math.min(fs * 0.5, (c.w - 12) * 0.55 / (text.length - 1));
        if (add > ls) { ls = add; setFont(ls); tw = ctx.measureText(text).width; }
      }
      if (tw > c.w - 6) {
        if (ls > 0.3) { ls = soft ? Math.max(0.3, fs * 0.08) : 0; setFont(ls); tw = ctx.measureText(text).width; }
      }
      if (tw > c.w - 6) {
        const short = text.split(/[(,—:]/)[0].trim();
        const sw = ctx.measureText(short).width;
        if (sw <= c.w - 6) { text = short; tw = sw; } else continue;
      }
      const cx = c.cx - ls / 2;   // measureText учитывает разрядку после последней буквы
      const box = { x0: cx - tw / 2 - 2, x1: cx + tw / 2 + 2,
                    y0: c.y - fs * 0.62, y1: c.y + fs * 0.62 };
      if (hits(box)) continue;
      drawn.push(box);
      const light = luminance(c.e.color) > (soft ? 0.38 : 0.62);
      if (soft) {
        // народы и культуры подписаны прямо по полю, без плашки-обводки
        ctx.fillStyle = light ? 'rgba(26,31,43,0.9)' : 'rgba(255,255,255,0.95)';
        ctx.fillText(text, cx, c.y);
      } else {
        ctx.lineWidth = 2.6;
        ctx.strokeStyle = light ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.35)';
        ctx.strokeText(text, cx, c.y);
        ctx.fillStyle = light ? '#1a1f2b' : '#ffffff';
        ctx.fillText(text, cx, c.y);
      }
    }
    ctx.letterSpacing = '0px';
  }

  /** Точки пути: x — по году, y — середина дорожки. Путь всегда идёт
   *  слева направо (по ходу времени), поэтому линия не может «вернуться»
   *  назад и закрутиться петлёй. */
  _migPoints(m) {
    const out = [];
    let lastX = -Infinity;
    for (const [year, laneId] of m.points) {
      const lane = this.lanesLayout.byId.get(laneId);
      if (!lane) continue;
      let x = this.xOf(year);
      if (out.length && x < lastX + 26) x = lastX + 26;   // минимальный шаг вправо
      lastX = x;
      out.push([x, this.yOf(lane, 0.5)]);
    }
    return out;
  }

  /** Линии переселений, вторжений и торговых путей — тонкие стрелки
   *  с наконечником в точке прихода, как на плакате-образце. */
  _drawMigrations(ctx) {
    this._migPaths = [];
    const py = this.plotY(), ph = this.plotH();
    const px = this.plotX(), pw = this.plotW();
    const drawnLabels = [];
    for (const m of this.data.migrations) {
      const pts = this._migPoints(m);
      if (pts.length < 2) continue;
      if (pts[pts.length - 1][0] < px - 80 || pts[0][0] > px + pw + 80) continue;
      if (!pts.some(p => p[1] > py - 60 && p[1] < py + ph + 60)) continue;
      // все миграции отображаются независимо от горизонтального spans
      const spanX = pts[pts.length - 1][0] - pts[0][0];
      const ys = pts.map(p => p[1]);
      const spanY = Math.max(...ys) - Math.min(...ys);

      const st = MIG_STYLE[m.kind] || MIG_STYLE.migration;
      const hov = this.hover && this.hover.kind === 'migration' && this.hover.id === m.id;
      const dim = this.highlightIds && !this.highlightIds.has(m.id);
      const poly = this._sampleFlow(pts);

      ctx.save();
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.globalAlpha = dim ? 0.1 : 1;
      // светлая подложка — чтобы тонкая линия читалась поверх лент
      ctx.setLineDash([]);
      ctx.lineWidth = (hov ? 3 : 1.4) + 1.4;
      ctx.strokeStyle = 'rgba(255,255,255,0.38)';
      ctx.beginPath(); this._flowCurve(ctx, pts); ctx.stroke();
      // сама линия
      ctx.globalAlpha = dim ? 0.12 : (hov ? 1 : 0.8);
      ctx.setLineDash(hov ? [] : st.dash);
      ctx.lineWidth = hov ? 2.6 : 1.3;
      ctx.strokeStyle = st.color;
      ctx.beginPath(); this._flowCurve(ctx, pts); ctx.stroke();
      ctx.setLineDash([]);

      // точка выхода, наконечники на промежуточных остановках и в конце пути
      ctx.fillStyle = st.color;
      ctx.beginPath(); ctx.arc(poly[0][0], poly[0][1], hov ? 3.2 : 2.2, 0, Math.PI * 2); ctx.fill();
      const per = Math.round((poly.length - 1) / (pts.length - 1));
      for (let k = 1; k < pts.length; k++) {
        const idx = Math.min(poly.length - 1, k * per);
        this._arrowAt(ctx, poly, idx, k === pts.length - 1 ? (hov ? 10 : 7.5) : 5.5, st.color);
      }

      // подпись вдоль линии
      if (this.filters.showLabels && !dim) {
        const place = this._pointAlong(poly, 0.52);
        if (place && place.x > px + 10 && place.x < px + pw - 10) {
          const fs = hov ? 11 : 10;
          ctx.font = `italic ${fs}px "Segoe UI", system-ui, sans-serif`;
          const tw = ctx.measureText(m.name).width;
          const box = { x0: place.x - tw / 2, x1: place.x + tw / 2,
                        y0: place.y - fs - 6, y1: place.y + 2 };
          const clash = drawnLabels.some(d =>
            box.x0 < d.x1 && box.x1 > d.x0 && box.y0 < d.y1 && box.y1 > d.y0);
          if (!clash) {
            drawnLabels.push(box);
            ctx.globalAlpha = 1;
            ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,0.92)';
            ctx.fillStyle = st.color;
            if (Math.abs(place.a) > 0.95) {
              // крутая стрелка: подпись не вдоль линии, а горизонтально сбоку
              ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
              ctx.strokeText(m.name, place.x + 7, place.y);
              ctx.fillText(m.name, place.x + 7, place.y);
            } else {
              const a = Math.max(-0.6, Math.min(0.6, place.a));
              ctx.translate(place.x, place.y); ctx.rotate(a);
              ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
              ctx.strokeText(m.name, 0, -4);
              ctx.fillText(m.name, 0, -4);
            }
          }
        }
      }
      ctx.restore();
      this._migPaths.push({ id: m.id, pts: poly, obj: m });
    }
  }

  /** Наконечник стрелки в узле ломаной — по касательной к пути. */
  _arrowAt(ctx, poly, idx, size, color) {
    const i = Math.max(1, Math.min(poly.length - 1, idx));
    const [ax, ay] = poly[i - 1], [bx, by] = poly[i];
    const ang = Math.atan2(by - ay, bx - ax);
    ctx.beginPath();
    ctx.moveTo(bx, by);
    ctx.lineTo(bx - size * Math.cos(ang - 0.4), by - size * Math.sin(ang - 0.4));
    ctx.lineTo(bx - size * Math.cos(ang + 0.4), by - size * Math.sin(ang + 0.4));
    ctx.closePath();
    ctx.fillStyle = color; ctx.fill();
  }

  /** Точка на ломаной на доле t её длины + угол наклона. */
  _pointAlong(poly, t) {
    let total = 0;
    const seg = [];
    for (let i = 1; i < poly.length; i++) {
      const d = Math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1]);
      seg.push(d); total += d;
    }
    if (total < 70) return null;
    let want = total * t, acc = 0;
    for (let i = 1; i < poly.length; i++) {
      if (acc + seg[i - 1] >= want) {
        const f = seg[i - 1] ? (want - acc) / seg[i - 1] : 0;
        const x = poly[i - 1][0] + (poly[i][0] - poly[i - 1][0]) * f;
        const y = poly[i - 1][1] + (poly[i][1] - poly[i - 1][1]) * f;
        const a = Math.atan2(poly[i][1] - poly[i - 1][1], poly[i][0] - poly[i - 1][0]);
        return { x, y, a };
      }
      acc += seg[i - 1];
    }
    return null;
  }

  /** Плавная кривая с горизонтальными касательными. Смещение контрольных
   *  точек не превышает половины шага по x, поэтому путь монотонен во
   *  времени: стрелка не заворачивает назад. */
  _flowCurve(ctx, pts) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
      const off = (x1 - x0) * 0.45;
      ctx.bezierCurveTo(x0 + off, y0, x1 - off, y1, x1, y1);
    }
  }

  /** Та же кривая ломаной — для подписей и проверки попадания курсора. */
  _sampleFlow(pts) {
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
      const off = (x1 - x0) * 0.45;
      const c1 = [x0 + off, y0], c2 = [x1 - off, y1];
      for (let s = 1; s <= 12; s++) {
        const t = s / 12, u = 1 - t;
        out.push([
          u * u * u * x0 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * x1,
          u * u * u * y0 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * y1,
        ]);
      }
    }
    return out;
  }

  _curve(ctx, pts) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    if (pts.length === 2) { ctx.lineTo(pts[1][0], pts[1][1]); return; }
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      ctx.bezierCurveTo(c1x, c1y, c2x, c2y, p2[0], p2[1]);
    }
  }

  _drawEvents(ctx) {
    this._eventBoxes = [];
    const py = this.plotY(), ph = this.plotH(), px = this.plotX(), pw = this.plotW();
    const [vy0, vy1] = this.visibleYears();
    const span = vy1 - vy0;              // сколько лет сейчас на экране
    const byLane = new Map();
    for (const ev of this.data.events) {
      if (!this.filters.iconTypes.has(ev.icon)) continue;
      if (ev.scale === 1 && span > 1200) continue;
      if (ev.scale === 2 && span > 4000) continue;
      const lane = this.lanesLayout.byId.get(ev.lane);
      if (!lane) continue;
      const x = this.xOf(ev.year);
      if (x < px - 20 || x > px + pw + 20) continue;
      const y = this.yOf(lane, 0.5);
      if (y < py - 20 || y > py + ph + 20) continue;
      if (!byLane.has(ev.lane)) byLane.set(ev.lane, []);
      byLane.get(ev.lane).push({ ev, x, y, lane });
    }
    for (const arr of byLane.values()) {
      arr.sort((a, b) => a.x - b.x);
      let lastX = -1e9, dir = 1;
      for (const it of arr) {
        const r = it.ev.scale === 3 ? 8 : it.ev.scale === 2 ? 6.5 : 5.5;
        if (it.x - lastX < r * 2.2) { it.y += dir * Math.min(it.lane.h * 0.33, r * 1.9); dir = -dir; }
        else { dir = 1; }
        lastX = it.x;
        const dim = this.highlightIds && !this.highlightIds.has(it.ev.id);
        const hov = this.hover && this.hover.kind === 'event' && this.hover.id === it.ev.id;
        ctx.globalAlpha = dim ? 0.2 : 1;
        if (it.ev.yearEnd && it.ev.yearEnd > it.ev.year) {
          const x2 = this.xOf(it.ev.yearEnd);
          if (x2 - it.x > 3) {
            ctx.strokeStyle = 'rgba(30,35,45,0.5)'; ctx.lineWidth = hov ? 3 : 1.6;
            ctx.beginPath(); ctx.moveTo(it.x, it.y); ctx.lineTo(x2, it.y); ctx.stroke();
            ctx.beginPath(); ctx.arc(x2, it.y, 2, 0, 7); ctx.fillStyle = 'rgba(30,35,45,0.6)'; ctx.fill();
          }
        }
        drawIcon(ctx, it.ev.icon, it.x, it.y, hov ? r * 1.3 : r,
          { stroke: hov ? '#0b63d6' : '#1d2330' });
        ctx.globalAlpha = 1;
        this._eventBoxes.push({ id: it.ev.id, x: it.x, y: it.y, r: r + 3, obj: it.ev });
      }
    }
  }

  _drawGutter(ctx) {
    const gw = this.geom.gutterW, py = this.plotY(), ph = this.plotH();
    ctx.save();
    ctx.beginPath(); ctx.rect(0, py, gw, ph); ctx.clip();
    ctx.fillStyle = '#efece4'; ctx.fillRect(0, py, gw, ph);
    for (const b of this.lanesLayout.bands) {
      const y = py + b.y - this.view.vy;
      ctx.fillStyle = `hsl(${b.hue}, 45%, 78%)`;
      ctx.fillRect(0, y, 26, b.h);
      ctx.strokeStyle = 'rgba(0,0,0,0.18)'; ctx.lineWidth = 1;
      ctx.strokeRect(0.5, y + 0.5, 25, b.h - 1);
      ctx.save();
      ctx.translate(13, y + b.h / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = '#20242e';
      const maxW = b.h - 6;
      let fs = 11;
      ctx.font = `700 ${fs}px "Segoe UI", system-ui, sans-serif`;
      let label = b.short;
      while (ctx.measureText(label).width > maxW && fs > 7) {
        fs -= 0.5; ctx.font = `700 ${fs}px "Segoe UI", system-ui, sans-serif`;
      }
      if (ctx.measureText(label).width <= maxW) ctx.fillText(label, 0, 0);
      ctx.restore();
    }
    for (const l of this.lanesLayout.lanes) {
      const y = py + l.y - this.view.vy;
      if (y + l.h < py || y > py + ph) continue;
      ctx.fillStyle = `hsla(${l.hue}, 35%, 90%, 1)`;
      ctx.fillRect(26, y, gw - 26, l.h);
      ctx.strokeStyle = 'rgba(0,0,0,0.08)';
      ctx.beginPath(); ctx.moveTo(26, Math.round(y + l.h) + 0.5);
      ctx.lineTo(gw, Math.round(y + l.h) + 0.5); ctx.stroke();
      ctx.fillStyle = '#2a2f3a';
      const fs = Math.max(8, Math.min(11.5, l.h * 0.62));
      ctx.font = `${fs.toFixed(1)}px "Segoe UI", system-ui, sans-serif`;
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      let name = l.name;
      const maxW = gw - 34;
      if (ctx.measureText(name).width > maxW) {
        while (name.length > 3 && ctx.measureText(name + '…').width > maxW) name = name.slice(0, -1);
        name += '…';
      }
      ctx.fillText(name, 30, y + l.h / 2);
    }
    ctx.restore();
    ctx.strokeStyle = 'rgba(0,0,0,0.25)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(gw + 0.5, py); ctx.lineTo(gw + 0.5, py + ph); ctx.stroke();
  }

  _drawAxis(ctx) {
    const { w } = this.cssSize();
    const px = this.plotX(), pw = this.plotW();
    const ah = this.geom.axisH, eh = this.geom.eraH;
    ctx.fillStyle = '#222733';
    ctx.fillRect(0, 0, w, ah);
    ctx.fillStyle = '#e9e5db';
    ctx.font = '700 12px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText('Годы', 10, ah / 2);

    const [ya, yb] = this.visibleYears();
    const ticks = ticksForRange(this.scale, ya, yb, pw, 95);
    ctx.save();
    ctx.beginPath(); ctx.rect(px, 0, pw, ah); ctx.clip();
    ctx.textAlign = 'center';
    let lastRight = -1e9;
    for (const tick of ticks) {
      const y = tick.year;
      const x = this.xOf(y);
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.beginPath(); ctx.moveTo(x, ah - 6); ctx.lineTo(x, ah); ctx.stroke();
      ctx.font = `${tick.major ? '700 13' : '400 11'}px "Segoe UI", system-ui, sans-serif`;
      ctx.fillStyle = y === 0 ? '#ffd27d' : '#f2efe7';
      const label = formatAxisYear(y, tick.step);
      const half = ctx.measureText(label).width / 2;
      const align = x - half < px + 2 ? 'left' : (x + half > px + pw - 2 ? 'right' : 'center');
      const lx = align === 'left' ? px + 3 : (align === 'right' ? px + pw - 3 : x);
      const left = align === 'left' ? lx : (align === 'right' ? lx - half * 2 : lx - half);
      if (left < lastRight + 8) continue;
      lastRight = left + half * 2;
      ctx.textAlign = align;
      ctx.fillText(label, lx, ah / 2 - 1);
      ctx.textAlign = 'center';
    }
    ctx.restore();

    // полоса эпох в шапке (включается только при geom.eraH > 0)
    if (eh <= 0) return;
    ctx.save();
    ctx.beginPath(); ctx.rect(px, ah, pw, eh); ctx.clip();
    ctx.fillStyle = '#e4e0d6'; ctx.fillRect(px, ah, pw, eh);
    ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
    for (const era of this.data.eras) {
      const x0 = this.xOf(era.start), x1 = this.xOf(era.end);
      if (x1 < px || x0 > px + pw) continue;
      ctx.fillStyle = era.color;
      ctx.fillRect(x0, ah + 1, x1 - x0, eh - 2);
      ctx.strokeStyle = 'rgba(255,255,255,0.8)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x1, ah + 1); ctx.lineTo(x1, ah + eh - 1); ctx.stroke();
      const cx = (Math.max(x0, px) + Math.min(x1, px + pw)) / 2;
      ctx.font = '600 10.5px "Segoe UI", system-ui, sans-serif';
      if (ctx.measureText(era.name).width < Math.min(x1, px + pw) - Math.max(x0, px) - 8) {
        ctx.fillStyle = 'rgba(25,28,36,0.85)';
        ctx.fillText(era.name, cx, ah + eh / 2);
      }
    }
    ctx.restore();
    ctx.fillStyle = '#d9d4c8'; ctx.fillRect(0, ah, px, eh);
    ctx.fillStyle = '#4a4e58';
    ctx.font = '600 10.5px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText('Эпохи', 10, ah + eh / 2);
  }

  /** Ленты эпох внутри дорожки «Эпохи и периоды» региона «Весь мир». */
  _drawEraLane(ctx) {
    this._eraBoxes = [];
    const lane = this.lanesLayout.byId.get(this.eraLaneId);
    if (!lane) return;
    const px = this.plotX(), pw = this.plotW();
    const top = this.yOf(lane, 0.04), h = lane.h * 0.92;
    if (top + h < this.plotY() - 2 || top > this.plotY() + this.plotH() + 2) return;
    ctx.save();
    ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
    for (const era of this.data.eras) {
      const x0 = this.xOf(era.start), x1 = this.xOf(era.end);
      if (x1 < px || x0 > px + pw) continue;
      const hov = this.hover && this.hover.kind === 'era' && this.hover.id === era.id;
      ctx.fillStyle = era.color;
      ctx.globalAlpha = hov ? 1 : 0.92;
      ctx.fillRect(x0, top, x1 - x0, h);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = hov ? '#1b1f28' : 'rgba(255,255,255,0.85)';
      ctx.lineWidth = hov ? 1.6 : 1;
      ctx.beginPath(); ctx.moveTo(x1, top); ctx.lineTo(x1, top + h); ctx.stroke();
      const a = Math.max(x0, px), b = Math.min(x1, px + pw);
      ctx.font = `600 ${Math.min(12, Math.max(9, h * 0.62))}px "Segoe UI", system-ui, sans-serif`;
      const room = b - a - 10;
      let label = era.name;
      if (ctx.measureText(label).width > room) {
        label = '';
        for (const word of era.name.split(' ')) {
          const probe = label ? label + ' ' + word : word;
          if (ctx.measureText(probe + '…').width > room) break;
          label = probe;
        }
        if (label && label !== era.name) label += '…';
      }
      if (label) {
        ctx.fillStyle = 'rgba(22,25,33,0.88)';
        ctx.fillText(label, (a + b) / 2, top + h / 2 + 0.5);
      }
      this._eraBoxes.push({ id: era.id, obj: era, x0, x1, y0: top, y1: top + h });
    }
    ctx.restore();
  }

  _drawScrollbar(ctx) {
    const ph = this.plotH(), py = this.plotY();
    const total = this.lanesLayout.height;
    if (total <= ph) return;
    const { w } = this.cssSize();
    const h = Math.max(30, ph * ph / total);
    const y = py + (ph - h) * (this.view.vy / (total - ph));
    ctx.fillStyle = 'rgba(0,0,0,0.08)';
    ctx.fillRect(w - 8, py, 8, ph);
    ctx.fillStyle = 'rgba(40,45,60,0.45)';
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(w - 7, y, 6, h, 3) : ctx.rect(w - 7, y, 6, h);
    ctx.fill();
  }

  // ---------- попадания ----------
  hitTest(mx, my) {
    const px = this.plotX(), py = this.plotY();
    if (mx < px) {
      const lane = this._laneAt(my);
      if (lane) return { kind: 'lane', id: lane.id, obj: lane };
      return null;
    }
    if (my < py) {
      if (my >= this.geom.axisH) {
        const year = this.yearOf(mx);
        const era = this.data.eras.find(e => year >= e.start && year <= e.end);
        if (era) return { kind: 'era', id: era.id, obj: era };
      }
      return null;
    }
    for (const b of this._eventBoxes) {
      if (Math.hypot(mx - b.x, my - b.y) <= b.r) return { kind: 'event', id: b.id, obj: b.obj };
    }
    for (const b of this._eraBoxes) {
      if (mx >= b.x0 && mx <= b.x1 && my >= b.y0 && my <= b.y1) {
        return { kind: 'era', id: b.id, obj: b.obj };
      }
    }
    for (const m of this._migPaths) {
      for (let i = 1; i < m.pts.length; i++) {
        if (this._distToSeg(mx, my, m.pts[i - 1], m.pts[i]) < 7) {
          return { kind: 'migration', id: m.id, obj: m.obj };
        }
      }
    }
    const lane = this._laneAt(my);
    if (!lane) return null;
    const year = this.yearOf(mx);
    const t = (my - this.yOf(lane, 0)) / lane.h;
    const strips = this.strips.get(lane.id) || [];
    for (const s of strips) {
      for (const run of s.runs) {
        if (year < run[0][0] || year > run[run.length - 1][0]) continue;
        for (let i = 1; i < run.length; i++) {
          if (year <= run[i][0]) {
            const a = run[i - 1], b = run[i];
            const f = b[0] === a[0] ? 0 : (year - a[0]) / (b[0] - a[0]);
            const t0 = a[1] + (b[1] - a[1]) * f, t1 = a[2] + (b[2] - a[2]) * f;
            if (t >= t0 && t <= t1) {
              return { kind: 'entity', id: s.entity.id, obj: s.entity, lane, year };
            }
            break;
          }
        }
      }
    }
    return { kind: 'empty', lane, year };
  }

  _laneAt(my) {
    const rel = my - this.plotY() + this.view.vy;
    for (const l of this.lanesLayout.lanes) {
      if (rel >= l.y && rel <= l.y + l.h) return l;
    }
    return null;
  }

  _distToSeg(x, y, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const l2 = dx * dx + dy * dy;
    if (!l2) return Math.hypot(x - a[0], y - a[1]);
    let t = ((x - a[0]) * dx + (y - a[1]) * dy) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
  }

  // ---------- события ввода ----------
  _bindEvents() {
    const c = this.canvas;
    let drag = null;
    let lastMoved = 0;   // сколько пикселей прошли до отпускания кнопки (пан ≠ выбор)

    c.addEventListener('mousedown', ev => {
      const r = c.getBoundingClientRect();
      drag = { x: ev.clientX, y: ev.clientY, ux: this.view.ux, vy: this.view.vy, moved: 0,
               px: ev.clientX - r.left, py: ev.clientY - r.top };
      c.classList.add('dragging');
    });

    window.addEventListener('mousemove', ev => {
      const r = c.getBoundingClientRect();
      const mx = ev.clientX - r.left, my = ev.clientY - r.top;
      if (drag) {
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
        this.view.ux = drag.ux - dx / this.contentW();
        this.view.vy = drag.vy - dy;
        this.clampView();
        this.draw();
        this.onView(this, 'pan');
        return;
      }
      if (mx < 0 || my < 0 || mx > r.width || my > r.height) { this._setHover(null, ev); return; }
      const hit = this.hitTest(mx, my);
      this._setHover(hit, ev);
    });

    window.addEventListener('mouseup', () => {
      if (drag) c.classList.remove('dragging');
      lastMoved = drag ? drag.moved : 0;
      drag = null;
    });

    c.addEventListener('click', ev => {
      if (lastMoved > 5) { lastMoved = 0; return; }   // это был пан полотна, а не щелчок по объекту
      const r = c.getBoundingClientRect();
      const hit = this.hitTest(ev.clientX - r.left, ev.clientY - r.top);
      if (hit && ['entity', 'event', 'migration', 'lane', 'era'].includes(hit.kind)) {
        this.selectedId = hit.kind === 'entity' ? hit.id : this.selectedId;
        this.onSelect(hit);
        this.draw();
      }
    });

    c.addEventListener('dblclick', ev => {
      const r = c.getBoundingClientRect();
      const hit = this.hitTest(ev.clientX - r.left, ev.clientY - r.top);
      if (hit && hit.kind === 'entity') this.zoomToRange(hit.obj.start, hit.obj.end, 0.25, 'zoom');
      else if (hit && hit.kind === 'era') this.zoomToRange(hit.obj.start, hit.obj.end, 0.05, 'zoom');
    });

    // Колесо и тачпад: в полноэкранной таблице обычная прокрутка двигает
    // полотно; на главной, где видны все строки, вертикальная прокрутка
    // остаётся странице, а Ctrl/⌘+колесо по-прежнему меняют масштаб времени.
    c.addEventListener('wheel', ev => {
      const r = c.getBoundingClientRect();
      const mx = ev.clientX - r.left;
      const unit = ev.deltaMode === 1 ? 18 : ev.deltaMode === 2 ? this.plotH() : 1;
      const dx = ev.deltaX * unit, dy = ev.deltaY * unit;
      if (ev.ctrlKey || ev.metaKey || ev.altKey) {
        ev.preventDefault();
        // щипок тачпада браузер присылает как wheel с ctrlKey
        const soft = (ev.ctrlKey || ev.metaKey) && !ev.altKey ? 0.42 : 1;
        const f = Math.pow(1.0038, -dy * soft);
        this.zoomAt(Math.max(this.plotX(), mx), f, 'zoom');
        return;
      }
      if (this.autoHeight && !ev.shiftKey) {
        // Трекпад может передать горизонтальную составляющую одновременно
        // с вертикальной: сдвигаем годы, но не блокируем прокрутку страницы.
        if (dx) {
          this.view.ux += dx / this.contentW();
          this.clampView(); this.draw(); this.onView(this, 'pan');
        }
        return;
      }
      ev.preventDefault();
      if (ev.shiftKey) {            // привычная горизонтальная прокрутка
        this.view.ux += (dx + dy) / this.contentW();
      } else {
        this.view.vy += dy;
        this.view.ux += dx / this.contentW();
      }
      this.clampView(); this.draw(); this.onView(this, 'pan');
    }, { passive: false });

    c.addEventListener('mouseleave', () => this._setHover(null, null));

    // touch: перетаскивание и щипок
    let touch = null;
    c.addEventListener('touchstart', ev => {
      const r = c.getBoundingClientRect();
      if (ev.touches.length === 1) {
        touch = { mode: 'pan', x: ev.touches[0].clientX, y: ev.touches[0].clientY,
                  ux: this.view.ux, vy: this.view.vy };
      } else if (ev.touches.length === 2) {
        const d = Math.hypot(ev.touches[0].clientX - ev.touches[1].clientX,
                             ev.touches[0].clientY - ev.touches[1].clientY);
        touch = { mode: 'zoom', d, k: this.view.k,
                  cx: (ev.touches[0].clientX + ev.touches[1].clientX) / 2 - r.left };
      }
    }, { passive: true });
    c.addEventListener('touchmove', ev => {
      if (!touch) return;
      if (this.autoHeight && touch.mode === 'pan' && ev.touches.length === 1) {
        const dx = ev.touches[0].clientX - touch.x, dy = ev.touches[0].clientY - touch.y;
        // Вертикальный свайп прокручивает страницу; горизонтальный двигает шкалу.
        if (Math.abs(dx) > Math.abs(dy) * 1.2) {
          ev.preventDefault();
          this.view.ux = touch.ux - dx / this.contentW();
          this.clampView(); this.draw(); this.onView(this, 'pan');
        }
        return;
      }
      ev.preventDefault();
      if (touch.mode === 'pan' && ev.touches.length === 1) {
        const dx = ev.touches[0].clientX - touch.x, dy = ev.touches[0].clientY - touch.y;
        this.view.ux = touch.ux - dx / this.contentW();
        this.view.vy = touch.vy - dy;
        this.clampView(); this.draw(); this.onView(this, 'pan');
      } else if (touch.mode === 'zoom' && ev.touches.length === 2) {
        const d = Math.hypot(ev.touches[0].clientX - ev.touches[1].clientX,
                             ev.touches[0].clientY - ev.touches[1].clientY);
        const target = touch.k * (d / touch.d);
        this.zoomAt(touch.cx, target / this.view.k, 'zoom');
      }
    }, { passive: false });
    c.addEventListener('touchend', () => { touch = null; }, { passive: true });

    window.addEventListener('resize', () => {
      if (this.fitRows) this.fitRowsToView(); else this.draw();
    });
  }

  _setHover(hit, ev) {
    const id = hit && hit.id ? hit.kind + ':' + hit.id : null;
    const prev = this.hover ? this.hover.kind + ':' + this.hover.id : null;
    this.hover = hit && hit.id ? hit : null;
    if (id !== prev) this.draw();
    this.onHover(hit, ev);
    this.canvas.style.cursor = (hit && ['entity', 'event', 'migration', 'lane', 'era'].includes(hit.kind))
      ? 'pointer' : 'grab';
  }
}
