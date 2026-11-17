'use strict';
// ───────────────────────────────────────────────────────────────────────────
//  РАЗРЕШЕНИЯ И ФАЗЫ — вторая половина модели доступа.
//
//  Уровень человека не хранится «сам по себе». Он вычисляется из записей
//  о разрешениях, у каждой из которых есть ИСТОЧНИК и СРОК:
//
//    purchase   — оплаченная подписка (в прототипе — заглушка оплаты)
//    manual     — ручное переключение в демо-режиме (сегодня)
//    promo      — промокод на объект или уровень
//    phase      — временное разрешение на время запуска («всё бесплатно»)
//    compensation — выдача за сбой
//
//  Подключение настоящей оплаты = новый источник записей,
//  а не правка страниц. Сегодня purchase создаётся заглушкой /subscribe,
//  завтра — вебхуком платёжного сервиса.
// ───────────────────────────────────────────────────────────────────────────

// Флаги: включаются данными, а не правкой кода.
const FLAGS = {
  notesMinLevel: 3,   // заметки пока только на уровне 3
  notesEnabled: true, // общий выключатель заметок (фаза запуска)
  tiersOnSale: [1, 2, 3],
  phase: 'local',     // local | free-launch | paid
};

function isActive(ent, now) {
  if (ent.from && new Date(ent.from) > now) return false;
  if (ent.to && new Date(ent.to) < now) return false;
  return true;
}

// Главная функция: из записей человека получить то, что ему реально доступно.
function resolve(record) {
  const now = new Date();
  const active = (record.entitlements || []).filter(function (e) { return isActive(e, now); });

  const manual = active.filter(function (e) { return e.source === 'manual'; }).pop();
  const paidLevels = active
    .filter(function (e) { return e.kind === 'level' && e.source !== 'manual'; })
    .map(function (e) { return e.level; });

  const paidLevel = paidLevels.length ? Math.max.apply(null, paidLevels) : 0;
  // Ручное переключение — демо-инструмент, оно перекрывает всё остальное.
  const level = manual ? manual.level : paidLevel;

  const grants = Array.from(new Set(active
    .filter(function (e) { return e.kind === 'item'; })
    .map(function (e) { return e.item; })));

  const notesOn = FLAGS.notesEnabled && level >= FLAGS.notesMinLevel;
  const notesLimit = notesOn ? (level >= 3 ? 1000 : 20) : 0;

  return { level: level, paidLevel: paidLevel, grants: grants, notesLimit: notesLimit, notesEnabled: notesOn, active: active };
}

// Создание разрешений — единственные места, где они появляются.
function grantLevel(record, level, source, opts) {
  opts = opts || {};
  record.entitlements.push({
    kind: 'level',
    level: level,
    source: source,
    from: opts.from || new Date().toISOString(),
    to: opts.to || null,
    note: opts.note || '',
  });
  return record;
}

function grantItem(record, item, source, opts) {
  opts = opts || {};
  record.entitlements.push({
    kind: 'item',
    item: item,
    source: source,
    from: opts.from || new Date().toISOString(),
    to: opts.to || null,
    note: opts.note || '',
  });
  return record;
}

// Демо-переключатель уровня: заменяет предыдущее ручное разрешение.
function setManualLevel(record, level) {
  record.entitlements = record.entitlements.filter(function (e) { return e.source !== 'manual'; });
  record.entitlements.push({
    kind: 'level', level: level, source: 'manual', from: new Date().toISOString(), to: null,
    note: 'переключение в демо-режиме',
  });
  return record;
}

function clearManual(record) {
  record.entitlements = record.entitlements.filter(function (e) { return e.source !== 'manual'; });
  return record;
}

// Запись о покупке: снимок того, что человек купил, на момент покупки.
function addPurchase(record, p) {
  const id = p.id;
  const item = {
    id: id,
    tier: p.tier,           // номер уровня тарифа
    price: p.price,
    currency: p.currency || 'EUR',
    period: p.period || 'month',
    code: p.code || null,
    discount: p.discount || 0,
    paidAt: new Date().toISOString(),
    from: p.from,
    to: p.to,
    note: p.note || '',
  };
  record.purchases.push(item);
  return item;
}

module.exports = { FLAGS, resolve, grantLevel, grantItem, setManualLevel, clearManual, addPurchase, isActive };
