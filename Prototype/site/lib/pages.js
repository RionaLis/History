'use strict';
// Все страницы сайта. Страницы ничего не решают про доступ — они спрашивают
// can() и рисуют то, что им разрешили.
const md = require('./md');
const content = require('./content');
const notesLib = require('./notes');
const L = require('./layout');
const { can, canItem, POINTS, LEVELS } = require('./access');
const { FLAGS } = require('./entitlements');

const esc = L.esc;
const ARTICLES = content.loadArticles();
const VIDEOS = content.loadVideos();
const QA = content.loadQA();
const BY_ID = {};
ARTICLES.forEach(function (a) { BY_ID[a.id] = a; });

const TARIFFS = [
  { tier: 1, name: 'Читатель', month: 6, year: 60, what: 'все тексты статей, каталог видео, пометки о видео' },
  { tier: 2, name: 'Практик', month: 12, year: 120, what: 'плюс панель связей, плеер в статье, заметки' },
  { tier: 3, name: 'Исследователь', month: 24, year: 240, what: 'плюс подборки-курсы, эксклюзивные лекции, 1000 заметок и конспекты' },
];

// ── мелкие помощники ───────────────────────────────────────────────────────
function articleVideo(a) { return VIDEOS.find(function (v) { return v.article === a.id && !v.exclusive; }) || null; }
function articleLecture(a) { return VIDEOS.find(function (v) { return v.article === a.id && v.exclusive; }) || null; }
function embedUrl(link) {
  const m = String(link).match(/[?&]v=([\w-]{6,})/);
  return m ? 'https://www.youtube.com/embed/' + m[1] : null;
}
function canReadBody(user, a) { return canItem(user, a.bodyLevel, a.id); }
function videoInList(user, v) {
  if (v.exclusive) return canItem(user, POINTS.video.exclusive, v.id);
  return can(user, v.visibleFrom) || (user.grants || []).indexOf(v.id) >= 0;
}
function canPlay(user, v) {
  if (v.exclusive) return canItem(user, POINTS.video.exclusive, v.id);
  return can(user, POINTS.video.in_article);
}

function typeChip(a) {
  if (a.type === 'entity') {
    return '<span class="chip chip-entity" title="Статья о сущности: номер совпадает с Wikidata">' + esc(a.id) + '</span>';
  }
  return '<span class="chip chip-author">авторская</span>';
}

function articleCard(a, user) {
  const full = canReadBody(user, a);
  return '' +
    '<a class="card article-card" href="/article/' + esc(a.id) + '">' +
      '<div class="card-top"><span class="chip">' + esc(a.topic) + '</span>' + typeChip(a) + L.badge(a.bodyLevel) + '</div>' +
      '<h3>' + esc(a.title) + '</h3>' +
      '<p class="card-text">' + esc(a.summary) + '</p>' +
      '<div class="card-foot"><span class="muted">' + esc(a.updated) + '</span>' +
        '<span class="more">' + (full ? 'Читать' : 'Открыть превью') + ' →</span></div>' +
    '</a>';
}

function videoCard(v, user, opts) {
  opts = opts || {};
  const open = videoInList(user, v);
  const playable = canPlay(user, v);
  const embed = embedUrl(v.url);
  let actions = '';

  if (!open) {
    actions = '<span class="video-locked">' + L.LOCK + 'Уровень ' + v.visibleFrom + '</span>';
  } else if (playable && embed) {
    actions = '<div class="player" data-embed="' + esc(embed) + '">' +
        '<button class="player-poster" data-player="1" type="button" aria-label="Смотреть: ' + esc(v.title) + '">' +
          L.poster(v) + '<span class="player-hint">Смотреть здесь</span></button></div>' +
      '<a class="video-link" href="' + esc(v.url) + '" target="_blank" rel="noopener">Открыть на YouTube ↗</a>';
  } else {
    actions = '<a class="video-link" href="' + esc(v.url) + '" target="_blank" rel="noopener">Открыть на YouTube ↗</a>' +
      '<span class="video-note">Плеер на странице — с уровня ' + POINTS.video.in_article + '</span>';
  }

  return '' +
    '<div class="card video-card' + (open ? '' : ' is-locked') + '">' +
      '<div class="video-poster-wrap">' + L.poster(v) +
        (v.exclusive ? '<span class="ribbon">Эксклюзив · ур. 3</span>' : '') +
        (open ? '' : '<span class="poster-lock">' + L.LOCK + '</span>') + '</div>' +
      '<div class="video-body">' +
        '<div class="card-top"><span class="chip">' + esc(v.topic) + '</span><span class="muted">' + esc(v.date) + ' · ' + esc(v.duration) + '</span></div>' +
        '<h3 class="video-title">' + esc(v.title) + '</h3>' +
        (opts.showActions === false ? '' : '<div class="video-actions">' + actions + '</div>') +
      '</div></div>';
}

// ── карточка Wikidata ──────────────────────────────────────────────────────
// Бесплатный слой статьи о сущности: факты (CC0) + ссылка на Википедию.
function wikidataCard(a) {
  const s = a.snapshot;
  if (!s) {
    return '<div class="notice">Снимок Wikidata не найден. В настоящей версии его готовит скрипт.</div>';
  }

  const img = s.image;
  const wp = s.wikipedia || {};

  const figure = img && img.src
    ? '<figure class="wd-fig">' +
        '<a href="' + esc(img.source_url || wp.url || '#') + '" target="_blank" rel="noopener">' +
          '<img src="' + esc(img.src) + '" alt="' + esc(img.caption || s.label) + '"' +
            (img.width ? ' width="' + img.width + '"' : '') +
            (img.height ? ' height="' + img.height + '"' : '') +
            ' loading="lazy">' +
        '</a>' +
        '<figcaption>' + esc(img.caption || '') +
          (img.author ? ' · ' + esc(img.author) : '') +
          (img.license ? ' · ' + esc(img.license) : '') +
        '</figcaption>' +
      '</figure>'
    : '';

  return '' +
    '<div class="wd-card">' +
      '<div class="wd-head">' +
        '<div>' +
          '<div class="wd-label">' + esc(s.label) + '</div>' +
          '<div class="wd-desc">' + esc(s.description) + '</div>' +
        '</div>' +
        '<a class="wd-id" href="https://www.wikidata.org/wiki/' + esc(s.wikidata) + '" target="_blank" rel="noopener">' + esc(s.wikidata) + ' ↗</a>' +
      '</div>' +
      '<div class="wd-main">' +
        figure +
        '<dl class="wd-facts">' + s.facts.map(function (f) {
          return '<div class="wd-fact"><dt>' + esc(f.label) + '</dt><dd>' + esc(f.value) + '</dd></div>';
        }).join('') + '</dl>' +
      '</div>' +
      (s.relations && s.relations.length
        ? '<div class="wd-rel"><span class="wd-rel-label">Связи</span>' + s.relations.map(function (r) {
            return '<span class="rel">' + esc(r.label) + ' <em>' + esc(r.relation) + '</em></span>';
          }).join('') + '</div>'
        : '') +
      (wp.url
        ? '<div class="wd-actions">' +
            '<a class="btn btn-small" href="' + esc(wp.url) + '" target="_blank" rel="noopener">Подробнее в Википедии ↗</a>' +
            '<span class="muted small">Откроется в новой вкладке. Доступно всем, без регистрации и подписки.</span>' +
          '</div>'
        : '') +
      '<div class="wd-foot">' +
        'Факты — Wikidata, CC0. ' +
        (wp.url ? 'Текст и изображения в Википедии и на Викискладе — ' + esc(wp.license || 'CC BY-SA') + ', <a href="' + esc(wp.authors_url || wp.url) + '" target="_blank" rel="noopener">авторы</a>, <a href="' + esc(wp.url) + '" target="_blank" rel="noopener">версия</a>.' : '') +
        ' Снимок от ' + esc(s.fetched_at || '—') + '.' +
      '</div>' +
    '</div>';
}

function graphSvg(center, others) {
  const cx = 160, cy = 108, r = 74, w = 320, h = 224;
  const nodes = others.map(function (a, i) {
    const ang = -Math.PI / 2 + i * (2 * Math.PI / Math.max(others.length, 1));
    return { a: a, x: cx + r * Math.cos(ang) * 1.15, y: cy + r * Math.sin(ang) };
  });
  let svg = '<svg class="graph" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="Связи статьи">';
  nodes.forEach(function (n) {
    svg += '<line x1="' + cx + '" y1="' + cy + '" x2="' + n.x.toFixed(1) + '" y2="' + n.y.toFixed(1) + '" stroke="rgba(232,193,124,.28)" stroke-width="1"/>';
  });
  svg += '<circle cx="' + cx + '" cy="' + cy + '" r="9" fill="#e8c17c"/>';
  svg += '<text x="' + cx + '" y="' + (cy + 26) + '" text-anchor="middle" font-size="9" fill="#e8c17c" font-family="system-ui,sans-serif">эта статья</text>';
  nodes.forEach(function (n) {
    const short = n.a.title.length > 16 ? n.a.title.slice(0, 15) + '…' : n.a.title;
    svg += '<a href="/article/' + esc(n.a.id) + '">' +
      '<circle cx="' + n.x.toFixed(1) + '" cy="' + n.y.toFixed(1) + '" r="6" fill="#8fa6bd"/>' +
      '<text x="' + n.x.toFixed(1) + '" y="' + (n.y + (n.y < cy ? -12 : 20)).toFixed(1) + '" text-anchor="middle" font-size="9" fill="#b9c6d3" font-family="system-ui,sans-serif">' + esc(short) + '</text></a>';
  });
  return svg + '</svg>';
}

function relatedFor(a) {
  const others = ARTICLES.filter(function (x) { return x.id !== a.id; });
  const scored = others.map(function (x) {
    let s = 0;
    if (x.topic === a.topic) s += 3;
    x.tags.forEach(function (t) { if (a.tags.indexOf(t) >= 0) s += 2; });
    return { a: x, s: s };
  });
  scored.sort(function (p, q) { return q.s - p.s; });
  return scored.slice(0, 3).map(function (x) { return x.a; });
}

// ── главная ────────────────────────────────────────────────────────────────
function homePage(user) {
  const full = ARTICLES.filter(function (a) { return canReadBody(user, a); }).length;
  const vids = VIDEOS.filter(function (v) { return videoInList(user, v); }).length;

  const body = '' +
    '<section class="hero"><div class="wrap">' +
      '<div class="hero-text">' +
        '<span class="eyebrow">База знаний · ' + ARTICLES.length + ' статей · ' + VIDEOS.length + ' видео</span>' +
        '<h1>Куликовская битва:<br>событие, источники, память</h1>' +
        '<p class="lead">Учебный прототип с четырьмя уровнями доступа. Переключайте уровень в полосе сверху и смотрите, как меняется одна и та же страница.</p>' +
        '<div class="hero-actions"><a class="btn" href="/articles">Открыть статьи</a>' +
          '<a class="btn btn-ghost" href="/levels">Сравнить уровни</a></div>' +
      '</div>' +
      '<div class="hero-stat">' +
        '<div class="stat-line"><span>Ваш уровень</span><strong>' + user.level + ' · ' + esc(LEVELS[user.level].name) + '</strong></div>' +
        '<div class="stat-line"><span>Статей целиком</span><strong>' + full + ' из ' + ARTICLES.length + '</strong></div>' +
        '<div class="stat-line"><span>Видео в каталоге</span><strong>' + vids + ' из ' + VIDEOS.length + '</strong></div>' +
        '<div class="stat-line"><span>Заметки</span><strong>' + (user.notesLimit ? user.notesCount + ' из ' + user.notesLimit : 'нет') + '</strong></div>' +
        '<div class="stat-line"><span>Панель связей</span><strong>' + (can(user, POINTS.article.extras) ? 'есть' : 'закрыта') + '</strong></div>' +
        '<a class="small-link" href="/account">В личный кабинет →</a>' +
      '</div>' +
    '</div></section>' +

    '<section class="wrap section"><div class="section-head"><h2>Статьи</h2><a class="small-link" href="/articles">Все статьи →</a></div>' +
      '<div class="grid grid-articles">' + ARTICLES.map(function (a) { return articleCard(a, user); }).join('') + '</div></section>' +

    '<section class="wrap section"><div class="section-head"><h2>Видео</h2><a class="small-link" href="/videos">Каталог видео →</a></div>' +
      '<div class="grid grid-videos">' + VIDEOS.slice(0, 3).map(function (v) { return videoCard(v, user, { showActions: false }); }).join('') + '</div></section>' +

    '<section class="wrap section"><div class="how">' +
      '<div class="how-col"><span class="how-n">1</span><h3>Два типа статей</h3><p>О сущностях — с номером Wikidata и карточкой фактов. Авторские — со своим номером, вступлением и оглавлением.</p></div>' +
      '<div class="how-col"><span class="how-n">2</span><h3>Уровень — из разрешений</h3><p>Уровень не хранится «сам по себе»: он вычисляется из записей о покупках, промокодах и фазе запуска.</p></div>' +
      '<div class="how-col"><span class="how-n">3</span><h3>Закрытое не приходит в браузер</h3><p>Сервер не отправляет платный текст тому, у кого нет доступа. Спрятать оформлением — не защита.</p></div>' +
    '</div><p class="center muted"><a class="small-link" href="/prototype">Посмотреть, как это написано в коде →</a></p></section>';

  return L.page({ title: 'Главная', user: user, active: '/', back: '/', body: body });
}

// ── список статей ──────────────────────────────────────────────────────────
function articlesPage(user, query) {
  const topics = Array.from(new Set(ARTICLES.map(function (a) { return a.topic; })));
  const current = query.topic || '';
  const types = query.type || '';
  let list = ARTICLES.slice();
  if (current) list = list.filter(function (a) { return a.topic === current; });
  if (types) list = list.filter(function (a) { return a.type === types; });

  const chips = '<a class="chip-btn' + (current || types ? '' : ' is-on') + '" href="/articles">Все</a>' +
    topics.map(function (t) {
      return '<a class="chip-btn' + (current === t ? ' is-on' : '') + '" href="/articles?topic=' + encodeURIComponent(t) + '">' + esc(t) + '</a>';
    }).join('') +
    '<a class="chip-btn' + (types === 'entity' ? ' is-on' : '') + '" href="/articles?type=entity">о сущностях</a>' +
    '<a class="chip-btn' + (types === 'authorial' ? ' is-on' : '') + '" href="/articles?type=authorial">авторские</a>';

  const body = '' +
    '<section class="wrap section">' +
      '<div class="page-head"><h1>Статьи</h1>' +
        '<p class="lead">Две статьи открыты целиком, остальные — по подписке. Статьи о сущностях показывают карточку из Wikidata, авторские — вступление и оглавление.</p></div>' +
      '<div class="chips">' + chips + '</div>' +
      '<div class="grid grid-articles">' + list.map(function (a) { return articleCard(a, user); }).join('') + '</div>' +
    '</section>';
  return L.page({ title: 'Статьи', user: user, active: '/articles', back: '/articles', body: body });
}

// ── страница статьи ────────────────────────────────────────────────────────
function articlePage(user, id, query) {
  const a = BY_ID[id];
  if (!a) return null;

  const full = canReadBody(user, a);
  const extras = can(user, a.extrasLevel);
  const related = relatedFor(a);
  const v = articleVideo(a);
  const lecture = articleLecture(a);
  const heads = md.outline(a.markdown);
  const back = '/article/' + a.id;

  // Заметки к этой статье (только свои, только с уровня заметок)
  const myInline = (user.record.notes || []).filter(function (n) {
    return n.kind === 'inline' && n.articleId === a.id;
  });

  const noteButton = user.notesEnabled && full
    ? function (i) { return '<button class="note-add" type="button" data-article="' + esc(a.id) + '" data-block="' + i + '" title="Добавить заметку к абзацу">＋</button>'; }
    : null;

  let contentBlock = '';
  if (a.type === 'entity') {
    contentBlock = wikidataCard(a) +
      (full
        ? '<div class="prose">' + md.render(a.markdown, { noteButton: noteButton }) + '</div>'
        : '<div class="preview-box"><div class="preview-label">Вступление · открыто всем</div>' +
          '<p class="preview-text">' + esc(a.preview) + '</p>' +
          '<div class="outline"><div class="outline-title">' + L.LOCK + ' Оглавление закрытой части</div><ol>' +
          heads.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('') + '</ol></div></div>' +
          L.lockPanel({ title: 'Полный разбор', text: 'Текст открывается уровнем ' + a.bodyLevel + '. В HTML его нет: сервер не отправил закрытое содержимое.', required: a.bodyLevel, back: back }));
  } else {
    contentBlock = full
      ? '<div class="prose">' + md.render(a.markdown, { noteButton: noteButton }) + '</div>'
      : '<div class="preview-box"><div class="preview-label">Превью · открыто всем</div>' +
        '<p class="preview-text">' + esc(a.preview) + '</p>' +
        '<div class="outline"><div class="outline-title">' + L.LOCK + ' Оглавление закрытой части</div><ol>' +
        heads.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('') + '</ol></div></div>' +
        L.lockPanel({ title: 'Полный текст статьи', text: 'Текст открывается уровнем ' + a.bodyLevel + '. В HTML его нет: сервер не отправил закрытое содержимое.', required: a.bodyLevel, back: back });
  }

  let videoBlock = '';
  if (v && can(user, a.videoHintLevel)) {
    if (canPlay(user, v) && embedUrl(v.url)) {
      videoBlock = '<section class="article-video"><div class="section-head"><h2>Видео по этой теме</h2><span class="chip">ур. ' + POINTS.video.in_article + '+</span></div>' +
        '<div class="player" data-embed="' + esc(embedUrl(v.url)) + '"><button class="player-poster" data-player="1" type="button">' + L.poster(v) + '<span class="player-hint">Смотреть здесь</span></button></div>' +
        '<p class="muted small">Плеер загружается по нажатию. <a href="' + esc(v.url) + '" target="_blank" rel="noopener">Открыть на YouTube ↗</a></p></section>';
    } else {
      videoBlock = '<section class="article-video"><div class="section-head"><h2>Видео по этой теме</h2><span class="chip">ур. ' + POINTS.video.in_article + '+</span></div>' +
        '<div class="video-hint-card">' + L.poster(v) + '<div><div class="video-hint-title">' + esc(v.title) + '</div>' +
        '<p class="muted small">Видео есть, но запуск прямо в статье открывается с уровня ' + POINTS.video.in_article + '. Пока ищите его в каталоге по названию.</p>' +
        '<a class="btn btn-ghost btn-small" href="/videos?q=' + encodeURIComponent(v.title) + '">Найти в каталоге</a></div></div></section>';
    }
  }

  let extrasBlock = '';
  if (extras) {
    extrasBlock = '<section class="extras"><div class="section-head"><h2>Дополнительные поля</h2><span class="chip">ур. ' + a.extrasLevel + '+</span></div>' +
      '<div class="extras-grid">' +
        '<div class="extras-card"><h3>Панель связей</h3><p class="muted small">Эта статья и соседние сюжеты. Кликните узел, чтобы перейти.</p>' + graphSvg(a, related) + '</div>' +
        '<div class="extras-card"><h3>Связанные материалы</h3><ul class="link-list">' +
          related.map(function (r) { return '<li><a href="/article/' + esc(r.id) + '">' + esc(r.title) + '</a> <span class="muted">· ур. ' + r.bodyLevel + '+</span></li>'; }).join('') +
          VIDEOS.filter(function (x) { return x.topic === a.topic && !x.exclusive; }).slice(0, 3).map(function (x) {
            return '<li><a href="/videos?q=' + encodeURIComponent(x.title) + '">Видео: ' + esc(x.title) + '</a></li>';
          }).join('') + '</ul></div>' +
        '<div class="extras-card"><h3>Поля к заметке</h3>' +
          '<div class="field"><span class="field-label">Ключевые даты</span><span class="field-value">1359 · 1367 · 1375 · 1378 · 1380</span></div>' +
          '<div class="field"><span class="field-label">Спорные места</span><span class="field-value">численность войск, место боя, роль Олега Рязанского</span></div>' +
          '<div class="field"><span class="field-label">Что почитать</span><span class="field-value">летописные повести, «Задонщина», «Сказание о Мамаевом побоище»</span></div>' +
          (user.notesEnabled
            ? '<a class="btn btn-ghost btn-small" href="/notes">Мои заметки →</a>'
            : '<p class="muted small">Заметки к этим полям появятся на уровне ' + FLAGS.notesMinLevel + '.</p>') +
        '</div></div></section>';
  } else {
    extrasBlock = '<section class="extras">' + L.lockPanel({
      title: 'Дополнительные поля статьи',
      text: 'Этот слой открывается уровнем ' + a.extrasLevel + '. Внутри:',
      list: ['панель связей статьи с соседними сюжетами', 'связанные видео и материалы по теме', 'поля, которые можно добавить в свои заметки'],
      required: a.extrasLevel, back: back,
    }) + '</section>';
  }

  let notesBlock = '';
  if (myInline.length) {
    notesBlock = '<section class="my-notes"><div class="section-head"><h2>Мои заметки к этой статье</h2>' +
      '<a class="small-link" href="/notes">Все заметки →</a></div>' +
      myInline.map(function (n) {
        const state = notesLib.anchorState(n, a);
        return '<div class="note-item note-' + state + '">' +
          (n.quote ? '<div class="note-quote">' + esc(n.quote) + '</div>' : '<div class="note-quote muted">без цитаты</div>') +
          '<div class="note-text">' + esc(n.text) + '</div>' +
          '<div class="note-meta">' + esc(n.createdAt.slice(0, 16).replace('T', ' ')) +
            (state === 'changed' ? ' · <span class="warn">фрагмент изменён</span>' : '') +
            (state === 'lost' ? ' · <span class="warn">абзац не найден</span>' : '') +
            ' <form method="post" action="/notes/delete" class="inline-form"><input type="hidden" name="id" value="' + esc(n.id) + '"><button class="note-del" type="submit">удалить</button></form></div>' +
          '</div>';
      }).join('') + '</section>';
  } else if (user.notesEnabled && full) {
    notesBlock = '<p class="muted small notes-hint">Наведите на абзац и нажмите «＋» слева, чтобы оставить заметку. Заметки видит только автор.</p>';
  }

  let lectureBlock = '';
  if (lecture) {
    if (canPlay(user, lecture)) {
      lectureBlock = '<section class="article-video"><div class="section-head"><h2>Эксклюзивная лекция</h2><span class="chip chip-gold">ур. 3</span></div>' +
        '<div class="player" data-embed="' + esc(embedUrl(lecture.url)) + '"><button class="player-poster" data-player="1" type="button">' + L.poster(lecture) + '<span class="player-hint">Смотреть здесь</span></button></div>' +
        '<p class="muted small">' + esc(lecture.duration) + ' · в настоящей версии здесь будет водяной знак с вашей почтой.</p></section>';
    } else {
      lectureBlock = '<section class="article-video">' + L.lockPanel({
        title: 'Эксклюзивная лекция · ' + lecture.duration,
        text: '«' + lecture.title + '» — закрытый доступ. Открывается уровнем 3 или персональным промокодом.',
        required: 3, back: back,
      }) + '</section>';
    }
  }

  const body = '' +
    '<article class="wrap article">' +
      '<div class="crumbs"><a href="/articles">Статьи</a> <span>/</span> <span class="muted">' + esc(a.topic) + '</span></div>' +
      '<header class="article-head">' +
        '<div class="card-top"><span class="chip">' + esc(a.topic) + '</span>' + typeChip(a) + L.badge(a.bodyLevel) +
          (extras ? '' : '<span class="badge badge-soft">доп. поля — ур. ' + a.extrasLevel + '+</span>') + '</div>' +
        '<h1>' + esc(a.title) + '</h1>' +
        '<p class="lead">' + esc(a.summary) + '</p>' +
        '<div class="meta">обновлено ' + esc(a.updated) + ' · ' + esc(a.tags.join(' · ')) + '</div>' +
      '</header>' +
      contentBlock + notesBlock + videoBlock + extrasBlock + lectureBlock +
      '<div class="article-nav"><a class="btn btn-ghost btn-small" href="/articles">← Все статьи</a>' +
        '<a class="btn btn-ghost btn-small" href="/search?q=' + encodeURIComponent(a.title.split(':')[0]) + '">Искать по теме</a></div>' +
    '</article>';

  return L.page({ title: a.title, user: user, active: '/articles', back: back, body: body });
}

// ── видео ──────────────────────────────────────────────────────────────────
function videosPage(user, query) {
  const q = (query.q || '').trim();
  const sort = query.sort === 'title' ? 'title' : 'date';
  const canSeeCatalog = can(user, POINTS.video.in_list);

  let list = VIDEOS.slice();
  if (!canSeeCatalog) list = list.filter(function (v) { return v.visibleFrom === 0 && !v.exclusive; });
  if (q) {
    const found = content.searchVideos(list, q).map(function (v) { return v.id; });
    list = list.filter(function (v) { return found.indexOf(v.id) >= 0 || v.exclusive; });
  }
  list.sort(function (x, y) {
    return sort === 'title' ? x.title.localeCompare(y.title, 'ru') : String(y.date).localeCompare(String(x.date));
  });
  const visibleCount = VIDEOS.filter(function (v) { return videoInList(user, v); }).length;

  const body = '' +
    '<section class="wrap section">' +
      '<div class="page-head"><h1>Каталог видео</h1><p class="lead">Видео лежат в открытом канале — их может посмотреть любой. Уровни на сайте открывают удобство: каталог, запуск внутри статьи и подборки.</p></div>' +
      (!canSeeCatalog
        ? '<div class="notice">На вашем уровне видно <strong>' + list.length + ' видео</strong> из ' + VIDEOS.length + '. Полный каталог с сортировкой открывается уровнем ' + POINTS.video.in_list + '.' +
          '<a class="btn btn-small" href="/level?to=1&back=%2Fvideos">Посмотреть как уровень 1</a></div>'
        : '<div class="notice notice-quiet">Видно ' + visibleCount + ' из ' + VIDEOS.length + ' позиций. Эксклюзивная лекция — уровень 3.</div>') +
      '<div class="toolbar">' +
        '<form class="toolbar-search" method="get" action="/videos">' +
          '<input type="search" name="q" value="' + esc(q) + '" placeholder="Поиск по видео: Вожа, Тохтамыш, источники">' +
          '<input type="hidden" name="sort" value="' + sort + '"><button class="btn btn-small" type="submit">Найти</button></form>' +
        '<div class="chips" style="margin:0">' +
          '<a class="chip-btn' + (sort === 'date' ? ' is-on' : '') + '" href="/videos?sort=date' + (q ? '&q=' + encodeURIComponent(q) : '') + '">По дате</a>' +
          '<a class="chip-btn' + (sort === 'title' ? ' is-on' : '') + '" href="/videos?sort=title' + (q ? '&q=' + encodeURIComponent(q) : '') + '">По названию</a>' +
        '</div></div>' +
      (list.length
        ? '<div class="grid grid-videos">' + list.map(function (v) { return videoCard(v, user); }).join('') + '</div>'
        : '<p class="empty">Ничего не нашлось. <a href="/videos">Сбросить поиск</a></p>') +
    '</section>';

  return L.page({ title: 'Видео', user: user, active: '/videos', back: '/videos', body: body });
}

// ── поиск ──────────────────────────────────────────────────────────────────
function searchPage(user, query) {
  const q = (query.q || '').trim();
  const type = query.type === 'articles' || query.type === 'videos' ? query.type : 'all';
  const foundArticles = q ? content.searchArticles(ARTICLES, q) : [];
  const canVideoSearch = can(user, POINTS.video.in_list);
  const visibleVideos = VIDEOS.filter(function (v) { return videoInList(user, v); });
  const foundVideos = q && canVideoSearch ? content.searchVideos(visibleVideos, q) : [];

  const body = '' +
    '<section class="wrap section">' +
      '<div class="page-head"><h1>Поиск</h1><p class="lead">Поиск по статьям открыт всем, включая закрытые: находятся заголовок и превью. Поиск по видео — с уровня ' + POINTS.video.in_list + '.</p></div>' +
      '<form class="big-search" method="get" action="/search">' +
        '<input type="search" name="q" value="' + esc(q) + '" placeholder="Например: Вожа, Тохтамыш, источники, засадный полк" autofocus>' +
        (type !== 'all' ? '<input type="hidden" name="type" value="' + type + '">' : '') +
        '<button class="btn" type="submit">Искать</button></form>' +
      '<div class="chips">' +
        '<a class="chip-btn' + (type === 'all' ? ' is-on' : '') + '" href="/search?q=' + encodeURIComponent(q) + '">Всё</a>' +
        '<a class="chip-btn' + (type === 'articles' ? ' is-on' : '') + '" href="/search?q=' + encodeURIComponent(q) + '&type=articles">Статьи (' + foundArticles.length + ')</a>' +
        '<a class="chip-btn' + (type === 'videos' ? ' is-on' : '') + '" href="/search?q=' + encodeURIComponent(q) + '&type=videos">Видео (' + (canVideoSearch ? foundVideos.length : '—') + ')</a>' +
      '</div>' +
      (!q ? '<p class="empty">Введите запрос — покажу, что найдётся.</p>' : '') +
      (q && (type === 'all' || type === 'articles') ? '<div class="section"><div class="section-head"><h2>Статьи</h2><span class="muted">' + foundArticles.length + '</span></div>' +
        (foundArticles.length ? '<div class="grid grid-articles">' + foundArticles.map(function (a) { return articleCard(a, user); }).join('') + '</div>'
          : '<p class="empty">По статьям ничего не нашлось.</p>') + '</div>' : '') +
      (q && (type === 'all' || type === 'videos') ? '<div class="section"><div class="section-head"><h2>Видео</h2><span class="muted">' + (canVideoSearch ? foundVideos.length : 'закрыто') + '</span></div>' +
        (!canVideoSearch
          ? '<div class="notice">Поиск по видео открывается уровнем ' + POINTS.video.in_list + '. Сейчас доступны только ' + visibleVideos.length + ' ролика на страницах сайта.</div>'
          : (foundVideos.length ? '<div class="grid grid-videos">' + foundVideos.map(function (v) { return videoCard(v, user); }).join('') + '</div>' : '<p class="empty">По видео ничего не нашлось.</p>')) + '</div>' : '') +
    '</section>';

  return L.page({ title: 'Поиск', user: user, active: '/search', back: '/search', body: body });
}

// ── вопросы ────────────────────────────────────────────────────────────────
function qaPage(user, query, extra) {
  const ticket = (extra.tickets || []).find(function (t) { return t.id === query.ticket; });
  const myTickets = (extra.tickets || []).filter(function (t) { return t.uid === user.uid; });

  const body = '' +
    '<section class="wrap section narrow">' +
      '<div class="page-head"><h1>Вопросы и неполадки</h1><p class="lead">Это не форум: здесь задают технические вопросы — про вход, оплату, видео и ошибки в тексте.</p></div>' +
      (ticket ? '<div class="notice notice-ok">Вопрос принят. Номер обращения: <strong>' + esc(ticket.id) + '</strong> (категория: ' + esc(ticket.category) + ').</div>' : '') +
      '<div class="faq">' + QA.faq.map(function (f, i) {
        return '<details class="faq-item"' + (i === 0 ? ' open' : '') + '><summary>' + esc(f.q) + '</summary><p>' + esc(f.a) + '</p></details>';
      }).join('') + '</div>' +
      '<div class="card form-card"><h2>Задать вопрос</h2>' +
        '<form method="post" action="/qa" class="form" data-reload="/qa">' +
          '<label>Ваше имя<input type="text" name="name" value="' + esc(user.name === 'Гость' ? '' : user.name) + '" required></label>' +
          '<label>Почта для ответа<input type="email" name="email" value="' + esc(user.email) + '" required></label>' +
          '<label>Категория<select name="category">' + QA.categories.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join('') + '</select></label>' +
          '<label>Что случилось<textarea name="text" rows="5" required placeholder="Опишите, на какой странице и что произошло"></textarea></label>' +
          '<button class="btn" type="submit">Отправить</button>' +
          '<p class="muted small">' + esc(QA.note) + '</p>' +
        '</form></div>' +
      (myTickets.length
        ? '<div class="card"><h3>Мои обращения</h3><ul class="link-list">' + myTickets.map(function (t) {
            return '<li><code>' + esc(t.id) + '</code> · ' + esc(t.category) + ' · ' + esc(t.at.slice(0, 16).replace('T', ' ')) + '</li>';
          }).join('') + '</ul></div>'
        : '') +
    '</section>';

  return L.page({ title: 'Вопросы', user: user, active: '/qa', back: '/qa', body: body });
}

// ── регистрация ────────────────────────────────────────────────────────────
function registerPage(user, query) {
  const body = '' +
    '<section class="wrap section narrow">' +
      '<div class="page-head"><h1>Регистрация</h1><p class="lead">Демонстрационная форма: оплата не подключена. Уровень выдаёт не форма, а разрешения — ниже видно, как они устроены.</p></div>' +
      (query.welcome ? '<div class="notice notice-ok">Аккаунт создан. Откройте <a href="/account">личный кабинет</a>, чтобы увидеть свои разрешения.</div>' : '') +
      '<div class="card form-card"><form method="post" action="/register" class="form">' +
        '<label>Имя<input type="text" name="name" value="' + esc(user.name === 'Гость' ? '' : user.name) + '" placeholder="Как к вам обращаться" required></label>' +
        '<label>Почта<input type="email" name="email" value="' + esc(user.email) + '" placeholder="you@example.com" required></label>' +
        '<button class="btn" type="submit">' + (user.name === 'Гость' ? 'Создать демо-аккаунт' : 'Сохранить') + '</button>' +
        '<p class="muted small">Настоящая регистрация будет с подтверждением почты. Уровень придёт из оплаченной подписки или из фазы запуска, а не из формы.</p>' +
      '</form></div>' +
      '<div class="card"><h3>Что даёт регистрация в прототипе</h3>' +
        '<p class="muted small">Ровно то, что прописано в модели: запись в базе, к которой привязываются разрешения, покупки и заметки. Сейчас уровень всё ещё задаётся демо-переключателем — на этапе подключения оплаты вместо него появится запись о покупке.</p></div>' +
    '</section>';
  return L.page({ title: 'Регистрация', user: user, active: '/register', back: '/register', body: body });
}

// ── личный кабинет ─────────────────────────────────────────────────────────
function accountPage(user, query) {
  const ents = user.entitlements || [];
  const manual = ents.filter(function (e) { return e.source === 'manual'; }).pop();
  const purchases = (user.record.purchases || []).slice().reverse();

  const srcLabel = {
    purchase: 'покупка', manual: 'демо-переключение', promo: 'промокод',
    phase: 'фаза запуска', compensation: 'компенсация',
  };

  const entRows = ents.map(function (e) {
    const what = e.kind === 'level' ? 'уровень ' + e.level : 'объект «' + e.item + '»';
    const till = e.to ? e.to.slice(0, 10) : 'бессрочно';
    return '<tr><td>' + esc(what) + '</td><td>' + esc(srcLabel[e.source] || e.source) + '</td><td>' + esc(till) + '</td></tr>';
  }).join('');

  const rows = [
    ['Полные тексты статей', POINTS.article.body, ARTICLES.filter(function (a) { return canReadBody(user, a); }).length + ' из ' + ARTICLES.length],
    ['Каталог видео', POINTS.video.in_list, can(user, 1) ? 'да' : 'нет'],
    ['Плеер видео в статье', POINTS.video.in_article, can(user, 2) ? 'да' : 'нет'],
    ['Панель связей и доп. поля', POINTS.article.extras, can(user, 2) ? 'да' : 'нет'],
    ['Эксклюзивные лекции', POINTS.video.exclusive, can(user, 3) ? 'да' : 'нет'],
    ['Заметки', FLAGS.notesMinLevel, user.notesLimit ? user.notesCount + ' из ' + user.notesLimit : 'нет'],
    ['Экспорт заметок', 0, 'всегда'],
  ];

  const body = '' +
    '<section class="wrap section narrow">' +
      '<div class="page-head"><h1>Личный кабинет</h1><p class="lead">Здесь видно, из чего сложился ваш доступ: не «тариф», а набор записей о разрешениях.</p></div>' +
      (query.paid ? '<div class="notice notice-ok">Покупка записана (заглушка оплаты). Обратите внимание: в списке разрешений появился источник «покупка», а демо-переключение убрано.</div>' : '') +
      (query.promo === 'ok' ? '<div class="notice notice-ok">Промокод применён.</div>' : '') +
      (query.promo === 'bad' ? '<div class="notice">Такого кода нет.</div>' : '') +
      (query.welcome ? '<div class="notice notice-ok">Аккаунт создан.</div>' : '') +

      '<div class="card account-card">' +
        '<div class="account-head">' +
          '<div><div class="muted small">Вы вошли как</div><div class="account-name">' + esc(user.name) + '</div>' +
            '<div class="muted small">' + (user.email ? esc(user.email) : 'почта не указана') + ' · id ' + esc(user.uid.slice(0, 8)) + '</div></div>' +
          '<div class="account-level"><div class="big-level">' + user.level + '</div><div class="muted small">' + esc(LEVELS[user.level].name) + '</div>' +
            (manual ? '<div class="warn small">демо-переопределение</div>' : '') + '</div>' +
        '</div>' +
        '<table class="tbl"><tbody>' + rows.map(function (r) {
          const ok = r[2] !== 'нет';
          return '<tr><td>' + esc(r[0]) + '</td><td class="muted">' + (r[1] > 0 ? 'с уровня ' + r[1] : 'всем') + '</td><td class="' + (ok ? 'ok' : 'no') + '">' + esc(r[2]) + '</td></tr>';
        }).join('') + '</tbody></table>' +
        '<div class="account-actions">' +
          '<a class="btn btn-ghost btn-small" href="/levels">Сравнить уровни</a>' +
          '<a class="btn btn-ghost btn-small" href="/register">Изменить профиль</a>' +
          '<a class="btn btn-ghost btn-small" href="/subscribe">Тарифы и оплата</a>' +
          '<a class="btn btn-ghost btn-small" href="/reset">Сбросить демо</a>' +
        '</div>' +
      '</div>' +

      '<div class="card"><h3>Из чего сложился доступ</h3>' +
        (ents.length
          ? '<table class="tbl"><thead><tr><th>Что</th><th>Источник</th><th>Действует до</th></tr></thead><tbody>' + entRows + '</tbody></table>'
          : '<p class="muted small">Разрешений нет — вы на бесплатном уровне. Переключите уровень сверху или возьмите тариф.</p>') +
        (manual ? '<p class="muted small warn">Сейчас действует демо-переключение: оно перекрывает покупки, промокоды и фазу запуска. Уберите его — вернётся доступ из настоящих записей. <a class="btn btn-ghost btn-small" href="/level/clear?back=%2Faccount">Убрать демо-переопределение</a></p>' : '') +
      '</div>' +

      '<div class="card"><h3>Покупки</h3>' +
        (purchases.length
          ? '<table class="tbl"><thead><tr><th>Запись</th><th>Тариф</th><th>Цена</th><th>Оплачено</th><th>Действует до</th></tr></thead><tbody>' +
            purchases.map(function (p) {
              return '<tr><td><code>' + esc(p.id) + '</code></td><td>уровень ' + p.tier + ' · ' + esc(p.period) + '</td><td>' + p.price + ' ' + esc(p.currency) + '</td><td>' + esc(p.paidAt.slice(0, 10)) + '</td><td>' + esc(String(p.to).slice(0, 10)) + '</td></tr>';
            }).join('') + '</tbody></table>'
          : '<p class="muted small">Покупок нет. <a href="/subscribe">Посмотреть тарифы →</a></p>') +
        '<p class="muted small">Запись о покупке — снимок того, что человек купил на момент покупки. Изменение состава тарифов не меняет уже оплаченное.</p>' +
      '</div>' +

      '<div class="card"><h3>Заметки</h3>' +
        (user.notesLimit
          ? '<p class="muted">' + user.notesCount + ' из ' + user.notesLimit + '. <a href="/notes">Открыть мои заметки →</a></p>'
          : '<p class="muted">Заметки открываются с уровня ' + FLAGS.notesMinLevel + '.</p>') +
        '<p class="muted small">Экспорт своих заметок доступен на любом уровне — это право человека на свои данные, а не функция тарифа.</p>' +
      '</div>' +

      '<div class="card form-card"><h3>Промокод</h3>' +
        '<p class="muted small">Демо: <code>KULIKOVO7</code> — доступ к статье «Источники и историография»; <code>NOTES30</code> — уровень 3 на 30 дней.</p>' +
        '<form method="post" action="/promo" class="form-row" data-reload="/account?promo=ok"><input type="text" name="code" placeholder="KULIKOVO7">' +
        '<button class="btn btn-small" type="submit">Применить</button></form></div>' +
    '</section>';

  return L.page({ title: 'Личный кабинет', user: user, active: '/account', back: '/account', body: body });
}

// ── тарифы и заглушка оплаты ───────────────────────────────────────────────
function subscribePage(user) {
  const card = function (t) {
    const on = user.level >= t.tier && !user.entitlements.some(function (e) { return e.source === 'manual'; });
    return '<div class="card tariff' + (on ? ' is-on' : '') + '">' +
      '<div class="card-top"><span class="chip">уровень ' + t.tier + '</span>' + (on ? '<span class="badge badge-free">ваш</span>' : '') + '</div>' +
      '<h3>' + esc(t.name) + '</h3>' +
      '<div class="price">' + t.month + ' € <span class="muted small">/ мес</span></div>' +
      '<div class="muted small">или ' + t.year + ' € за год — два месяца в подарок</div>' +
      '<p class="muted small">' + esc(t.what) + '</p>' +
      '<form method="post" action="/subscribe" class="tariff-form" data-reload="/account?paid=1">' +
        '<input type="hidden" name="tier" value="' + t.tier + '">' +
        '<button class="btn btn-small" name="period" value="month" type="submit">Оформить на месяц</button>' +
        '<button class="btn btn-ghost btn-small" name="period" value="year" type="submit">На год</button>' +
      '</form></div>';
  };

  const body = '' +
    '<section class="wrap section">' +
      '<div class="page-head"><h1>Тарифы</h1><p class="lead">Оплата не подключена: кнопки ниже создают запись о покупке — ровно ту же, что потом будет создавать платёжный сервис.</p></div>' +
      '<div class="notice">Заглушка. Здесь будет платёжная страница: <code>Stripe Checkout</code> или аналог. После оплаты сервис присылает событие, обработчик вызывает <code>grantLevel()</code> — и на сайте ничего не меняется.</div>' +
      '<div class="grid grid-3">' + TARIFFS.map(card).join('') + '</div>' +
      '<div class="card" style="margin-top:24px"><h3>Как это заменяется настоящей оплатой</h3>' +
        '<ol class="link-list">' +
          '<li>Кнопка ведёт не на <code>/subscribe</code>, а на платёжную страницу сервиса.</li>' +
          '<li>Сервис присылает событие об оплате на адрес <code>/webhook</code>.</li>' +
          '<li>Обработчик проверяет подпись и вызывает ту же функцию, что и заглушка: создаёт запись о покупке и разрешение.</li>' +
          '<li>Страницы, проверка доступа, личный кабинет, заметки — не меняются вообще.</li>' +
        '</ol>' +
        '<p class="muted small">Поэтому уровень и хранится не «в тарифе», а в записях о разрешениях: источник записей можно заменить, не трогая сайт.</p></div>' +
    '</section>';
  return L.page({ title: 'Тарифы', user: user, active: '/subscribe', back: '/subscribe', body: body });
}

// ── заметки ────────────────────────────────────────────────────────────────
function notesPage(user, query) {
  const notes = (user.record.notes || []).slice().reverse();
  const canCreate = Boolean(user.notesLimit);
  const hasNotes = notes.length > 0;

  const list = notes.map(function (n) {
    const a = n.articleId ? BY_ID[n.articleId] : null;
    const state = notesLib.anchorState(n, a);
    return '<div class="note-item note-' + state + '">' +
      '<div class="note-head">' +
        (n.kind === 'inline'
          ? '<a href="/article/' + esc(n.articleId) + '">' + esc(a ? a.title : n.articleId) + '</a>'
          : '<span class="chip">отдельная</span>') +
        '<span class="muted small">' + esc(n.createdAt.slice(0, 16).replace('T', ' ')) + '</span></div>' +
      (n.kind === 'inline' ? '<div class="note-quote">' + (n.quote ? esc(n.quote) : '<span class="muted">без цитаты</span>') + '</div>' : '') +
      '<div class="note-text">' + esc(n.text) + '</div>' +
      '<div class="note-meta">' +
        (state === 'changed' ? '<span class="warn">фрагмент изменён — заметка сохранена</span> ' : '') +
        (state === 'lost' ? '<span class="warn">абзац не найден — заметка сохранена</span> ' : '') +
        '<form method="post" action="/notes/delete" class="inline-form"><input type="hidden" name="id" value="' + esc(n.id) + '">' +
        '<button class="note-del" type="submit">удалить</button></form></div></div>';
  }).join('');

  const exportBar = '<div class="notes-bar"><span>Использовано <strong>' + notes.length +
    (canCreate ? ' из ' + user.notesLimit : '') + '</strong></span>' +
    '<span><a class="btn btn-ghost btn-small" href="/notes/export">Выгрузить в Markdown</a></span></div>';

  let inner = '';

  if (!canCreate && !hasNotes) {
    // Нет доступа и нет заметок — только заглушка.
    inner = L.lockPanel({
      title: 'Заметки закрыты',
      text: 'Заметки открываются уровнем ' + FLAGS.notesMinLevel + '. Внутри: заметки к выделенному фрагменту, отдельные записи, конспекты и экспорт.',
      required: FLAGS.notesMinLevel, back: '/notes',
    });
  } else if (!canCreate && hasNotes) {
    // Уровень понизили: создавать нельзя, читать и выгружать — можно.
    inner = '<div class="notice">На вашем уровне создание новых заметок недоступно, но старые не удалены: их можно читать и выгрузить.' +
      '<form method="post" action="/level" class="inline-form"><input type="hidden" name="to" value="3"><input type="hidden" name="back" value="/notes"><button class="btn btn-small" type="submit">Посмотреть как уровень 3</button></form></div>' +
      '<div class="card">' + exportBar + '<p class="muted small">Квота проверяется на сервере, а не в браузере.</p></div>' +
      '<div class="notes-list">' + list + '</div>';
  } else {
    inner = '<div class="card">' + exportBar +
        '<p class="muted small">Квота проверяется на сервере: при понижении уровня создание новых заметок блокируется, чтение и экспорт остаются.</p></div>' +
      '<div class="card form-card"><h3>Отдельная заметка</h3>' +
        '<form method="post" action="/notes" class="form" data-reload="/notes?added=1">' +
          '<input type="hidden" name="kind" value="standalone">' +
          '<label>Текст заметки<textarea name="text" rows="4" required placeholder="Своя мысль, конспект, вопрос к себе"></textarea></label>' +
          '<button class="btn btn-small" type="submit">Сохранить</button></form>' +
        '<p class="muted small">Заметка к абзацу создаётся на странице статьи: наведите на абзац и нажмите «＋» слева.</p></div>' +
      '<div class="notes-list">' + (hasNotes ? list : '<p class="empty">Заметок пока нет.</p>') + '</div>';
  }

  const body = '' +
    '<section class="wrap section narrow">' +
      '<div class="page-head"><h1>Мои заметки</h1>' +
        '<p class="lead">Заметки к абзацам и отдельные записи. Видит только автор. Сейчас открыты на уровне ' + FLAGS.notesMinLevel + '.</p></div>' +
      (query.added ? '<div class="notice notice-ok">Заметка сохранена.</div>' : '') +
      (query.error ? '<div class="notice">' + esc(query.error) + '</div>' : '') +
      inner +
    '</section>';

  return L.page({ title: 'Мои заметки', user: user, active: '/notes', back: '/notes', body: body });
}

// ── уровни ─────────────────────────────────────────────────────────────────
function levelsPage(user) {
  const cols = LEVELS.map(function (l) {
    return '<th class="' + (l.n === user.level ? 'is-me' : '') + '">' + l.n + ' · ' + esc(l.name) + (l.n === user.level ? '<div class="me-mark">вы здесь</div>' : '') + '</th>';
  }).join('');

  const rows = [
    ['Превью закрытых статей', ['да', 'да', 'да', 'да']],
    ['Открытые статьи целиком', ['да', 'да', 'да', 'да']],
    ['Все тексты статей', ['—', 'да', 'да', 'да']],
    ['Пометка «есть видео»', ['—', 'да', 'да', 'да']],
    ['Каталог видео', ['3 ролика', 'все', 'все', 'все']],
    ['Плеер внутри статьи', ['—', '—', 'да', 'да']],
    ['Панель связей и доп. поля', ['—', '—', 'да', 'да']],
    ['Заметки', ['—', '—', '—', '1000']],
    ['Экспорт заметок', ['да', 'да', 'да', 'да']],
    ['Подборки-курсы', ['—', 'список', 'список', 'все']],
    ['Эксклюзивные лекции', ['—', '—', '—', 'да']],
  ];

  const body = '' +
    '<section class="wrap section">' +
      '<div class="page-head"><h1>Уровни доступа</h1><p class="lead">Одна вложенная шкала: каждый следующий уровень включает предыдущий. Заметки пока открыты только на уровне 3 — это флаг запуска, а не свойство тарифа.</p></div>' +
      '<div class="table-wrap"><table class="tbl levels-tbl"><thead><tr><th>Что открывается</th>' + cols + '</tr></thead><tbody>' +
        rows.map(function (r) {
          return '<tr><td>' + esc(r[0]) + '</td>' + r[1].map(function (c, i) {
            const yes = c !== '—';
            return '<td class="' + (yes ? 'ok' : 'no') + (i === user.level ? ' is-me' : '') + '">' + esc(c) + '</td>';
          }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>' +
      '<div class="grid grid-3">' +
        '<div class="card"><h3>Уровень вычисляется</h3><p class="muted">Он не хранится отдельно: собирается из разрешений — покупка, промокод, фаза запуска, демо-переключение.</p></div>' +
        '<div class="card"><h3>Два вида доступа</h3><p class="muted">По уровню и точечный: конкретный объект открывается промокодом или компенсацией, независимо от тарифа.</p></div>' +
        '<div class="card"><h3>Закрытое не уезжает в браузер</h3><p class="muted">Проверка на сервере: в HTML нет текста, который вы не оплатили. Откройте исходный код закрытой статьи и убедитесь.</p></div>' +
      '</div>' +
    '</section>';

  return L.page({ title: 'Уровни', user: user, active: '/levels', back: '/levels', body: body });
}

// ── как устроено ───────────────────────────────────────────────────────────
function prototypePage(user) {
  const fs = require('fs');
  const path = require('path');
  const read = function (p) { return fs.readFileSync(path.join(__dirname, '..', p), 'utf8'); };
  const entSrc = read('lib/entitlements.js');
  const sessSrc = read('lib/session.js');
  const notesSrc = read('lib/notes.js');
  const exampleMd = read('content/articles/02-hod-bitvy.md');
  const fm = (exampleMd.match(/^---\r?\n([\s\S]*?)\r?\n---/) || [])[1] || '';

  const cut = function (src, from, to) {
    const i = src.indexOf(from);
    if (i < 0) return '';
    const j = to ? src.indexOf(to, i) : -1;
    return src.slice(i, j > 0 ? j : i + 900).trim();
  };

  const body = '' +
    '<section class="wrap section narrow">' +
      '<div class="page-head"><h1>Как это устроено</h1><p class="lead">Реальный код этого сайта. Три места, которые важно понять: разрешения, точка подключения оплаты и якоря заметок.</p></div>' +

      '<div class="card"><h2>1. Файлы</h2><pre class="code">site/\n  server.js              — маршруты\n  lib/pages.js           — страницы\n  lib/access.js          — матрица доступа и can()\n  lib/entitlements.js    — разрешения и фазы\n  lib/session.js         — кто пришёл; здесь подключается оплата\n  lib/notes.js           — заметки, квоты, якоря, экспорт\n  lib/store.js           — хранилище (JSON; заменится на базу данных)\n  content/articles/      — статьи в Markdown + снимки Wikidata\n  content/_templates/    — шаблоны для заполнения\n  data/state.json        — демо-данные: разрешения, покупки, заметки</pre></div>' +

      '<div class="card"><h2>2. Уровень вычисляется из разрешений</h2>' +
        '<p class="muted">Нигде в сайте не написано «у этого человека уровень 2, потому что он заплатил». Есть записи о разрешениях с источником и сроком, а уровень собирается из них.</p>' +
        '<pre class="code">' + esc(cut(entSrc, 'function resolve(record)', '// Создание разрешений')) + '</pre></div>' +

      '<div class="card"><h2>3. Где подключается оплата</h2>' +
        '<p class="muted">Сегодня эту функцию зовёт форма-заглушка. Завтра — обработчик события платёжного сервиса. Тело одно и то же.</p>' +
        '<pre class="code">' + esc(cut(sessSrc, 'function subscribeStub', 'function applyPromo')) + '</pre>' +
        '<p class="muted small">Всё остальное — страницы, проверка доступа, кабинет, заметки — при подключении оплаты не меняется.</p></div>' +

      '<div class="card"><h2>4. Якорь заметки</h2>' +
        '<p class="muted">Заметка к абзацу хранит цитату и номер блока. Если текст отредактировали, заметка не пропадает.</p>' +
        '<pre class="code">' + esc(cut(notesSrc, 'function anchorState', '// Экспорт')) + '</pre></div>' +

      '<div class="card"><h2>5. Шапка статьи</h2><pre class="code">---' + esc(fm) + '---</pre>' +
        '<p class="muted small"><code>type: entity</code> — статья о сущности, <code>id</code> совпадает с Wikidata. <code>body</code> и <code>extras</code> — точки доступа.</p></div>' +

      '<div class="card"><h2>6. Чего в прототипе нет</h2><ul class="link-list">' +
        '<li>настоящей оплаты — кнопки создают запись о покупке;</li>' +
        '<li>настоящих аккаунтов с паролем: идентификатор в cookie; в реальной версии — сессия на сервере;</li>' +
        '<li>базы данных: JSON-файл, спрятанный за модулем хранилища;</li>' +
        '<li>конспектов и курсов — только место в интерфейсе;</li>' +
        '<li>настоящих видео: чужие публичные ролики как заглушки.</li>' +
      '</ul></div>' +
    '</section>';

  return L.page({ title: 'Как устроено', user: user, active: '', back: '/prototype', body: body });
}

function notFoundPage(user) {
  const body = '<section class="wrap section narrow center"><h1>404</h1><p class="lead">Такой страницы нет.</p><p><a class="btn" href="/">На главную</a></p></section>';
  return L.page({ title: 'Не найдено', user: user, active: '', back: '/', body: body });
}

module.exports = {
  ARTICLES: ARTICLES, VIDEOS: VIDEOS, BY_ID: BY_ID, TARIFFS: TARIFFS, QA: QA,
  homePage: homePage, articlesPage: articlesPage, articlePage: articlePage,
  videosPage: videosPage, searchPage: searchPage, qaPage: qaPage,
  registerPage: registerPage, accountPage: accountPage, subscribePage: subscribePage,
  notesPage: notesPage, levelsPage: levelsPage, prototypePage: prototypePage,
  notFoundPage: notFoundPage, articleCard: articleCard,
};
