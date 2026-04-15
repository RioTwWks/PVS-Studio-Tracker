# Inline Code Viewer — Реализация в стиле SonarQube

## Обзор

PVS-Studio Tracker **не хранит исходный код на сервере**. Вместо этого код извлекается **динамически** при запросе, как в SonarQube. Это позволяет работать с отчётами, загруженными с разных узлов на разных ОС, без необходимости хранения копий исходных файлов.

---

## 🎯 Как это работает

### Strategy Pattern (Fallback Chain)

При запросе исходного кода система пытается получить файл из нескольких источников **в порядке приоритета**:

```
1. Git Repository (SonarQube-style)
      ↓ (если недоступен)
2. Source Archive (uploaded zip/tar)
      ↓ (если недоступен)
3. Local Filesystem (legacy, backward compatibility)
      ↓ (если недоступен)
4. Error: "Исходный код недоступен"
```

---

## ⚙️ Настройка

### 1. Git Repository (Рекомендуется)

Это подход **в стиле SonarQube** — код извлекается по требованию из Git, никогда не хранится постоянно на сервере.

#### Настройки проекта

Настройте через интерфейс проекта или API:

```json
{
  "git_url": "https://github.com/org/repo.git",
  "git_branch": "main"
}
```

#### Пример API

**Linux/macOS:**
```bash
# Создание проекта с Git URL
curl -X POST http://localhost:8080/api/v2/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-project",
    "git_url": "https://github.com/myorg/myrepo.git",
    "git_branch": "main"
  }'

# Обновление существующего проекта
curl -X PATCH http://localhost:8080/api/v2/projects/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "git_url": "https://github.com/myorg/myrepo.git",
    "git_branch": "develop"
  }'
```

**Windows (cmd):**
```cmd
REM Создание проекта с Git URL
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"git_url\": \"https://github.com/myorg/myrepo.git\", \"git_branch\": \"main\"}"

REM Обновление существующего проекта
curl -X PATCH http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"git_url\": \"https://github.com/myorg/myrepo.git\", \"git_branch\": \"develop\"}"
```

**Windows (PowerShell):**
```powershell
# Создание проекта с Git URL
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "git_url": "https://github.com/myorg/myrepo.git", "git_branch": "main"}'

# Обновление существующего проекта
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects/1 -Method PATCH -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"git_url": "https://github.com/myorg/myrepo.git", "git_branch": "develop"}'
```

#### Как это работает

1. **Первый запрос**: Клонирование репозитория в кэш (директория `.git_cache/`)
2. **Последующие запросы**: Обновление кэша (git pull) если TTL истёк
3. **Извлечение файла**: Чтение файла из кэшированного репозитория
4. **Для конкретного коммита**: Если run содержит хеш коммита, checkout именно этого коммита

#### Кэширование

- **Расположение**: `.git_cache/` (настраивается через `GIT_CACHE_DIR`)
- **TTL**: 60 минут (настраивается через `GIT_CACHE_TTL_MINUTES`)
- **Автоматическая очистка**: Просроченные кэши удаляются автоматически
- **По веткам**: Каждая ветка получает отдельную директорию кэша

#### Таймаут Git

- **По умолчанию**: 30 секунд (настраивается через `GIT_TIMEOUT_SECONDS`)
- Предотвращает зависание запросов на медленных Git операциях

---

### 2. Source Archive (Fallback)

Загрузите архив с исходным кодом (zip/tar) вместе с отчётом. Код хранится временно для анализа.

#### Upload via API

**Linux/macOS:**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=my-project" \
  -F "file=@report.json" \
  -F "source_archive=@source.zip" \
  -F "commit=abc1234" \
  -F "branch=main" \
  -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "source_archive=@source.zip" -F "commit=abc1234" -F "branch=main" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v1/upload -Method POST -Headers @{Authorization="Bearer $TOKEN"} -Form @{
    project_name = "my-project"
    file = Get-Item "C:\path\to\report.json"
    source_archive = Get-Item "C:\path\to\source.zip"
    commit = "abc1234"
    branch = "main"
}
```

#### Поддерживаемые форматы

- **ZIP** (`.zip`)
- **TAR** (`.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`)

#### Структура архива

Архив должен содержать исходные файлы с путями, совпадающими с отчётом PVS-Studio:

```
source.zip
├── src/
│   ├── main.cpp
│   ├── utils.cpp
│   └── ...
└── include/
    └── ...
```

---

### 3. Local Filesystem (Legacy)

Для обратной совместимости с существующими setups, где исходный код доступен на сервере.

#### Настройки проекта

```json
{
  "source_root_win": "C:\\Projects\\my-project\\src",
  "source_root_linux": "/home/user/projects/my-project/src"
}
```

#### API Example

**Linux/macOS:**
```bash
curl -X PATCH http://localhost:8080/api/v2/projects/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_root_win": "C:\\Projects\\my-project\\src",
    "source_root_linux": "/home/user/projects/my-project/src"
  }'
```

**Windows (cmd):**
```cmd
curl -X PATCH http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"source_root_win\": \"C:\\\\Projects\\\\my-project\\\\src\", \"source_root_linux\": \"/home/user/projects/my-project/src\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects/1 -Method PATCH -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"source_root_win": "C:\\Projects\\my-project\\src", "source_root_linux": "/home/user/projects/my-project/src"}'
```

---

## 🔧 Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `GIT_CACHE_DIR` | `.git_cache/` | Директория для кэша Git репозиториев |
| `GIT_CACHE_TTL_MINUTES` | `60` | Время жизни кэша в минутах |
| `GIT_TIMEOUT_SECONDS` | `30` | Таймаут для Git операций |

---

## 🚀 Примеры использования

### Пример 1: Публичный Git репозиторий

**Linux/macOS:**
```bash
# 1. Создание проекта с Git URL
curl -X POST http://localhost:8080/api/v2/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "open-source-project",
    "git_url": "https://github.com/example/public-repo.git",
    "git_branch": "main"
  }'

# 2. Загрузка отчёта (архив не нужен)
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=open-source-project" \
  -F "file=@pvs-report.json" \
  -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
REM 1. Создание проекта с Git URL
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"open-source-project\", \"git_url\": \"https://github.com/example/public-repo.git\", \"git_branch\": \"main\"}"

REM 2. Загрузка отчёта (архив не нужен)
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=open-source-project" -F "file=@pvs-report.json" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
# 1. Создание проекта с Git URL
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "open-source-project", "git_url": "https://github.com/example/public-repo.git", "git_branch": "main"}'

# 2. Загрузка отчёта
Invoke-RestMethod -Uri http://localhost:8080/api/v1/upload -Method POST -Headers @{Authorization="Bearer $TOKEN"} -Form @{
    project_name = "open-source-project"
    file = Get-Item "C:\path\to\pvs-report.json"
}
```

### Пример 2: Приватный проект с архивом исходников

**Windows (cmd):**
```cmd
REM 1. Создание проекта (без Git URL)
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"private-project\"}"

REM 2. Загрузка отчёта + архив с исходниками
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=private-project" -F "file=@pvs-report.json" -F "source_archive=@sources.zip" -H "Authorization: Bearer %TOKEN%"
```

### Пример 3: Local Filesystem (Legacy)

**Windows (cmd):**
```cmd
REM 1. Создание проекта с source roots
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"legacy-project\", \"source_root_linux\": \"/opt/src/legacy\"}"

REM 2. Загрузка отчёта
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=legacy-project" -F "file=@pvs-report.json" -H "Authorization: Bearer %TOKEN%"
```

---

## 🔍 Решение проблем

### "Исходный код недоступен"

**Проблема**: Все три стратегии не сработали.

**Решения**:

1. **Настройте Git URL** (рекомендуется):
   ```cmd
   curl -X PATCH http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"git_url\": \"https://github.com/org/repo.git\"}"
   ```

2. **Загрузите архив с исходниками**:
   ```cmd
   curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "source_archive=@sources.zip"
   ```

3. **Настройте source roots** (legacy):
   ```cmd
   curl -X PATCH http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"source_root_linux\": \"/path/to/src\"}"
   ```

### Git Clone не работает

**Проблема**: Репозиторий недоступен.

**Решения**:

1. **Проверьте URL**: Убедитесь что `git_url` правильный и доступен
2. **Публичный репо**: Проверьте что репозиторий публичный
3. **Приватный репо**: Настройте SSH доступ или используйте токен
4. **Таймаут**: Увеличьте `GIT_TIMEOUT_SECONDS` для больших репо

---

## ✅ Преимущества

### vs. Хранение кода на сервере

| Характеристика | Старый (Storage) | Новый (On-Demand) |
|----------------|------------------|-------------------|
| **Использование диска** | Высокое (все файлы) | Низкое (только кэш) |
| **Multi-OS** | ❌ Нет | ✅ Да |
| **Multi-machine** | ❌ Нет | ✅ Да |
| **Свежесть кода** | Устаревший (snapshot) | Свежий (из Git) |
| **Для коммита** | ❌ Нет | ✅ Да |
| **Безопасность** | Копия кода на сервере | Нет постоянного хранения |
| **Масштабируемость** | Плохая (растёт диск) | Хорошая (кэш с TTL) |

### Паритет с SonarQube

✅ **Нет хранения кода на сервере** — как SonarQube  
✅ **Git/SCM integration** — извлечение по требованию  
✅ **Просмотр для коммита** — код как он был  
✅ **Несколько стратегий** — гибкое развёртывание  
✅ **Автоматический кэш** — оптимизация производительности  
✅ **Fallback chain** — graceful degradation  

---

**Версия**: 0.2.0+  
**Дата**: 15 апреля 2026  
**Статус**: Production Ready ✅
