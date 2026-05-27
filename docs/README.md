# Документация PVS-Studio Tracker

Указатель по темам. Точка входа в репозитории: [README](../README.md).  
Для агентов Cursor: [CURSOR.md](../CURSOR.md) и [.cursor/spec.md](../.cursor/spec.md).

## С чего начать

| Документ | Аудитория | Содержание |
|----------|-----------|------------|
| [quick-reference.md](quick-reference.md) | Разработчики, DevOps | Команды curl/PowerShell, API v1/v2, типовые сценарии |
| [jenkins-ci.md](jenkins-ci.md) | CI/CD | Jenkins, TFS webhook, upload, `.meta.json`, Jira assignee |
| [inline-code-viewer.md](inline-code-viewer.md) | Разработчики UI | Git / archive / filesystem, inline Code на Issues |

## Справочники по функциям

| Тема | Где читать |
|------|------------|
| Аутентификация (local + LDAP) | [quick-reference.md § Аутентификация](quick-reference.md#-аутентификация), `.env.example` |
| Загрузка отчётов и метаданные коммита | [jenkins-ci.md § Метаданные коммита](jenkins-ci.md#метаданные-коммита-metajson), [quick-reference.md § Загрузка](quick-reference.md#-загрузка-отчётов) |
| Quality gates (rule codes) | [quick-reference.md § Quality Gates](quick-reference.md#-quality-gates-rule-codes) |
| Просмотр кода | [inline-code-viewer.md](inline-code-viewer.md) |
| Email / webhooks | [quick-reference.md](quick-reference.md#-email-smtp) |

## Архив и история

| Документ | Примечание |
|----------|------------|
| [v0.2-transformation.md](v0.2-transformation.md) | Заметки о переходе на v0.2; часть про metric-based QG устарела — см. `QualityGateRule` в коде |

## Вне этой папки

- **README.md** (корень) — обзор продукта, установка, возможности
- **CURSOR.md** — краткий гид для Cursor (не переносится в `docs/`)
- **`.cursor/`** — правила и skills для агентов
- **`PVS_Sonar_WebHook_FastAPI/`** — устаревший standalone; только для миграции
