// Временная шкала: год <-> безразмерная координата 0..1 и обратно.
// Поддерживает два режима: "плакатный" (нелинейный, как в образце —
// ближе к современности масштаб крупнее) и равномерный.

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
  const raw = yearsPerPixel * targetPx;
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
  for (const s of steps) if (s >= raw) return s;
  return 10000;
}

export function formatYear(y, short = false) {
  const r = Math.round(y);
  if (r < 0) return short ? `${-r} до н.э.` : `${-r} г. до н.э.`;
  if (r === 0) return '1 г.';
  return short ? `${r}` : `${r} г.`;
}

export function formatSpan(a, b) {
  return `${formatYear(a, true)} — ${formatYear(b, true)}`;
}
