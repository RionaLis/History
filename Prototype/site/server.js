'use strict';
// Маршруты прототипа. Никакой логики доступа здесь нет: страницы спрашивают
// can(), а сессия и разрешения живут в lib/session.js и lib/entitlements.js.

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const sessionLib = require('./lib/session');
const store = require('./lib/store');
const notesLib = require('./lib/notes');
const P = require('./lib/pages');

const PORT = Number(process.env.PORT || 3000);

// Промокоды: демо-таблица. В настоящей версии — записи в базе с лимитами и сроками.
const PROMO = {
  KULIKOVO7: { kind: 'item', item: 'istochniki', label: 'статья «Источники и историография»' },
  NOTES30: { kind: 'level', level: 3, to: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(), label: 'уровень 3 на 30 дней' },
};

const MIME = {
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
};

function readBody(req) {
  return new Promise(function (resolve) {
    let data = '';
    req.on('data', function (chunk) { data += chunk; if (data.length > 1e6) req.destroy(); });
    req.on('end', function () { resolve(new URLSearchParams(data)); });
  });
}

function send(res, code, html, headers) {
  res.writeHead(code, Object.assign({ 'Content-Type': 'text/html; charset=utf-8' }, headers || {}));
  res.end(html);
}

function redirect(res, location, headers) {
  res.writeHead(303, Object.assign({ Location: location }, headers || {}));
  res.end();
}

// Идентификатор сессии в адресе: /videos?sort=title → /videos?sort=title&u=…
// Нужно потому, что в песочнице предпросмотра cookie могут не сохраняться.
function appendU(path, uid) {
  if (!uid) return path;
  if (/[?&]u=[a-f0-9]{16}/.test(path)) return path;
  const hashAt = path.indexOf('#');
  const hash = hashAt >= 0 ? path.slice(hashAt) : '';
  const clean = hashAt >= 0 ? path.slice(0, hashAt) : path;
  return clean + (clean.indexOf('?') >= 0 ? '&' : '?') + 'u=' + uid + hash;
}

// Проставляем u во все внутренние ссылки и формы собранной страницы.
function withSession(html, uid) {
  if (!uid) return html;
  html = html.replace(/(href|action)="(\/[^"]*)"/g, function (m, attr, path) {
    return attr + '="' + appendU(path, uid) + '"';
  });
  // GET-форма затирает query в action — добавляем скрытое поле
  html = html.replace(/<form([^>]*method="get"[^>]*)>/gi, function (m, attrs) {
    return '<form' + attrs + '><input type="hidden" name="u" value="' + uid + '">';
  });
  // Идентификатор для скриптов: формы, которые собираются в браузере.
  html = html.replace('</head>', '<meta name="u" content="' + uid + '"></head>');
  return html;
}

function safeBack(p) {
  return (typeof p === 'string' && p.startsWith('/') && !p.startsWith('//')) ? p : '/';
}

function serveStatic(res, filePath) {
  fs.readFile(filePath, function (err, data) {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

const server = http.createServer(async function (req, res) {
  const parsed = url.parse(req.url, true);
  const p = parsed.pathname;
  const query = parsed.query || {};
  // Статика обслуживается до сессии: иначе каждый файл создаёт нового «гостя».
  if (p.startsWith('/public/')) {
    const root = path.join(__dirname, 'public');
    const rel = path.normalize(decodeURIComponent(p.slice('/public/'.length)));
    const file = path.join(root, rel);
    // защита от выхода за пределы папки public
    if (!file.startsWith(root + path.sep)) { res.writeHead(403); return res.end('forbidden'); }
    return serveStatic(res, file);
  }
  if (p === '/favicon.ico') { res.writeHead(204); return res.end(); }

  const sess = sessionLib.open(req, query);
  const user = sess.view;
  const userHeaders = sessionLib.headers(sess);

  // Любой переход внутрь сайта тащит идентификатор в адресе.
  const go = function (location) { return redirect(res, appendU(location, sess.uid), userHeaders); };

  // ── демо-переключение уровня: работает и ссылкой (GET), и формой (POST) ──
  if (p === '/level') {
    const params = req.method === 'POST' ? await readBody(req) : new URLSearchParams(query);
    const to = Math.max(0, Math.min(3, parseInt(params.get('to'), 10) || 0));
    sessionLib.setManualLevel(sess, to);
    return go(safeBack(params.get('back')));
  }

  // ── убрать демо-переопределение ──────────────────────────────────────────
  if (p === '/level/clear') {
    require('./lib/entitlements').clearManual(sess.record);
    store.save();
    return go('/account');
  }

  if (p === '/reset') {
    store.reset(sess.uid);
    return go('/');
  }

  // ── регистрация ──────────────────────────────────────────────────────────
  if (p === '/register' && req.method === 'POST') {
    const body = await readBody(req);
    sessionLib.register(sess, body.get('name'), body.get('email'));
    return go('/account?welcome=1');
  }

  // ── заглушка оплаты ──────────────────────────────────────────────────────
  if (p === '/subscribe' && req.method === 'POST') {
    const body = await readBody(req);
    const tier = Math.max(1, Math.min(3, parseInt(body.get('tier'), 10) || 1));
    const period = body.get('period') === 'year' ? 'year' : 'month';
    const t = P.TARIFFS.find(function (x) { return x.tier === tier; });
    sessionLib.subscribeStub(sess, tier, period === 'year' ? t.year : t.month, period);
    return go('/account?paid=1');
  }

  // ── промокоды ────────────────────────────────────────────────────────────
  if (p === '/promo' && req.method === 'POST') {
    const body = await readBody(req);
    const code = (body.get('code') || '').trim().toUpperCase();
    const ok = sessionLib.applyPromo(sess, code, PROMO);
    return go('/account?promo=' + (ok ? 'ok' : 'bad'));
  }

  // ── заметки ──────────────────────────────────────────────────────────────
  if (p === '/notes' && req.method === 'POST') {
    const body = await readBody(req);
    const kind = body.get('kind') === 'standalone' ? 'standalone' : 'inline';
    const articleId = body.get('article') || null;
    const result = notesLib.add(sess.record, user, {
      kind: kind,
      articleId: articleId,
      block: body.get('block'),
      quote: body.get('quote'),
      text: body.get('text'),
    });
    if (!result.ok) {
      return go('/notes?error=' + encodeURIComponent(result.error));
    }
    const back = kind === 'inline' && articleId ? '/article/' + articleId + '?added=1' : '/notes?added=1';
    return go(back);
  }

  if (p === '/notes/delete' && req.method === 'POST') {
    const body = await readBody(req);
    notesLib.remove(sess.record, body.get('id'));
    return go(safeBack(body.get('back') || '/notes'));
  }

  if (p === '/notes/export') {
    // Экспорт — право человека на свои данные, а не функция тарифа.
    const text = notesLib.exportMarkdown(sess.record, P.BY_ID);
    res.writeHead(200, {
      'Content-Type': 'text/markdown; charset=utf-8',
      'Content-Disposition': 'attachment; filename="my-notes.md"',
    });
    return res.end(text);
  }

  // ── вопрос-ответ ─────────────────────────────────────────────────────────
  if (p === '/qa' && req.method === 'POST') {
    const body = await readBody(req);
    const ticket = store.addTicket({
      id: store.nextId('K'),
      uid: sess.uid,
      name: body.get('name') || '',
      email: body.get('email') || '',
      category: body.get('category') || 'Другое',
      text: body.get('text') || '',
      at: new Date().toISOString(),
      level: user.level,
    });
    return go('/qa?ticket=' + ticket.id);
  }

  // ── GET: страницы ────────────────────────────────────────────────────────
  let html = null;

  if (p === '/') html = P.homePage(user);
  else if (p === '/articles') html = P.articlesPage(user, query);
  else if (p.startsWith('/article/by-title/')) {
    // Ссылки из Obsidian выглядят как [[Источники и историография]] — то есть
    // часто по короткому названию, без части после двоеточия.
    const norm = function (s) { return String(s).trim().toLowerCase().replace(/\s+/g, ' '); };
    const target = norm(decodeURIComponent(p.slice('/article/by-title/'.length)));
    const found = P.ARTICLES.find(function (a) {
      return norm(a.title) === target || norm(a.title.split(':')[0]) === target;
    });
    if (found) return go('/article/' + found.id);
    html = null;
  } else if (p.startsWith('/article/')) {
    html = P.articlePage(user, decodeURIComponent(p.slice('/article/'.length)), query);
  } else if (p === '/videos') html = P.videosPage(user, query);
  else if (p === '/search') html = P.searchPage(user, query);
  else if (p === '/qa') html = P.qaPage(user, query, { tickets: store.tickets() });
  else if (p === '/register') html = P.registerPage(user, query);
  else if (p === '/account') html = P.accountPage(user, query);
  else if (p === '/subscribe') html = P.subscribePage(user, query);
  else if (p === '/notes') html = P.notesPage(user, query);
  else if (p === '/levels') html = P.levelsPage(user);
  else if (p === '/prototype') html = P.prototypePage(user);

  const found = html !== null;
  if (!found) html = P.notFoundPage(user);
  send(res, found ? 200 : 404, withSession(html, sess.uid), userHeaders);
});

server.listen(PORT, '0.0.0.0', function () {
  console.log('Прототип запущен: http://localhost:' + PORT);
  console.log('Статей: ' + P.ARTICLES.length + ' · видео: ' + P.VIDEOS.length + ' · тарифов: ' + P.TARIFFS.length);
});
