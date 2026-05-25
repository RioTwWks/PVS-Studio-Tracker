---
name: add-htmx-filter
description: >-
  Adds or extends HTMX issue filters on the PVS-Studio Tracker dashboard
  (severity, status, search, classifier). Use when adding UI filters,
  pagination query params, issues table HTMX, or /ui/issues changes.
---

# Add HTMX Issue Filter

Parent skill: [pvs-tracker-dev](../pvs-tracker-dev/SKILL.md). Rules: [.cursor/rules.md](../../rules.md) §4.

## Goal

Add a filter control that updates **only** the issues table via HTMX — Chart.js and the rest of the dashboard must not reload.

## Files (typical)

| File | Role |
|------|------|
| `pvs_tracker/templates/dashboard/_issues_tab.html` | Filter form → `#issues-table-full` |
| `pvs_tracker/templates/issues_table.html` | Full table fragment; sort links + pagination |
| `pvs_tracker/templates/partials/issues_rows.html` | Infinite-scroll / page-2+ rows (`fragment=true`) |
| `pvs_tracker/main.py` | `GET /ui/issues` — query params + SQL filters |

## Workflow

```
Task Progress:
- [ ] Add query param name in main.py ui_issues (filter + total_query)
- [ ] Add form control in _issues_tab.html (name= must match param)
- [ ] Thread param through issues_table.html (sort headers, pagination)
- [ ] Thread param through issues_rows.html (hx-get load-more)
- [ ] Preserve selected value in <select> / <input> after HTMX swap
- [ ] Test with fetch MCP or pytest client
```

## HTMX contract

- Form: `hx-get="/ui/issues"` → `hx-target="#issues-table-full"` → `hx-swap="innerHTML"`.
- Hidden fields: always include `project_id`, `branch` (from `active_branch`).
- Fragment response: first load returns `issues_table.html`; `fragment=true` returns `partials/issues_rows.html` only.
- **Never** return `<!DOCTYPE>`, `<html>`, `<head>` from `/ui/issues`.

## Query param checklist

When adding param `foo`, update **every** URL builder:

1. `_issues_tab.html` — form field + hidden inputs if needed
2. `issues_table.html` — column sort `hx-get` links
3. `issues_table.html` — "load more" / next page button
4. `partials/issues_rows.html` — pagination `hx-get`
5. `main.py` — `issues_query` **and** `total_query` (keep filters in sync)

Use `|urlencode` for string params in Jinja: `&foo={{ foo|urlencode }}`.

## Existing params (reference)

`project_id`, `branch`, `severity`, `status_filter`, `q`, `page`, `sort_by`, `order`, `fragment`

Default status when `status_filter` empty: `new` + `existing` (not `fixed`).

## Backend pattern

```python
if new_filter:
    issues_query = issues_query.where(Issue.field == new_filter)
    total_query = total_query.where(Issue.field == new_filter)
```

Use `Depends(get_session)`; `/ui/issues` is behind session auth like other `/ui/*` routes.

## Do not

- Re-init Chart.js or reload dashboard chart on filter apply.
- Return JSON from UI filter endpoints.
- Drop existing params from pagination/sort links.
- Break inline Code rows in `partials/issue_row.html` (open state lives in DOM; full table swap closes panels — acceptable).

## Related (not this skill)

- CI toggles / toast: `project_manage.py`, `dashboard/_ci_actions.html`, `app.js` (`showToast`, `sq-toast`).
- Inline code animation: `app.js` + `style.css` (`sq-codeReveal` / `sq-codeHide`).

## Verification

```bash
pytest tests/test_smoke.py -k "issues" -v
```

Manual (fetch MCP): `GET /ui/issues?project_id=1&severity=High` — response is HTML table with `hx-get` links containing `severity=High`.

End with:

```text
✅ Файл готов. Запусти: pytest tests/test_smoke.py -k issues -v
Ожидаемый результат: фильтр меняет таблицу без перезагрузки графика; пагинация сохраняет query params.
```
