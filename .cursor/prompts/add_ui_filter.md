> Skill: `@add-htmx-filter` — see [.cursor/skills/add-htmx-filter/SKILL.md](../skills/add-htmx-filter/SKILL.md)

Добавь фильтр в `dashboard/_issues_tab.html` и `issues_table.html` (+ `partials/issues_rows.html` для пагинации).
- Используй HTMX hx-get с сохранением query params
- Обнови пагинацию, чтобы фильтры передавались на следующие страницы
- Не перезагружай Chart.js, только таблицу
- Протестируй через fetch MCP
