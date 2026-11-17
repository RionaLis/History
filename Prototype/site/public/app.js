// 1. Плеер загружается только по нажатию: до этого сторонние cookie не ставятся.
// 2. Кнопка «＋» у абзаца открывает форму заметки и подставляет выделенный текст.
// 3. Отправка форм идёт через fetch: в песочнице предпросмотра обычная отправка
//    формы блокируется, а обновление состояния — нет.

function currentUid() {
  var meta = document.querySelector('meta[name="u"]');
  var fromMeta = meta ? meta.getAttribute('content') : '';
  if (fromMeta) return fromMeta;
  var m = String(location.search).match(/[?&]u=([a-f0-9]{16})/);
  return m ? m[1] : '';
}

function withUid(url) {
  var uid = currentUid();
  if (!uid || /[?&]u=/.test(url)) return url;
  return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'u=' + uid;
}

document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!form || form.dataset.native === '1') return;
  e.preventDefault();

  var data = new URLSearchParams();
  new FormData(form).forEach(function (value, key) { data.append(key, value); });
  if (e.submitter && e.submitter.name) data.append(e.submitter.name, e.submitter.value);

  var action = withUid(form.getAttribute('action') || location.pathname);
  var target = form.dataset.reload || (location.pathname + location.search);

  function done() { location.href = withUid(target); }
  function fallback() { form.dataset.native = '1'; form.submit(); }

  try {
    fetch(action, { method: 'POST', body: data, mode: 'no-cors', credentials: 'include' })
      .then(done, fallback);
  } catch (err) {
    fallback();
  }
});

document.addEventListener('click', function (e) {
  var player = e.target.closest('[data-player]');
  if (player) {
    var wrap = player.closest('.player');
    if (wrap && wrap.dataset.embed) {
      var frame = document.createElement('iframe');
      frame.src = wrap.dataset.embed;
      frame.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture');
      frame.setAttribute('allowfullscreen', '');
      frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      wrap.innerHTML = '';
      wrap.appendChild(frame);
    }
    return;
  }

  var add = e.target.closest('.note-add');
  if (add) {
    var block = add.closest('.blk');
    var quote = '';
    var sel = window.getSelection ? window.getSelection() : null;
    if (sel && String(sel).trim() && block && sel.anchorNode) {
      var node = sel.anchorNode.nodeType === 3 ? sel.anchorNode.parentNode : sel.anchorNode;
      if (block.contains(node)) quote = String(sel).trim().slice(0, 300);
    }
    openNoteForm(add.dataset.article, add.dataset.block, quote);
    return;
  }

  if (e.target.classList && (e.target.classList.contains('modal') || e.target.classList.contains('modal-cancel'))) {
    closeNoteForm();
  }
});

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeNoteForm();
});

function closeNoteForm() {
  var el = document.getElementById('note-modal');
  if (el) el.remove();
}

function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function openNoteForm(articleId, blockIndex, quote) {
  closeNoteForm();
  var modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'note-modal';
  modal.innerHTML =
    '<div class="modal-box">' +
      '<h3>Заметка к абзацу</h3>' +
      '<form method="post" action="' + esc(withUid('/notes')) + '" class="form">' +
        '<input type="hidden" name="kind" value="inline">' +
        '<input type="hidden" name="article" value="' + esc(articleId) + '">' +
        '<input type="hidden" name="block" value="' + esc(blockIndex) + '">' +
        '<label>Цитата из текста<input type="text" name="quote" value="' + esc(quote) + '" placeholder="выделите текст в абзаце или впишите вручную"></label>' +
        '<label>Заметка<textarea name="text" rows="5" required autofocus placeholder="Своя мысль, вопрос, ссылка"></textarea></label>' +
        '<div class="modal-actions">' +
          '<button class="btn btn-small" type="submit">Сохранить</button>' +
          '<button class="btn btn-ghost btn-small modal-cancel" type="button">Отмена</button>' +
        '</div>' +
        '<p class="muted small">Заметку видите только вы. Если абзац позже отредактируют, заметка не пропадёт — появится пометка «фрагмент изменён».</p>' +
      '</form>' +
    '</div>';
  document.body.appendChild(modal);
  var ta = modal.querySelector('textarea');
  if (ta) ta.focus();
}
