(() => {
  "use strict";
  const loader = document.currentScript;
  const baseURL = loader ? loader.src : window.location.href;
  const app = document.getElementById("app");

  function showError(message) {
    if (app) {
      app.innerHTML = `<section class="not-found"><span class="eyebrow">НЕ УДАЛОСЬ ЗАГРУЗИТЬ ДАННЫЕ</span><h1>Проверьте статические файлы сайта.</h1><p>${message}</p><p>Убедитесь, что рядом с index.html опубликован файл content-index.json.</p></section>`;
    }
  }

  fetch(new URL("./content-index.json", baseURL))
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      window.HISTORY_DATA = data;
      const script = document.createElement("script");
      script.src = new URL("./app.js", baseURL).href;
      script.onerror = () => showError("Не удалось загрузить интерфейс app.js.");
      document.head.appendChild(script);
    })
    .catch(error => {
      showError(`Не удалось прочитать content-index.json (${error.message}). Откройте проект через локальный веб-сервер, а не как file://.`);
    });
})();
