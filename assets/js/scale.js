// Временная шкала: год <-> безразмерная координата 0..1.
// В режиме poster шкала нелинейна; линейный режим распределяет календарные
// годы равномерно. Древние даты заданы в календарных годах, пересчитанных из BP
// (year = 1950 - BP), поэтому современный участок шкалы остаётся совместимым.

export class TimeScale {
  constructor(anchors, mode = 'poster') {
    this.anchors = anchors.map(a => [a[0], a[1]]).sort((a, b) => a[0] - b[0]);
    this.yearMin = this.anchors[0][0];
    this.yearMax = this.anchors[this.anchors.length - 1][0];
    this.mode = mode;
  }

  setMode(mode) { this.mode = mode; }

  /** год -> 0..1 */
  unit(year) {
    if (this.mode === 'linear') {
      return (year - this.yearMin) / (this.yearMax - this.yearMin);
    }
    const a = this.anchors;
    if (year <= a[0][0]) return a[0][1];
    if (year >= a[a.length - 1][0]) return a[a.length - 1][1];
    let lo = 0, hi = a.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (a[mid][0] <= year) lo = mid; else hi = mid;
    }
    const [y0, u0] = a[lo], [y1, u1] = a[hi];
    return u0 + (u1 - u0) * (year - y0) / (y1 - y0);
  }

  /** 0..1 -> год */
  year(u) {
    if (this.mode === 'linear') {
      return this.yearMin + u * (this.yearMax - this.yearMin);
    }
    const a = this.anchors;
    if (u <= a[0][1]) return a[0][0];
    if (u >= a[a.length - 1][1]) return a[a.length - 1][0];
    let lo = 0, hi = a.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (a[mid][1] <= u) lo = mid; else hi = mid;
    }
    const [y0, u0] = a[lo], [y1, u1] = a[hi];
    return y0 + (y1 - y0) * (u - u0) / (u1 - u0);
  }
}

/** Красивый шаг сетки под текущую плотность (лет на пиксель). */
export function tickStep(yearsPerPixel, targetPx = 110) {
  const raw = Math.max(0, yearsPerPixel * targetPx);
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000,
    5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000,
    2000000, 5000000, 10000000];
  for (const s of steps) if (s >= raw) return s;
  return 10000000;
}

/**
 * Тики для линейной или плакатной шкалы. В широком обзоре плакатная шкала
 * получает отдельные шаги для глубокого времени и для прежнего диапазона
 * 12000 до н.э. — 2000 н.э., чтобы его сетка не изменилась после расширения.
 */
export function ticksForRange(scale, yearStart, yearEnd, pixelWidth, targetPx = 90) {
  const lo = Math.max(scale.yearMin, Math.min(yearStart, yearEnd));
  const hi = Math.min(scale.yearMax, Math.max(yearStart, yearEnd));
  if (!(hi > lo) || !(pixelWidth > 0)) return [];

  const out = new Map();
  const visibleUnitSpan = Math.max(1e-12, scale.unit(hi) - scale.unit(lo));
  const addRange = (a, b, px, target) => {
    if (!(b > a) || !(px > 0.05)) return;
    const step = tickStep((b - a) / px, target);
    const first = Math.ceil(a / step - 1e-10) * step;
    for (let y = first, guard = 0; y <= b + step * 1e-10 && guard < 5000; y += step, guard++) {
      const year = Math.round(y);
      out.set(year, step);
    }
  };

  // For the familiar time window, use the same single-step grid as before.
  if (scale.mode === 'linear' || hi - lo <= 100000) {
    addRange(lo, hi, pixelWidth, targetPx);
  } else {
    // Deep-time segments: choose a readable step using their actual screen width.
    const deepEnd = Math.min(hi, -12000);
    if (lo < deepEnd) {
      for (let i = 0; i < scale.anchors.length - 1; i++) {
        const a = Math.max(lo, scale.anchors[i][0]);
        const b = Math.min(deepEnd, scale.anchors[i + 1][0]);
        if (!(b > a)) continue;
        const px = (scale.unit(b) - scale.unit(a)) / visibleUnitSpan * pixelWidth;
        addRange(a, b, px, targetPx);
      }
    }

    // Keep dates from the original chart together: they share one tick interval.
    const recentA = Math.max(lo, -12000);
    const recentB = Math.min(hi, 2000);
    if (recentB > recentA) {
      const px = (scale.unit(recentB) - scale.unit(recentA)) / visibleUnitSpan * pixelWidth;
      addRange(recentA, recentB, px, Math.min(targetPx, 50));
    }
  }

  return [...out.entries()]
    .map(([year, step]) => ({
      year, step,
      major: Math.abs(Math.round(year / step)) % 5 === 0,
    }))
    .sort((a, b) => a.year - b.year);
}

function localizedNumber(value, maximumFractionDigits = 1) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits }).format(value);
}

function formatAge(years, short = false) {
  if (years >= 1_000_000) {
    const value = localizedNumber(years / 1_000_000, 1);
    return short ? `${value} млн л.н.` : `${value} млн лет назад`;
  }
  const value = localizedNumber(years / 1000, years >= 100_000 ? 0 : 1);
  return short ? `${value} тыс. л.н.` : `${value} тыс. лет назад`;
}

// Старые археологические даты внутри новой части отображаются как BP;
// -12000 г. до н.э. и более поздний участок сохраняют прежнюю подпись.
const BP_CALENDAR_CUTOFF = -12050;

export function formatYear(y, short = false) {
  const r = Math.round(y);
  if (r <= BP_CALENDAR_CUTOFF) return formatAge(1950 - r, short);
  if (r < 0) return short ? `${-r} до н.э.` : `${-r} г. до н.э.`;
  if (r === 0) return '1 г.';
  return short ? `${r}` : `${r} г.`;
}

export function formatAxisYear(y, step = 1) {
  const r = Math.round(y);
  if (r <= BP_CALENDAR_CUTOFF) {
    const age = 1950 - r;
    // Grid ticks may be aligned to calendar years while deep-time labels use BP.
    // Snap the displayed age to the tick interval to avoid labels like "502 ka".
    const shown = step >= 1000 ? Math.round(age / step) * step : age;
    return formatAge(shown, true);
  }
  if (r === 0) return 'н.э.';
  if (r < 0) return `−${-r}`;
  return `${r}`;
}

export function formatSpan(a, b) {
  return `${formatYear(a, true)} — ${formatYear(b, true)}`;
}
