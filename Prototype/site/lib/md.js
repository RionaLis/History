'use strict';
// Маленький рендерер Markdown без зависимостей.
// Каждый блок оборачивается в <div class="blk" data-b="N">, чтобы к нему можно
// было привязать заметку: номер блока — это якорь заметки.

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function inline(s) {
  return escapeHtml(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, function (_m, target, label) {
      return '<a href="/article/by-title/' + encodeURIComponent(target.trim()) + '">' + (label || target) + '</a>';
    })
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
}

// Разбор на блоки — используется и при выводе, и при проверке якорей заметок.
function blocks(markdown) {
  return String(markdown).trim().split(/\n\s*\n/).map(function (b) { return b.trim(); }).filter(Boolean);
}

// Текст блока без разметки — нужен, чтобы понять, изменился ли абзац,
// к которому была привязана заметка.
function blockText(block) {
  return String(block)
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/^-\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, function (_m, a, b) { return b || a; })
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/`/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function renderBlock(b, i) {
  if (b === '---') return '<hr>';
  if (b.startsWith('### ')) { const t = b.slice(4).trim(); return '<h3 id="' + slug(t) + '">' + inline(t) + '</h3>'; }
  if (b.startsWith('## ')) { const t = b.slice(3).trim(); return '<h2 id="' + slug(t) + '">' + inline(t) + '</h2>'; }
  if (b.startsWith('> ')) {
    const body = b.split('\n').map(function (l) { return l.replace(/^>\s?/, ''); }).join(' ');
    return '<blockquote>' + inline(body) + '</blockquote>';
  }
  if (/^-\s/.test(b)) {
    const items = b.split('\n').filter(function (l) { return /^-\s/.test(l); })
      .map(function (l) { return '<li>' + inline(l.replace(/^-\s+/, '')) + '</li>'; });
    return '<ul>' + items.join('') + '</ul>';
  }
  return '<p>' + inline(b.replace(/\n/g, ' ')) + '</p>';
}

// opts.notes — сюда передаётся функция-обработчик кнопки «заметка»,
// либо null, если заметки недоступны.
function render(markdown, opts) {
  opts = opts || {};
  const withNotes = typeof opts.noteButton === 'function';
  return blocks(markdown).map(function (b, i) {
    const btn = withNotes ? opts.noteButton(i) : '';
    return '<div class="blk" data-b="' + i + '">' + renderBlock(b, i) + btn + '</div>';
  }).join('\n');
}

// Оглавление: заголовки видны всем, даже когда текст закрыт.
function outline(markdown) {
  const res = [];
  const re = /^##\s+(.+)$/gm;
  const src = String(markdown);
  let m;
  while ((m = re.exec(src)) !== null) res.push(m[1].trim());
  return res;
}

module.exports = { render, outline, blocks, blockText, escapeHtml, inline, slug };
