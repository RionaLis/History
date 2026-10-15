// Пиктограммы событий. Рисуются векторно на canvas — чтобы одинаково
// выглядеть и на схеме, и в легенде, и на любом масштабе.

const P = {
  pottery(c, s) { // горшок
    c.moveTo(-0.55 * s, -0.5 * s); c.lineTo(0.55 * s, -0.5 * s);
    c.moveTo(-0.45 * s, -0.5 * s);
    c.bezierCurveTo(-0.95 * s, 0.1 * s, -0.5 * s, 0.75 * s, 0, 0.75 * s);
    c.bezierCurveTo(0.5 * s, 0.75 * s, 0.95 * s, 0.1 * s, 0.45 * s, -0.5 * s);
  },
  metal(c, s) { // молот и наковальня
    c.moveTo(-0.8 * s, 0.6 * s); c.lineTo(0.8 * s, 0.6 * s);
    c.moveTo(-0.55 * s, 0.6 * s); c.lineTo(-0.15 * s, -0.1 * s);
    c.moveTo(-0.5 * s, -0.75 * s); c.lineTo(0.55 * s, -0.2 * s);
    c.moveTo(-0.15 * s, -0.75 * s); c.lineTo(-0.5 * s, -0.2 * s);
    c.lineTo(0.2 * s, 0.15 * s); c.lineTo(0.55 * s, -0.4 * s); c.closePath();
  },
  battle(c, s) { // скрещённые мечи
    c.moveTo(-0.75 * s, -0.75 * s); c.lineTo(0.6 * s, 0.6 * s);
    c.moveTo(0.75 * s, -0.75 * s); c.lineTo(-0.6 * s, 0.6 * s);
    c.moveTo(-0.85 * s, 0.45 * s); c.lineTo(-0.45 * s, 0.85 * s);
    c.moveTo(0.85 * s, 0.45 * s); c.lineTo(0.45 * s, 0.85 * s);
  },
  revolt(c, s) { // поднятый флаг / вилы
    c.moveTo(-0.3 * s, 0.85 * s); c.lineTo(-0.3 * s, -0.85 * s);
    c.lineTo(0.75 * s, -0.55 * s); c.lineTo(-0.3 * s, -0.2 * s);
  },
  revolution(c, s) { // круговая стрелка
    c.arc(0, 0, 0.7 * s, 0.5, 5.4);
    c.moveTo(0.33 * s, -0.78 * s); c.lineTo(0.62 * s, -0.45 * s); c.lineTo(0.2 * s, -0.3 * s);
  },
  migration(c, s) { // плавная стрелка
    c.moveTo(-0.85 * s, 0.45 * s);
    c.bezierCurveTo(-0.2 * s, 0.5 * s, 0.1 * s, -0.4 * s, 0.75 * s, -0.5 * s);
    c.moveTo(0.3 * s, -0.8 * s); c.lineTo(0.85 * s, -0.5 * s); c.lineTo(0.35 * s, -0.15 * s);
  },
  invasion(c, s) { // копьё-стрела
    c.moveTo(-0.85 * s, 0.7 * s); c.lineTo(0.7 * s, -0.7 * s);
    c.moveTo(0.1 * s, -0.8 * s); c.lineTo(0.85 * s, -0.85 * s); c.lineTo(0.8 * s, -0.1 * s);
  },
  massive(c, s) { // вспышка
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4;
      c.moveTo(Math.cos(a) * 0.3 * s, Math.sin(a) * 0.3 * s);
      c.lineTo(Math.cos(a) * 0.9 * s, Math.sin(a) * 0.9 * s);
    }
    c.moveTo(0.3 * s, 0); c.arc(0, 0, 0.3 * s, 0, Math.PI * 2);
  },
  idea(c, s) { // раскрытая книга
    c.moveTo(0, -0.45 * s);
    c.bezierCurveTo(-0.35 * s, -0.8 * s, -0.7 * s, -0.65 * s, -0.85 * s, -0.6 * s);
    c.lineTo(-0.85 * s, 0.55 * s);
    c.bezierCurveTo(-0.6 * s, 0.45 * s, -0.3 * s, 0.45 * s, 0, 0.7 * s);
    c.bezierCurveTo(0.3 * s, 0.45 * s, 0.6 * s, 0.45 * s, 0.85 * s, 0.55 * s);
    c.lineTo(0.85 * s, -0.6 * s);
    c.bezierCurveTo(0.7 * s, -0.65 * s, 0.35 * s, -0.8 * s, 0, -0.45 * s);
    c.moveTo(0, -0.45 * s); c.lineTo(0, 0.7 * s);
  },
  disaster(c, s) { // молния в треугольнике
    c.moveTo(0, -0.85 * s); c.lineTo(0.9 * s, 0.75 * s); c.lineTo(-0.9 * s, 0.75 * s); c.closePath();
    c.moveTo(0.12 * s, -0.4 * s); c.lineTo(-0.2 * s, 0.15 * s);
    c.lineTo(0.08 * s, 0.15 * s); c.lineTo(-0.12 * s, 0.55 * s);
  },
};

export const ICON_IDS = Object.keys(P);

export const ICON_LABELS = {
  pottery: 'Керамика, быт, хозяйство',
  metal: 'Технология, металлургия',
  battle: 'Ключевая битва',
  revolt: 'Крупное восстание',
  revolution: 'Революция, внутренний перелом',
  migration: 'Переселение народов',
  invasion: 'Вторжение, завоевание',
  massive: 'Событие колоссального масштаба',
  idea: 'Религия, идея, наука',
  disaster: 'Катастрофа, эпидемия, климат',
};

/**
 * Нарисовать значок события.
 * @param {CanvasRenderingContext2D} ctx
 * @param {string} type
 * @param {number} x @param {number} y центр
 * @param {number} r радиус значка в пикселях
 */
export function drawIcon(ctx, type, x, y, r, opts = {}) {
  const fn = P[type] || P.massive;
  const stroke = opts.stroke || '#1d2330';
  const halo = opts.halo ?? true;
  ctx.save();
  ctx.translate(x, y);
  const path = new Path2D();
  fn(path, r);
  if (halo) {
    ctx.lineWidth = Math.max(2.4, r * 0.75);
    ctx.strokeStyle = opts.haloColor || 'rgba(255,255,255,0.92)';
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.stroke(path);
  }
  ctx.lineWidth = Math.max(1, r * 0.3);
  ctx.strokeStyle = stroke;
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  ctx.stroke(path);
  ctx.restore();
}
