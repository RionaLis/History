// Минимальный markdown-рендерер без внешних зависимостей.
// Понимает подмножество, которым пользуется Obsidian: заголовки, списки,
// таблицы, цитаты, код, ссылки, [[вики-ссылки]], изображения.

export function stripFrontmatter(text) {
  if (!text.startsWith('---')) return { meta: {}, body: text };
  const end = text.indexOf('\n---', 3);
  if (end === -1) return { meta: {}, body: text };
  const raw = text.slice(3, end);
  const body = text.slice(end + 4).replace(/^\n+/, '');
  const meta = {};
  for (const line of raw.split('\n')) {
    const m = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    if (!m) continue;
    let v = m[2].trim();
    try { v = JSON.parse(v); } catch (_) { v = v.replace(/^["']|["']$/g, ''); }
    meta[m[1]] = v;
  }
  return { meta, body };
}

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function inline(s) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, a, u) => `<img alt="${a}" src="${u}">`);
  t = t.replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g,
    (_, p, a) => `<a class="wikilink" data-wiki="${p.trim()}" href="#">${a}</a>`);
  t = t.replace(/\[\[([^\]]+)\]\]/g,
    (_, p) => `<a class="wikilink" data-wiki="${p.trim()}" href="#">${p}</a>`);
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, a, u) =>
    `<a href="${u}"${/^https?:/.test(u) ? ' target="_blank" rel="noopener"' : ''}>${a}</a>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|\W)\*([^*\n]+)\*/g, '$1<em>$2</em>');
  t = t.replace(/(^|\W)_([^_\n]+)_/g, '$1<em>$2</em>');
  t = t.replace(/==([^=]+)==/g, '<mark>$1</mark>');
  return t;
}

export function renderMarkdown(src) {
  const lines = src.replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  const flushTable = (rows) => {
    if (rows.length < 2) { rows.forEach(r => out.push(`<p>${inline(r)}</p>`)); return; }
    const cells = r => r.replace(/^\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
    const head = cells(rows[0]);
    const body = rows.slice(2).map(cells);
    const isEmptyHead = head.every(h => h === '');
    let html = '<table>';
    if (!isEmptyHead) {
      html += '<thead><tr>' + head.map(h => `<th>${inline(h)}</th>`).join('') + '</tr></thead>';
    }
    html += '<tbody>' + body.map(r =>
      '<tr>' + r.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
    out.push(html);
  };

  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^```/.test(line)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++].trim());
      flushTable(rows);
      continue;
    }
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${renderMarkdown(buf.join('\n'))}</blockquote>`);
      continue;
    }
    if (/^\s*([-*+])\s+/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*([-*+])\s+/.test(lines[i])) {
        buf.push(lines[i++].replace(/^\s*([-*+])\s+/, ''));
      }
      out.push('<ul>' + buf.map(b => `<li>${inline(b)}</li>`).join('') + '</ul>');
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        buf.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''));
      }
      out.push('<ol>' + buf.map(b => `<li>${inline(b)}</li>`).join('') + '</ol>');
      continue;
    }
    const buf = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|\s*>|\s*\||```)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    out.push(`<p>${inline(buf.join(' '))}</p>`);
  }
  return out.join('\n');
}
