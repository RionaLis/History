'use strict';
// Чтение контента: Markdown-файлы статей, снимки Wikidata, JSON со видео и вопросами.
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'content');
const ARTICLES_DIR = path.join(DIR, 'articles');

function parseFrontmatter(raw) {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!m) return { data: {}, body: raw };
  const data = {};
  m[1].split(/\r?\n/).forEach(function (line) {
    const i = line.indexOf(':');
    if (i < 0) return;
    const key = line.slice(0, i).trim();
    let val = line.slice(i + 1).trim();
    if (/^-?\d+$/.test(val)) val = Number(val);
    else if (val === 'true') val = true;
    else if (val === 'false') val = false;
    else if (val === 'null' || val === '') val = null;
    data[key] = val;
  });
  return { data: data, body: raw.slice(m[0].length) };
}

function loadArticles() {
  return fs.readdirSync(ARTICLES_DIR)
    .filter(function (f) { return f.endsWith('.md'); })
    .map(function (f) {
      const raw = fs.readFileSync(path.join(ARTICLES_DIR, f), 'utf8');
      const parsed = parseFrontmatter(raw);
      const d = parsed.data;

      // Снимок Wikidata лежит рядом со статьёй: <имя файла>.wikidata.json
      let snapshot = null;
      const snapPath = path.join(ARTICLES_DIR, f.replace(/\.md$/, '.wikidata.json'));
      if (fs.existsSync(snapPath)) {
        try { snapshot = JSON.parse(fs.readFileSync(snapPath, 'utf8')); } catch (e) { snapshot = null; }
      }

      return {
        id: d.id || f.replace(/\.md$/, ''),
        file: f,
        order: d.order === undefined || d.order === null ? 999 : d.order,
        type: d.type || 'authorial', // entity — статья о сущности, authorial — авторская
        wikidata: d.wikidata || null,
        snapshot: snapshot,
        title: d.title || 'Без названия',
        topic: d.topic || 'Без темы',
        summary: d.summary || '',
        preview: d.preview || '',
        tags: typeof d.tags === 'string' ? d.tags.split(',').map(function (t) { return t.trim(); }) : [],
        bodyLevel: typeof d.body === 'number' ? d.body : 1,
        extrasLevel: typeof d.extras === 'number' ? d.extras : 2,
        videoHintLevel: typeof d.video_hint === 'number' ? d.video_hint : 1,
        video: d.video || null,
        publishedAt: d.published_at || null,
        updated: d.updated || '',
        markdown: parsed.body,
      };
    })
    .sort(function (a, b) {
      if (a.order !== b.order) return a.order - b.order;
      return a.title.localeCompare(b.title, 'ru');
    });
}

function loadVideos() {
  return JSON.parse(fs.readFileSync(path.join(DIR, 'videos.json'), 'utf8'));
}

function loadQA() {
  return JSON.parse(fs.readFileSync(path.join(DIR, 'qa.json'), 'utf8'));
}

// ── Поиск ──────────────────────────────────────────────────────────────────
function norm(s) { return String(s).toLowerCase().replace(/ё/g, 'е'); }
function tokens(s) { return norm(s).split(/[^\p{L}\p{N}]+/u).filter(Boolean); }

function scoreField(text, queryTokens, weight) {
  const hay = tokens(text);
  let score = 0;
  for (const q of queryTokens) {
    for (const w of hay) {
      if (w === q) score += weight * 2;
      else if (w.startsWith(q) && q.length >= 3) score += weight;
    }
  }
  return score;
}

function searchArticles(articles, query) {
  const q = tokens(query);
  if (!q.length) return [];
  const scored = articles.map(function (a) {
    let s = 0;
    s += scoreField(a.title, q, 6);
    s += scoreField(a.summary + ' ' + a.preview, q, 3);
    s += scoreField(a.tags.join(' '), q, 3);
    s += scoreField(a.topic, q, 2);
    s += scoreField(a.markdown, q, 1);
    return { item: a, score: s };
  }).filter(function (r) { return r.score > 0; });
  scored.sort(function (a, b) { return b.score - a.score; });
  return scored.map(function (r) { return r.item; });
}

function searchVideos(videos, query) {
  const q = tokens(query);
  if (!q.length) return [];
  const scored = videos.map(function (v) {
    let s = 0;
    s += scoreField(v.title, q, 6);
    s += scoreField(v.topic, q, 3);
    return { item: v, score: s };
  }).filter(function (r) { return r.score > 0; });
  scored.sort(function (a, b) { return b.score - a.score; });
  return scored.map(function (r) { return r.item; });
}

module.exports = { loadArticles, loadVideos, loadQA, searchArticles, searchVideos, ARTICLES_DIR };
