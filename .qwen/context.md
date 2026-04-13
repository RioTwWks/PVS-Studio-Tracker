# 🏗 PVS-Tracker: Контекст проекта

## 🎯 Зачем существует
SonarQube не поддерживает инкрементальные отчёты PVS-Studio. Мы делаем легковесный сервис, который:
- Принимает JSON-отчёты из CI
- Считает `new / fixed / existing` между запусками
- Показывает тренды и таблицы с фильтрами через HTMX
- Авторизует через корпоративный LDAP
- Работает как нативная служба (без Docker)

## 🗺 Архитектура (Mermaid)
```mermaid
graph TD
  Browser[Browser UI] -->|POST /ui/upload (form)| API[FastAPI]
  CI[CI/CD Pipeline] -->|POST /api/v1/upload (JSON)| API[FastAPI]
  API -->|UI: redirect 303| Dashboard[/ui/projects/{id}/dashboard]
  API -->|API: JSON| JSONResponse[API Response]
  API --> Parser[parser.py]
  API --> Classifier[classifier_parser.py]
  API --> DB[(SQLite/PostgreSQL)]
  Parser --> Diff[incremental.py]
  Classifier --> DB[(ErrorClassifier Table)]
  Diff --> DB
  DB --> UI[Jinja2+HTMX]
  API --> Webhook[httpx BackgroundTasks]
  Webhook --> External[Telegram/CI/Slack]
  UI --> Chart[Chart.js]
  UI --> i18n[I18n RU/EN]
  UI --> Theme[Dark Blue Theme]
  UI --> ClassifierInfo[Classifier Badges]
```

## ⚖️ Ключевые решения и почему
| Решение | Альтернатива | Причина |
|---------|--------------|---------|
| SQLite → Postgres | MySQL/Mongo | Простота старта, SQLModel-совместимость, ACID |
| BackgroundTasks вместо Redis | Celery/RQ | Нет распределённой очереди, отчёты < 1 мин |
| Фингерпринт: `file:line:code:msg` | Только `file:line` | PVS генерирует разные правила для одной строки |
| HTMX вместо React/SPA | Vue/Svelte | Быстрая разработка, сервер-рендеринг, минимум JS |
| Нативная служба | Docker | Корпоративный policy, нет Docker в продакшене |
| Dark blue theme | Black/gray dark | Более приятный глазу, профессиональный вид |
| Client-side i18n | Server-side locale | Без перезагрузки, один JSON, простой toggle |
| **Dual upload endpoints** | Один endpoint | UI получает redirect, API получает JSON — разделение Concerns |
| **UI upload → redirect 303** | Возврат JSON из формы | Правильный UX: пользователь видит дашборд, а не JSON |
| **Synthetic paths для analysis warnings** | Пропускать warnings без файла | V010 и подобные получают `__analysis__/{code}`, чтобы отслеживались |
| **Fixed в ПРЕДЫДУЩЕМ run** | Fixed в текущем run | При исчезновении fingerprint'а, статус "fixed" ставится на issue предыдущего run |
| **Default filter = new+existing** | Default filter = existing | При первой загрузке все issues "new", фильтр должен их показывать |
| **График: chronological order** | Newest first | Trend chart показывает oldest → newest для визуализации тренда |
| **Error Classifier из CSV** | Хардкод в коде | Гибкое обновление правил без изменения кода, 416 правил из Actual_warnings.csv |
| **Автозагрузка classifiers** | Ручной импорт | Удобство, автоматически при старте приложения |

## 🎨 Frontend
- **CSS**: `static/style.css` — CSS custom properties, тёмно-синяя палитра (`#0b1a2e`, `#0f2240`, `#142d50`), smooth transitions
- **JS**: `static/app.js` — `ThemeManager` (light/dark), `I18n` (RU/EN toggle), `createTrendChart` (Chart.js wrapper), `showToast`, animated counters
- **Translations**: `static/translations.json` — словарь ru/en, ключи через `data-i18n` / `data-i18n-placeholder`
- **Icons**: Bootstrap Icons CDN (`bi bi-*`)
- **Таблицы в dark mode**: `[data-theme="dark"] .card .table { ... !important }` — принудительно перебивает белый фон Bootstrap

## ⚠️ Известные нюансы PVS-Studio
1. **Два формата JSON**: Современный формат использует `positions[].file`, `positions[].line`, `code`, numeric `level` (0-3). Legacy формат использует `fileName`, `lineNumber`, `warningCode`, string `level`/`severity`. Parser поддерживает оба формата.
2. **Multi-position warnings**: Одно предупреждение может иметь несколько позиций (например, V501 на нескольких строках). Каждая позиция создаёт отдельный issue.
3. **Numeric level mapping**: `0` → "Analysis", `1` → "High", `2` → "Medium", `3` → "Low"
4. **Пустые file paths**: Warnings с пустым `file` в positions пропускаются (meta-warnings об процессе анализа).
5. Пути в отчёте зависят от ОС сборки. Windows: `C:\Build\src\main.cpp`, Linux: `/build/src/main.cpp`. Нормализуем в фингерпринте (`\` → `/`).
6. `pvs-studio-analyzer` может дублировать предупреждения при параллельном анализе. Дедупликация по фингерпринту обязательна.

## 📐 Границы ответственности
- ✅ Входит: приём отчётов, инкремент, UI, LDAP, вебхуки, служба
- ❌ Не входит: статический анализ кода, CI-пайплайны, Docker, Kubernetes, SSO, SAML, многопрофильность (только LDAP)
```
🔹 **Зачем:** AI перестаёт "галлюцинировать" альтернативы, понимает trade-offs и пишет код в рамках принятых ограничений.
