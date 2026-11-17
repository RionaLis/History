'use strict';
// Хранилище прототипа: один JSON-файл.
// В настоящей версии здесь будет база данных; снаружи это не видно,
// потому что все обращения идут через этот модуль.
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'data');
const FILE = path.join(DIR, 'state.json');

let state = load();

function load() {
  try {
    return JSON.parse(fs.readFileSync(FILE, 'utf8'));
  } catch (e) {
    return { seq: 1, users: {}, tickets: [] };
  }
}

function save() {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(state, null, 2));
}

function nextId(prefix) {
  const n = state.seq++;
  save();
  return prefix + '-' + String(1000 + n);
}

function getUser(uid) {
  if (!state.users[uid]) {
    state.users[uid] = {
      uid: uid,
      name: 'Гость',
      email: '',
      createdAt: new Date().toISOString(),
      entitlements: [], // разрешения: уровень, объект, источник, срок
      purchases: [],    // записи о покупках: что, когда, за сколько
      discounts: [],    // пожизненные скидки человека
      notes: [],
    };
    save();
  }
  return state.users[uid];
}

function reset(uid) {
  const u = getUser(uid);
  u.name = 'Гость';
  u.email = '';
  u.entitlements = [];
  u.purchases = [];
  u.discounts = [];
  u.notes = [];
  save();
  return u;
}

function tickets() { return state.tickets; }
function addTicket(t) { state.tickets.push(t); save(); return t; }

module.exports = { getUser, reset, nextId, tickets, addTicket, save, FILE };
