'use strict';
// Оболочка страниц и мелкие компоненты интерфейса.
const { LEVELS } = require('./access');

function esc(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const NAV = [
  { href: '/', label: 'Главная' },
  { href: '/articles', label: 'Статьи' },
  { href: '/videos', label: 'Видео' },
  { href: '/search', label: 'Поиск' },
  { href: '/qa', label: 'Вопросы' },
  { href: '/levels', label: 'Уровни' },
  { href: '/notes', label: 'Заметки' },
  { href: '/account', label: 'Кабинет' },
];

function badge(required) {
  if (required === 0 || required === undefined) {
    return '<span class="badge badge-free">Бесплатно</span>';
  }
  return '<span class="badge badge-paid">Уровень ' + required + '+</span>';
}

// Замочек
const LOCK = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3" fill="none" stroke="currentColor" stroke-width="1.8"/><rect x="4.5" y="10" width="15" height="10.5" rx="2" fill="currentColor"/></svg>';
const PLAY = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" fill="currentColor"/></svg>';

function poster(v) {
  const seed = Array.from(v.id).reduce(function (a, c) { return a + c.charCodeAt(0); }, 0);
  const h1 = 24 + (seed % 18);
  const h2 = 30 + (seed % 14);
  return '' +
    '<svg class="poster" viewBox="0 0 320 180" role="img" aria-label="' + esc(v.title) + '">' +
      '<defs><linearGradient id="g' + v.id + '" x1="0" y1="0" x2="1" y2="1">' +
        '<stop offset="0%" stop-color="hsl(' + h1 + ',28%,22%)"/>' +
        '<stop offset="100%" stop-color="hsl(' + h2 + ',32%,10%)"/>' +
      '</linearGradient></defs>' +
      '<rect width="320" height="180" fill="url(#g' + v.id + ')"/>' +
      '<g stroke="rgba(255,255,255,.055)" stroke-width="1">' +
        '<path d="M-20 150 L150 -20 M20 200 L200 -10 M60 220 L250 0 M110 240 L300 -20"/>' +
      '</g>' +
      '<circle cx="160" cy="86" r="26" fill="rgba(0,0,0,.35)" stroke="rgba(232,193,124,.55)" stroke-width="1.5"/>' +
      '<g transform="translate(151 77) scale(0.8)" color="#e8c17c">' + PLAY + '</g>' +
      '<text x="14" y="24" fill="rgba(232,193,124,.85)" font-size="10" letter-spacing="1.4" font-family="system-ui,sans-serif">' + esc(v.topic.toUpperCase()) + '</text>' +
      '<text x="306" y="166" fill="rgba(255,255,255,.7)" font-size="11" text-anchor="end" font-family="system-ui,sans-serif">' + esc(v.duration) + '</text>' +
    '</svg>';
}

// Заглушка на месте закрытого содержимого.
// ВАЖНО: закрытый текст сюда не попадает — его нет в HTML вообще.
function lockPanel(opts) {
  const req = opts.required;
  return '' +
    '<div class="lock">' +
      '<div class="lock-ico">' + LOCK + '</div>' +
      '<div class="lock-body">' +
        '<div class="lock-title">' + esc(opts.title || 'Закрыто') + '</div>' +
        '<p class="lock-text">' + esc(opts.text || '') + '</p>' +
        (opts.list ? '<ul class="lock-list">' + opts.list.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
        '<div class="lock-actions">' +
          '<span class="lock-req">Нужен уровень ' + req + '</span>' +
          '<a class="btn btn-small" href="/register">Оформить доступ</a>' +
          '<a class="btn btn-ghost btn-small" href="/level?to=' + req + '&back=' + encodeURIComponent(opts.back || '/') + '">Посмотреть как уровень ' + req + '</a>' +
        '</div>' +
      '</div>' +
    '</div>';
}

function levelBar(user, back) {
  return '' +
    '<div class="levelbar"><div class="wrap">' +
      '<span class="levelbar-label">Демо-режим: вы смотрите сайт как <strong>' +
        esc(LEVELS[user.level].name) + ' (уровень ' + user.level + ')</strong></span>' +
      '<span class="levelbar-btns">' +
        LEVELS.map(function (l) {
          const on = l.n === user.level ? ' is-on' : '';
          return '<a class="lvl-btn' + on + '" href="/level?to=' + l.n + '&back=' + encodeURIComponent(back) + '" title="' + esc(l.name) + '">' + l.n + '</a>';
        }).join('') +
      '</span>' +
    '</div></div>';
}

function page(opts) {
  const user = opts.user;
  const active = opts.active || '';
  const back = opts.back || '/';
  return '<!doctype html><html lang="ru"><head>' +
    '<meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>' + esc(opts.title) + ' — Куликово поле</title>' +
    '<link rel="stylesheet" href="/public/style.css">' +
    '</head><body>' +
    levelBar(user, back) +
    '<header class="site-header"><div class="wrap header-inner">' +
      '<a class="logo" href="/"><span class="logo-mark">К</span><span class="logo-text">Куликово поле<small>база знаний · прототип</small></span></a>' +
      '<nav class="nav">' + NAV.map(function (n) {
        return '<a href="' + n.href + '" class="' + (active === n.href ? 'is-active' : '') + '">' + n.label + '</a>';
      }).join('') + '</nav>' +
      '<a class="who" href="/account">' + esc(user.name) + ' · ур. ' + user.level + '</a>' +
    '</div></header>' +
    '<main>' + opts.body + '</main>' +
    '<footer class="site-footer"><div class="wrap">' +
      '<div class="footer-cols">' +
        '<div><strong>Куликово поле</strong><p class="muted">Прототип базы знаний с уровнями доступа. Контент учебный, оплата не подключена.</p></div>' +
        '<div><strong>Дальше</strong><p class="muted"><a href="/prototype">Как это устроено и где в коде</a><br><a href="/account">Личный кабинет</a><br><a href="/qa">Вопросы и сбои</a></p></div>' +
        '<div><strong>Доступ</strong><p class="muted"><a href="/levels">Сравнение уровней</a><br><a href="/subscribe">Тарифы и оплата (заглушка)</a><br><a href="/notes">Мои заметки</a></p></div>' +
      '</div>' +
      '<div class="footer-note">Видео в прототипе — чужие публичные ролики с YouTube, используются как заглушки.</div>' +
    '</div></footer>' +
    '<script src="/public/app.js"></script>' +
    '</body></html>';
}

module.exports = { esc, page, badge, poster, lockPanel, LOCK, PLAY, NAV, LEVELS };
