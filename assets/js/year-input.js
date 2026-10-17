// Разбирает числовой год и выбранную пользователем эру.
// Внутреннее представление: положительные годы — н.э., отрицательные — до н.э.; года 0 нет.
export function parseHistoricalYear(value, era = 'ce') {
  const text = String(value == null ? '' : value).trim().replace(/[\s,_]/g, '');
  if (!/^\d+$/.test(text)) return null;

  const magnitude = Number(text);
  if (!Number.isSafeInteger(magnitude) || magnitude < 1) return null;
  if (era === 'bce') return -magnitude;
  if (era === 'ce') return magnitude;
  return null;
}
