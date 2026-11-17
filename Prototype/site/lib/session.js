'use strict';
// Сессия прототипа: кто пришёл и что ему доступно.
// Здесь единственная точка, где решается «какой уровень у человека».
// Замена на настоящие аккаунты и оплату затрагивает этот файл, а не страницы.

const crypto = require('crypto');
const store = require('./store');
const ent = require('./entitlements');

function cookie(name, value, maxAge) {
  return name + '=' + encodeURIComponent(value) + '; Path=/; Max-Age=' + (maxAge || 2592000) + '; SameSite=Lax';
}

function parseCookies(req) {
  const out = {};
  String(req.headers.cookie || '').split(';').forEach(function (p) {
    const i = p.indexOf('=');
    if (i > 0) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}

function viewOf(record) {
  const r = ent.resolve(record);
  return {
    uid: record.uid,
    name: record.name || 'Гость',
    email: record.email || '',
    level: r.level,
    paidLevel: r.paidLevel,
    grants: r.grants,
    notesLimit: r.notesLimit,
    notesEnabled: r.notesEnabled,
    entitlements: r.active,
    discounts: record.discounts || [],
    notesCount: (record.notes || []).length,
    record: record,
  };
}

function open(req, query) {
  const c = parseCookies(req);
  // ВАЖНО: идентификатор берётся сначала из адреса (?u=...), потом из cookie.
  // В предпросмотре cookie могут блокироваться, и тогда адрес — единственный
  // способ сохранить состояние между запросами.
  const fromQuery = query && query.u ? String(query.u) : '';
  let uid = /^[a-f0-9]{16}$/.test(fromQuery) ? fromQuery : c.sid;
  let isNew = false;
  if (!/^[a-f0-9]{16}$/.test(uid || '')) {
    uid = crypto.randomBytes(8).toString('hex');
    isNew = true;
  }
  const record = store.getUser(uid);
  return { uid: uid, isNew: isNew, record: record, view: viewOf(record) };
}

// Заголовки ответа: выдать идентификатор, если он новый.
function headers(sess) {
  return sess.isNew ? { 'Set-Cookie': cookie('sid', sess.uid) } : {};
}

function refresh(sess) {
  sess.view = viewOf(sess.record);
  return sess.view;
}

function setManualLevel(sess, level) {
  ent.setManualLevel(sess.record, Math.max(0, Math.min(3, level)));
  store.save();
  return refresh(sess);
}

function register(sess, name, email) {
  sess.record.name = (name || 'Читатель').slice(0, 60);
  sess.record.email = (email || '').slice(0, 120);
  store.save();
  return refresh(sess);
}

// Заглушка оплаты. В настоящей версии эта же запись создаётся
// обработчиком вебхука платёжного сервиса — форма ниже просто зовёт его.
function subscribeStub(sess, tier, price, period) {
  const days = period === 'year' ? 365 : 30;
  const from = new Date();
  const to = new Date(from.getTime() + days * 24 * 3600 * 1000);
  const purchase = ent.addPurchase(sess.record, {
    id: store.nextId('PAY'),
    tier: tier,
    price: price,
    period: period || 'month',
    from: from.toISOString(),
    to: to.toISOString(),
    note: 'заглушка оплаты: запись создана формой, а не вебхуком',
  });
  ent.grantLevel(sess.record, tier, 'purchase', { to: to.toISOString(), note: 'покупка ' + purchase.id });
  sess.record.entitlements = sess.record.entitlements.filter(function (e) { return e.source !== 'manual'; });
  store.save();
  return { purchase: purchase, view: refresh(sess) };
}

function applyPromo(sess, code, table) {
  const promo = table[code];
  if (!promo) return false;
  if (promo.kind === 'level') ent.grantLevel(sess.record, promo.level, 'promo', { to: promo.to || null, note: 'промокод ' + code });
  else ent.grantItem(sess.record, promo.item, 'promo', { to: promo.to || null, note: 'промокод ' + code });
  store.save();
  refresh(sess);
  return true;
}

module.exports = { open, headers, refresh, setManualLevel, register, subscribeStub, applyPromo, cookie, parseCookies };
