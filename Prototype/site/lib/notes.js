'use strict';
// Заметки: создание, квоты, проверка якоря, экспорт.
// Заметка хранит не «позицию в тексте», а цитату и номер блока — если статью
// отредактировали, заметка не теряется, а помечается как «фрагмент изменён».

const store = require('./store');
const md = require('./md');

function limitOf(view) {
  return view.notesLimit || 0;
}

function add(record, view, data) {
  const limit = limitOf(view);
  if (!limit) return { ok: false, error: 'Заметки недоступны на вашем уровне.' };
  if ((record.notes || []).length >= limit) {
    return { ok: false, error: 'Достигнут лимит заметок для вашего уровня: ' + limit + '.' };
  }
  const text = String(data.text || '').trim();
  if (!text) return { ok: false, error: 'Пустая заметка.' };

  const note = {
    id: store.nextId('N'),
    kind: data.kind === 'inline' ? 'inline' : 'standalone',
    articleId: data.articleId || null,
    block: data.block === undefined || data.block === null || data.block === '' ? null : Number(data.block),
    quote: String(data.quote || '').slice(0, 400),
    text: text.slice(0, 4000),
    createdAt: new Date().toISOString(),
    updatedAt: null,
  };
  record.notes.push(note);
  store.save();
  return { ok: true, note: note };
}

function remove(record, id) {
  const before = record.notes.length;
  record.notes = record.notes.filter(function (n) { return n.id !== id; });
  store.save();
  return record.notes.length < before;
}

// Проверка якоря: находим блок по номеру и смотрим, сохранилась ли цитата.
function anchorState(note, article) {
  if (note.kind !== 'inline' || !article) return 'ok';
  const blocks = md.blocks(article.markdown);
  const raw = blocks[note.block];
  if (raw === undefined) return 'lost';
  const text = md.blockText(raw);
  if (!note.quote) return 'ok';
  const needle = note.quote.trim().slice(0, 60);
  return text.indexOf(needle) >= 0 ? 'ok' : 'changed';
}

// Экспорт: обычный Markdown, чтобы файл открывался где угодно.
function exportMarkdown(record, articlesById) {
  const notes = record.notes || [];
  const byArticle = {};
  const standalone = [];
  notes.forEach(function (n) {
    if (n.kind === 'inline' && n.articleId) (byArticle[n.articleId] = byArticle[n.articleId] || []).push(n);
    else standalone.push(n);
  });

  const lines = [];
  lines.push('# Мои заметки');
  lines.push('');
  lines.push('Выгружено: ' + new Date().toISOString().slice(0, 10) + ' · всего заметок: ' + notes.length);
  lines.push('');

  Object.keys(byArticle).forEach(function (aid) {
    const a = articlesById[aid];
    lines.push('## ' + (a ? a.title : aid));
    lines.push('');
    byArticle[aid].forEach(function (n) {
      lines.push('> ' + (n.quote ? n.quote.replace(/\n/g, ' ') : 'заметка к статье'));
      lines.push('');
      lines.push(n.text);
      lines.push('');
      lines.push('_' + n.createdAt.slice(0, 16).replace('T', ' ') + ' · ' + n.id + '_');
      lines.push('');
    });
  });

  if (standalone.length) {
    lines.push('## Отдельные заметки');
    lines.push('');
    standalone.forEach(function (n) {
      lines.push('### ' + n.text.split('\n')[0].slice(0, 80));
      lines.push('');
      if (n.text.indexOf('\n') > 0) { lines.push(n.text.split('\n').slice(1).join('\n')); lines.push(''); }
      lines.push('_' + n.createdAt.slice(0, 16).replace('T', ' ') + ' · ' + n.id + '_');
      lines.push('');
    });
  }

  if (!notes.length) lines.push('Заметок пока нет.');
  return lines.join('\n');
}

module.exports = { add, remove, anchorState, exportMarkdown, limitOf };
