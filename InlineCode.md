Для реализации inline-просмотра кода с предупреждениями (как в SonarQube/GitLab) нужно решить 3 задачи:
1. **Безопасное разрешение путей** (CI-пути ≠ пути на сервере, защита от `../` traversal)
2. **Серверный рендеринг** с привязкой предупреждений к строкам
3. **HTMX-интеграция** без перезагрузки страницы

Ниже готовый, production-ready модуль. Полностью соответствует `spec.md` и `.qwen/rules.md`.

---

## 📐 1. Обновление модели (`models.py`)
Добавьте поле `source_root` в `Project`. Это корневая директория исходников на сервере.
```python
class Project(SQLModel, table=True):
    # ... существующие поля ...
    source_root: str = Field(default=".", description="Базовый путь к исходникам на сервере")
```
⚠️ **Важно:** После изменения запустите: `SQLModel.metadata.create_all(engine)` (в dev достаточно, в prod используйте Alembic или скрипт миграции).

---

## 🛡 2. Безопасный резолвер путей (`file_resolver.py`)
```python
import os
from pathlib import Path
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

def resolve_source_path(project_source_root: str, report_file_path: str) -> Path:
    """
    Безопасно преобразует путь из отчёта PVS в абсолютный путь на сервере.
    Защита от Path Traversal, поддержка Windows/Linux путей.
    """
    if not project_source_root:
        raise HTTPException(400, "Не настроен source_root для проекта")

    base = Path(project_source_root).resolve()
    
    # Нормализуем путь из отчёта
    norm_path = report_file_path.replace("\\", "/").strip()
    
    # Если путь абсолютный, пытаемся извлечь относительную часть
    if Path(norm_path).is_absolute():
        # Пробуем отрезать известные префиксы (CI/CD часто дают полные пути)
        for prefix in ["/build", "/src", "/workspace", "C:\\", "/home"]:
            if norm_path.lower().startswith(prefix.lower()):
                norm_path = norm_path[len(prefix):].lstrip("/\\")
                break
        else:
            # Fallback: берём basename, если не удалось сопоставить
            logger.warning(f"Absolute path not mapped, using basename: {norm_path}")
            norm_path = Path(norm_path).name

    target = (base / norm_path).resolve()
    
    # 🔒 Строгая проверка: путь должен начинаться с base
    if not str(target).startswith(str(base) + os.sep) and str(target) != str(base):
        raise HTTPException(403, "Path traversal blocked")
        
    if not target.exists():
        raise HTTPException(404, f"Файл не найден: {target}")
    if not target.is_file():
        raise HTTPException(400, "Указан не файл")
        
    return target
```

---

## 🌐 3. Роут просмотра кода (`code_viewer.py`)
```python
from fastapi import APIRouter, Request, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from jinja2 import Template
import asyncio
from .db import get_session
from .models import Project, Issue, Run
from .file_resolver import resolve_source_path

router = APIRouter()

@router.get("/ui/file", response_class=HTMLResponse)
async def view_code(
    request: Request,
    project_id: int = Query(..., ge=1),
    file_path: str = Query(...),
    line: int = Query(None, ge=1),
    run_id: int = Query(None, ge=1),
    session: Session = Depends(get_session)
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")

    try:
        # Блокирующий I/O выносим в пул потоков
        abs_path = await asyncio.to_thread(resolve_source_path, project.source_root, file_path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except HTTPException as e:
        return HTMLResponse(status_code=e.status_code, content=f"❌ {e.detail}")
    except Exception as e:
        return HTMLResponse(status_code=500, content=f"❌ Ошибка чтения: {e}")

    # Определяем run: либо переданный, либо последний успешный
    if run_id:
        run = session.get(Run, run_id)
    else:
        run = session.exec(
            select(Run).where(Run.project_id == project_id, Run.status == "done")
            .order_by(Run.timestamp.desc()).limit(1)
        ).first()

    warnings_by_line = {}
    if run:
        issues = session.exec(
            select(Issue).where(
                Issue.run_id == run.id,
                Issue.file_path == file_path.replace("\\", "/"),
                Issue.status.in_(["new", "existing"])  # Игнорируем fixed
            )
        ).all()
        for iss in issues:
            if iss.line not in warnings_by_line:
                warnings_by_line[iss.line] = []
            warnings_by_line[iss.line].append(iss)

    return templates.TemplateResponse("code_view.html", {
        "request": request,
        "project": project,
        "file_path": file_path,
        "abs_path": str(abs_path),
        "lines": lines,
        "warnings_by_line": warnings_by_line,
        "target_line": line,
        "run_id": run.id if run else None
    })
```
📌 Подключите роут в `main.py`: `app.include_router(code_viewer.router)`

---

## 🎨 4. Шаблон `templates/code_view.html`
```html
{% extends "base.html" %}
{% block title %}📄 {{ file_path }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h5 class="mb-0">📄 {{ file_path }}</h5>
  <div class="btn-group">
    <a href="/ui/dashboard/{{ project.id }}" class="btn btn-sm btn-outline-secondary">← Назад к дашборду</a>
  </div>
</div>

<div class="code-container border rounded bg-light">
  <table class="code-table table table-bordered table-sm mb-0">
    <tbody>
      {% for line_num, code in lines | zip(range(1, lines|length + 1)) %}
      <tr class="code-row {% if line_num in warnings_by_line %}line-with-issue{% endif %}" 
          id="L{{ line_num }}" data-line="{{ line_num }}">
        <td class="line-num text-end text-muted pe-2 select-none" style="width: 50px;">{{ line_num }}</td>
        <td class="line-code"><code>{{ code.rstrip() | e }}</code></td>
        <td class="line-gutter" style="width: 200px;">
          {% if line_num in warnings_by_line %}
            {% for w in warnings_by_line[line_num] %}
            <div class="issue-badge mb-1" 
                 data-bs-toggle="tooltip" 
                 title="🔴 {{ w.rule_code }}: {{ w.message }}">
              <span class="badge bg-{{ 'danger' if w.severity=='High' else 'warning' }}">
                {{ w.rule_code }}
              </span>
            </div>
            {% endfor %}
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<script>
  // Прокрутка к целевой строке
  {% if target_line %}
  document.addEventListener("DOMContentLoaded", () => {
    const el = document.getElementById("L{{ target_line }}");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("highlight-target");
      setTimeout(() => el.classList.remove("highlight-target"), 3000);
    }
  });
  {% endif %}
  // Инициализация Bootstrap тултипов
  const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltips.forEach(el => new bootstrap.Tooltip(el));
</script>
{% endblock %}
```

---

## 🎨 5. CSS для inline-подсветки (добавьте в `base.html` или `static/style.css`)
```css
.code-container { overflow-x: auto; max-height: 80vh; }
.code-table { border-collapse: collapse; width: 100%; font-family: 'Consolas', 'Monaco', monospace; font-size: 14px; }
.line-num { user-select: none; background: #f8f9fa; }
.line-code { white-space: pre; padding: 2px 8px; }
.line-gutter { vertical-align: top; padding: 4px; }
.line-with-issue { background-color: #fff8e1; border-left: 3px solid #ffc107; }
.line-with-issue:hover { background-color: #fff3cd; }
.issue-badge { display: inline-block; font-size: 11px; cursor: pointer; }
.highlight-target { background-color: #cce5ff !important; animation: flash 2s; }
@keyframes flash { 0% { background-color: #0d6efd; } 100% { background-color: #cce5ff; } }
.select-none { user-select: none; }
```

---

## 🔗 6. HTMX-интеграция с таблицей предупреждений
В `templates/issues_table.html` добавьте кнопку в колонку действий:
```html
<td>
  <button class="btn btn-sm btn-outline-primary"
          hx-get="/ui/file?project_id={{ project_id }}&file_path={{ issue.file_path }}&line={{ issue.line }}"
          hx-target="#code-pane"
          hx-indicator=".htmx-request"
          hx-swap="innerHTML">
    👁️ Код
  </button>
  <button class="btn btn-sm btn-outline-secondary"
          hx-post="/api/v1/issues/{{ issue.fingerprint }}/ignore"
          hx-confirm="Пометить как False Positive?">
    🚫 Игнор
  </button>
</td>
```
В `dashboard.html` добавьте контейнер рядом с таблицей или под ней:
```html
<div class="row">
  <div class="col-md-7">
    <!-- Существующая таблица -->
    <div id="issues-table" hx-get="/ui/issues?project_id={{ project.id }}" hx-trigger="load"></div>
  </div>
  <div class="col-md-5">
    <div id="code-pane" class="p-3 bg-light border rounded">
      <p class="text-muted">Выберите предупреждение для просмотра в коде</p>
    </div>
  </div>
</div>
```

---

## ⚡ 7. Оптимизация для production
| Проблема | Решение |
|----------|---------|
| **Большие файлы (>10k строк)** | Добавьте параметр `context=20` и отдавайте только строки `[line-20:line+20]`. Или используйте виртуальный скроллинг на клиенте. |
| **Повторные чтения** | Добавьте `@lru_cache(maxsize=100)` с инвалидацией по `mtime` или `file_stat`. |
| **Кодировка** | `errors="replace"` в `open()` спасает от краша на бинарных файлах. Логируйте предупреждения. |
| **Синтаксическая подсветка** | Подключите `pygments` серверно: `highlight(code, PythonLexer(), HtmlFormatter())` или `Highlight.js` на клиенте. |

Пример кеширования:
```python
import functools
from pathlib import Path

@functools.lru_cache(maxsize=256)
def _read_file_cached(abs_path_str: str, mtime: float) -> list[str]:
    with open(abs_path_str, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()
```

---

## ✅ Чек-лист внедрения
- [ ] Обновите `models.py` → `source_root`
- [ ] Создайте `file_resolver.py` с защитой от traversal
- [ ] Добавьте роут `/ui/file` с `asyncio.to_thread` для I/O
- [ ] Вставьте `code_view.html` и CSS
- [ ] Добавьте HTMX-кнопку `👁️ Код` в `issues_table.html`
- [ ] Укажите `source_root` в настройках проекта (или через UI)
- [ ] Протестируйте: `curl http://localhost:8080/ui/file?project_id=1&file_path=src/main.cpp&line=42`

🔹 **Готово к интеграции в Phase 4.5.**  
Если нужно, сгенерирую:
1. UI для настройки `source_root` через веб-интерфейс
2. Модуль серверной подсветки синтаксиса через `Pygments`
3. Виртуальный скроллинг для файлов >50k строк
4. Интеграцию с Git (показ диффа строки, ссылка на commit)

Укажите, какой блок реализовать следующим.