# База заметок Adam's History

Откройте эту папку как Obsidian vault. Основные заметки содержат YAML frontmatter между `---` и Markdown-текст после закрывающей строки.

- `events/states`, `events/science`, `events/arts` — события и открытия;
- `people` — биографии персон;
- `rulers` — записи о правителях;
- `tracks/states`, `tracks/science`, `tracks/arts`, `tracks/rulers` — линии временной карты;
- `eras` — статьи об эпохах;
- `settings.md` — диапазон дат, порядок регионов, группы и палитра персон;
- `templates` — шаблоны заметок Obsidian.

После изменений запустите из корня проекта `python3 scripts/build_content.py`. Шаблоны исключены из генерации автоматически. Сохраните в Git исходные заметки и полученный `content-index.json`.

См. подробную инструкцию в корневом `README.md`.
