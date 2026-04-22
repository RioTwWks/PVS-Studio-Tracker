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
  API -->|UI: code viewer| CodeViewer[/ui/file + /ui/projects/{id}/code-viewer]
  API -->|API: JSON| JSONResponse[API Response]
  API --> Parser[parser.py]
  API --> Classifier[classifier_parser.py]
  API --> FileResolver[file_resolver.py]
  API --> DB[(SQLite/PostgreSQL)]
  Parser --> Diff[incremental.py]
  Classifier --> DB[(ErrorClassifier Table)]
  Diff --> DB
  DB --> UI[Jinja2+HTMX]
  CodeViewer --> DB
  CodeViewer --> FileResolver
  FileResolver --> SourceFiles[Source Files on Disk]
  API --> Webhook[httpx BackgroundTasks]
  Webhook --> External[Telegram/CI/Slack]
  UI --> Chart[Chart.js]
  UI --> i18n[I18n RU/EN]
  UI --> Theme[Dark Blue Theme]
  UI --> ClassifierInfo[Classifier Badges]
  UI --> CodeTab[Code Tab (inline viewer)]
  CodeViewer --> CodeViewerPage[Standalone Code Viewer Page]
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
| **Branch Switcher** | Отдельная таблица распределения | Команды работают с несколькими ветками — переключатель фильтрует весь дашборд (график + issues) |
| **Commit hash 6 chars** | Полный хэш или 7 chars | Стандартная короткая форма хэша, компактно для оси X |
| **Code Viewer: tabs** | Боковая панель | SonarQube-style UX, полное использование экрана, удобнее для работы с кодом |
| **Code Viewer: file browser** | Только inline view | Отдельная страница с файловым браузером для навигации по всем файлам с предупреждениями |
| **Secure file resolver** | Прямой доступ к файлам | Защита от path traversal, поддержка Windows/Linux путей, кэширование с инвалидацией по mtime |
| **HTMX partial без base.html** | Наследование base.html | Избежание дублирования навигации при HTMX-загрузке кода во вкладку Code |

## 🎨 Frontend
- **CSS**: `static/style.css` — CSS custom properties, тёмно-синяя палитра (`#0b1a2e`, `#0f2240`, `#142d50`), smooth transitions, code viewer styles
- **JS**: `static/app.js` — `ThemeManager` (light/dark), `I18n` (RU/EN toggle), `createTrendChart` (Chart.js wrapper), `showToast`, animated counters, `switchToCodeTab()` for tab switching
- **Translations**: `static/translations.json` — словарь ru/en, ключи через `data-i18n` / `data-i18n-placeholder`
- **Icons**: Bootstrap Icons CDN (`bi bi-*`)
- **Таблицы в dark mode**: `[data-theme="dark"] .card .table { ... !important }` — принудительно перебивает белый фон Bootstrap
- **Вкладки (Tabs)**: Dashboard использует Bootstrap tabs для разделения Issues и Code Viewer. HTMX загружает код в `#code-viewer-content`, JS переключает на вкладку Code
- **Code Viewer стили**: `.nav-tabs`, `.file-browser-card`, `.code-table`, `.line-with-issue`, `.issue-badge`, `.code-container` — все поддерживают dark theme

## 🌿 Branch & Commit Tracking
- **Branch Switcher**: В верхней части дашборда — выпадающий список веток. При выборе ветки весь дашборд (график + таблица issues) перезагружается с фильтром по выбранной ветке. URL: `?branch=<name>`
- **Commit Hashes on Chart**: Ось X графика показывает короткий хэш коммита (6 символов) + дату. При наведении тултип показывает полный хэш коммита, имя ветки и полную дату/время

## 🔍 Code Viewer
- **Inline tab view**: На дашборде вкладка "Код" загружает исходный файл с предупреждениями при клике на кнопку "View Code" в таблице issues
- **Standalone page**: `/ui/projects/{id}/code-viewer` — полнофункциональная страница с файловым браузером (список файлов с предупреждениями слева) и отображением кода (справа)
- **Line-level annotations**: Каждая строка с предупреждением показывает цветные бейджи (severity + rule code) в правой колонке
- **Target highlighting**: Клик на issue прокручивает и подсвечивает конкретную строку с анимацией flash
- **Secure file access**: `file_resolver.py` защищает от path traversal, поддерживает Windows/Linux абсолютные пути, кэширует файлы с инвалидацией по mtime
- **File browser**: Показывает все файлы с предупреждениями, отсортированные по количеству issues, с бейджами-счётчиками
- **HTMX partial template**: `code_view.html` — частичный шаблон БЕЗ наследования `base.html`, чтобы избежать дублирования навигации при HTMX-загрузке
- **Routes**:
  - `GET /ui/file?project_id=&file_path=&line=&run_id=` — inline code snippet (HTMX partial, no base.html)
  - `GET /ui/projects/{id}/code-viewer?run_id=` — standalone code viewer page with file browser

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
