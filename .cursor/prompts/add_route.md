> Skill: `@add-api-route` — see [.cursor/skills/add-api-route/SKILL.md](../skills/add-api-route/SKILL.md)

Добавь новый endpoint по спецификации из spec.md.

- **v2 REST** → `pvs_tracker/api.py`, Pydantic + `Depends(require_auth)`, RBAC
- **v1 / UI** → `pvs_tracker/main.py`, `Depends(get_session)`, session `require_auth` для мутаций
- Логирование через `logger`
- Не ломай существующие роуты
- В конце: curl-команда и ожидаемый HTTP-статус
