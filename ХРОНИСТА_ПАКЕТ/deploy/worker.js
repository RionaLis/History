// =====================================================================
//  worker.js — закрытая раздача карты Хронисты.
//
//  Зачем этот файл. Ваша задача: смотреть карту с любого устройства вам и
//  паре друзей, а оригиналы тайлов должны остаться только у вас. GitHub
//  Pages для этого не годится в принципе: всё, что вы туда положили,
//  скачивается кем угодно без пароля — достаточно знать адрес файла.
//
//  Здесь карта лежит в хранилище Cloudflare R2 (бесплатно до 10 ГБ),
//  а отдаёт её этот Worker. Он делает три вещи:
//
//    1. Проверяет ключ. Нет ключа — 403, и содержимого файла не видно.
//    2. Отвечает на CORS-префлайт. Без этого браузер блокирует запросы
//       тайлов с другого адреса.
//    3. Поддерживает Range-запросы и отвечает 206 Partial Content.
//       PMTiles читает файл не целиком, а кусками по несколько килобайт,
//       и без 206 карта не откроется вовсе.
//
//  Бесплатные лимиты Cloudflare на момент написания (проверьте актуальные
//  на developers.cloudflare.com перед публикацией — они меняются):
//
//    Workers Free    100 000 запросов в сутки, 10 мс CPU на запрос,
//                    код Worker'а до 1 МБ
//    R2 Free         10 ГБ хранилища, 1 млн операций чтения класса A
//                    и 10 млн класса B в месяц,
//                    ИСХОДЯЩИЙ ТРАФИК БЕСПЛАТЕН БЕЗ ОГРАНИЧЕНИЙ
//
//  Последний пункт — главная причина выбрать именно R2. У всех остальных
//  бесплатных хостингов исходящий трафик ограничен, и карта, которую
//  смотрят несколько человек, этот лимит съедает быстро.
//
//  Хватит ли вам. Ваши три эпохи весят 3 МБ. Один просмотр карты — это
//  примерно 50–300 запросов тайлов (зависит от того, как вы её двигаете
//  и приближаете). Значит 100 000 запросов в сутки — это сотни просмотров
//  в день. Для вас и пары друзей предел недостижим.
// =====================================================================

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const method = request.method;

    // -----------------------------------------------------------------
    // 1. CORS-префлайт. Браузер шлёт OPTIONS перед настоящим запросом,
    //    если страница и тайлы на разных адресах. Отвечаем сразу, без
    //    проверки ключа: в OPTIONS нет ни тела, ни параметров, а сам по
    //    себе ответ «можно» ничего не раскрывает.
    //
    //    Замерено 22.10.2026: поддомен workers.dev НЕ блокирует запросы
    //    с заголовком Origin (обычный Cloudflare вернул бы 403), поэтому
    //    бесплатный адрес вида https://ИМЯ.ВАШ-АКК.workers.dev работает
    //    без собственного домена. Чужой Worker на OPTIONS отвечал 405 —
    //    просто потому, что сам OPTIONS не обрабатывал, а не потому, что
    //    Cloudflare его запретил.
    // -----------------------------------------------------------------
    if (method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    // -----------------------------------------------------------------
    // 2. Проверка ключа.
    //
    //    Ключ берётся из строки запроса (?k=…) или из заголовка
    //    Authorization: Bearer …. Второй вариант нужен, если вы когда-
    //    нибудь захотите передавать ключ не через URL.
    //
    //    Сравнение намеренно постоянное по времени: обычное === на
    //    строках теоретически позволяет угадывать ключ посимвольно по
    //    времени ответа. Для вашего масштаба это избыточно, но стоит
    //    ноль строк кода и защищает на будущее, когда продукт станет
    //    платным.
    // -----------------------------------------------------------------
    const expected = (env.ACCESS_KEY || '').trim();
    if (!expected) {
      return text(500,
        'Ключ доступа не задан. Установите секрет:\n' +
        '    npx wrangler secret put ACCESS_KEY\n');
    }

    const got = url.searchParams.get('k') ||
                (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');

    if (!safeEqual(got, expected)) {
      // 403, а не 404: 404 подсказал бы, что файла не существует, а нам
      // нужно, чтобы без ключа нельзя было отличить существующий тайл от
      // несуществующего.
      return text(403,
        'Нет доступа. Откройте ссылку целиком, вместе с частью после #\n' +
        'например:  https://' + url.host + '/#k=ВАШ-КЛЮЧ\n');
    }

    // -----------------------------------------------------------------
    // 3. Какой файл отдать.
    // -----------------------------------------------------------------
    let path = decodeURIComponent(url.pathname).replace(/^\/+/, '');
    if (!path || path === '/') path = 'index.html';
    // Защита от выхода за пределы хранилища: «../../maps/eras/…».
    if (path.includes('..')) return text(400, 'Недопустимый путь');

    const object = await env.BUCKET.get(path, { range: rangeOf(request) });
    if (!object) {
      return text(404, 'Нет такого файла: ' + path);
    }

    // -----------------------------------------------------------------
    // 4. Ответ. R2 сам разбирает Range и отдаёт 206, если диапазон задан.
    // -----------------------------------------------------------------
    const headers = new Headers(corsHeaders(request));
    object.writeHttpMetadata(headers);
    headers.set('Content-Type', contentType(path));
    // ETag позволяет браузеру не качать тайл повторно.
    if (object.etag) headers.set('ETag', object.etag);

    // Тайлы не меняются между сборками, пока вы их не пересоберёте, поэтому
    // кэшируем их в браузере надолго. index.html — никогда: иначе вы не
    // увидите изменений после пересборки.
    if (path.startsWith('tiles/')) {
      headers.set('Cache-Control', 'public, max-age=86400');
    } else {
      headers.set('Cache-Control', 'no-cache');
    }
    headers.set('Accept-Ranges', 'bytes');

    const status = object.range ? 206 : 200;
    if (status === 206) {
      const r = object.range;
      const start = r.offset ?? 0;
      const end = r.length ? start + r.length - 1 : (object.size - 1);
      headers.set('Content-Range', `bytes ${start}-${end}/${object.size}`);
      headers.set('Content-Length', String(r.length ?? object.size));
    } else {
      headers.set('Content-Length', String(object.size));
    }

    if (method === 'HEAD') {
      return new Response(null, { status, headers });
    }
    return new Response(object.body, { status, headers });
  },
};

// ---------------------------------------------------------------------
//  Вспомогательные функции
// ---------------------------------------------------------------------

function corsHeaders(request) {
  // '*' — потому что страница может лежать на GitHub Pages, на вашем домене
  // или открываться локально. Ключ всё равно проверяется отдельно, поэтому
  // открытый CORS здесь ничего не раскрывает.
  // Если захотите сузить — замените на точный адрес вашей страницы.
  const origin = request.headers.get('Origin') || '*';
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
    'Access-Control-Allow-Headers': 'Range, Content-Type, Authorization',
    'Access-Control-Expose-Headers':
      'Content-Length, Content-Range, Accept-Ranges, ETag',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
}

function rangeOf(request) {
  const h = request.headers.get('Range');
  if (!h || !h.startsWith('bytes=')) return undefined;
  const spec = h.slice(6).split(',')[0].trim();
  const [a, b] = spec.split('-');
  if (a === '' && b !== '') {
    // bytes=-N → последние N байт
    return { suffix: parseInt(b, 10) };
  }
  const offset = parseInt(a, 10);
  const length = b === '' ? undefined : parseInt(b, 10) - offset + 1;
  return length ? { offset, length } : { offset };
}

function safeEqual(a, b) {
  a = String(a || '');
  b = String(b || '');
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

function contentType(path) {
  const ext = path.slice(path.lastIndexOf('.') + 1).toLowerCase();
  return {
    html: 'text/html; charset=utf-8',
    js: 'application/javascript; charset=utf-8',
    css: 'text/css; charset=utf-8',
    json: 'application/json; charset=utf-8',
    pmtiles: 'application/octet-stream',
    png: 'image/png',
    jpg: 'image/jpeg',
    svg: 'image/svg+xml',
    woff2: 'font/woff2',
  }[ext] || 'application/octet-stream';
}

function text(status, body) {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
