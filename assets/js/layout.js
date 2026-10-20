// Расчёт геометрии таблицы. Модуль чистый: не знает про DOM и canvas,
// поэтому его можно использовать и в node (например, для snapshot-рендера в SVG).

/**
 * Вертикальная раскладка: полосы регионов и дорожки суб-регионов.
 * @param {Array} regions
 * @param {Object} opts {rowUnit, regionGap, headerH}
 */
export function computeLanes(regions, opts = {}) {
  const rowUnit = opts.rowUnit ?? 22;      // высота дорожки с weight = 1
  const regionGap = opts.regionGap ?? 6;   // зазор между макро-регионами
  const lanes = [];
  const bands = [];
  let y = 0;
  for (const r of regions) {
    const top = y;
    for (const l of r.lanes) {
      const h = Math.max(8, rowUnit * (l.weight || 1));
      lanes.push({
        id: l.id, name: l.name, regionId: r.id, regionName: r.name,
        color: r.color, hue: r.hue, y, h, index: lanes.length,
      });
      y += h;
    }
    bands.push({ id: r.id, name: r.name, short: r.short, color: r.color, hue: r.hue,
                 y: top, h: y - top, path: r.path });
    y += regionGap;
  }
  const height = Math.max(0, y - regionGap);
  const byId = new Map(lanes.map(l => [l.id, l]));
  return { lanes, bands, height, byId, regionGap };
}

function shareAt(points, year) {
  if (year < points[0][0] || year > points[points.length - 1][0]) return 0;
  for (let i = 1; i < points.length; i++) {
    if (year <= points[i][0]) {
      const [y0, s0] = points[i - 1], [y1, s1] = points[i];
      if (y1 === y0) return Math.max(s0, s1);
      return s0 + (s1 - s0) * (year - y0) / (y1 - y0);
    }
  }
  return points[points.length - 1][1];
}

/**
 * Укладка лент внутри одной дорожки: доли складываются стопкой сверху вниз,
 * при переполнении (сумма > 1) нормируются. Толщина ленты = доля площади
 * суб-региона, занятая государством, и меняется во времени.
 *
 * @returns Map<entityId, {entity, runs: Array<Array<[year, top, bottom]>>}>
 * координаты top/bottom — доли высоты дорожки (0 сверху, 1 снизу).
 */
export function stackLane(items, stateGamma = 0.65) {
  // items: [{entity, points}]
  if (!items.length) return new Map();
  const ordered = items.slice().sort((a, b) => {
    const d = a.points[0][0] - b.points[0][0];
    return d !== 0 ? d : (a.entity.id < b.entity.id ? -1 : 1);
  });
  const yearsSet = new Set();
  for (const it of ordered) for (const p of it.points) yearsSet.add(p[0]);
  const years = [...yearsSet].sort((a, b) => a - b);

  const out = new Map();
  for (const it of ordered) out.set(it.entity.id, { entity: it.entity, runs: [] });
  const open = new Map(); // id -> текущая серия вершин

  for (let i = 0; i < years.length - 1; i++) {
    const ya = years[i], yb = years[i + 1];
    const active = ordered.filter(it =>
      it.points[0][0] <= ya && it.points[it.points.length - 1][0] >= yb);

    if (!active.length) { // разрыв
      for (const [id, run] of open) { out.get(id).runs.push(run); }
      open.clear();
      continue;
    }
    // Нелинейная визуальная шкала: выпуклость уменьшена для государств, чтобы
    // малые политии оставались различимыми и могли получить подпись.
    // Исходная areaSeries остаётся нетронутой; трансформация только экранная.
    const visualShare = (it, year) => {
      const value = shareAt(it.points, year);
      return ['state', 'empire'].includes(it.entity.type)
        ? Math.max(0.012, value) ** stateGamma : value;
    };
    const sa = active.map(it => visualShare(it, ya));
    const sb = active.map(it => visualShare(it, yb));
    const suma = sa.reduce((x, v) => x + v, 0);
    const sumb = sb.reduce((x, v) => x + v, 0);
    const ka = suma > 1 ? 1 / suma : 1;
    const kb = sumb > 1 ? 1 / sumb : 1;

    let offa = 0, offb = 0;
    const seg = new Map();
    for (let j = 0; j < active.length; j++) {
      const ha = sa[j] * ka, hb = sb[j] * kb;
      seg.set(active[j].entity.id, [offa, offa + ha, offb, offb + hb]);
      offa += ha; offb += hb;
    }
    // закрыть серии тех, кто выпал
    for (const [id, run] of [...open]) {
      if (!seg.has(id)) { out.get(id).runs.push(run); open.delete(id); }
    }
    for (const [id, s] of seg) {
      let run = open.get(id);
      if (!run) { run = [[ya, s[0], s[1]]]; open.set(id, run); }
      else {
        const last = run[run.length - 1];
        // если стопка «прыгнула» на стыке — добавляем вертикальную ступень
        if (Math.abs(last[1] - s[0]) > 1e-6 || Math.abs(last[2] - s[1]) > 1e-6) {
          run.push([ya, s[0], s[1]]);
        }
      }
      run.push([yb, s[2], s[3]]);
    }
  }
  for (const [id, run] of open) out.get(id).runs.push(run);
  for (const v of out.values()) v.runs = v.runs.filter(r => r.length > 1);
  return out;
}

/**
 * Полная раскладка лент по всем дорожкам.
 * @returns Map<laneId, Array<{entity, runs}>>
 */
export function layoutEntities(entities, laneIds, stateGamma = 0.65) {
  const perLane = new Map();
  for (const id of laneIds) perLane.set(id, []);
  for (const e of entities) {
    for (const sp of e.spans) {
      if (!perLane.has(sp.lane)) continue;
      perLane.get(sp.lane).push({ entity: e, points: sp.points });
    }
  }
  const res = new Map();
  for (const [laneId, items] of perLane) {
    const stacked = stackLane(items, stateGamma);
    res.set(laneId, [...stacked.values()].filter(v => v.runs.length));
  }
  return res;
}

/** Самый «широкий» в годах отрезок серии — туда ставим подпись. */
export function widestRun(runs) {
  let best = null, bestW = -1;
  for (const run of runs) {
    const w = run[run.length - 1][0] - run[0][0];
    if (w > bestW) { bestW = w; best = run; }
  }
  return best;
}
