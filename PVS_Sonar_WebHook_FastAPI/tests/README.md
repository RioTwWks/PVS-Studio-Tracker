# Документация по тестированию

Unit и интеграционные тесты для SAST PVS+Sonar Project Manager.

## Установка

Установите зависимости для тестирования:

```bash
pip install -r requirements.txt  # Включает pytest, httpx, respx, etc.
```

## Запуск тестов

### Запустить все тесты
```bash
pytest
```

### Запустить с подробным выводом
```bash
pytest -v
```

### Запустить конкретный файл тестов
```bash
pytest tests/test_webhooks.py -v
```

### Запустить конкретный класс тестов
```bash
pytest tests/test_webhooks.py::TestHealthChecks -v
```

### Запустить конкретную тест-функцию
```bash
pytest tests/test_webhooks.py::TestHealthChecks::test_webhook_health_check -v
```

### Запустить тесты по маркерам
```bash
# Только интеграционные тесты
pytest -m integration

# Только медленные тесты
pytest -m slow

# Пропустить медленные тесты
pytest -m "not slow"
```

### Запустить с отчётом о покрытии
```bash
pytest --cov=app --cov-report=html
# Откройте htmlcov/index.html в браузере
```

### Запустить без покрытия
```bash
pytest --no-cov
```

### Логирование тестов
Тесты записывают логи в `logs/pytest/pytest.log`:
```bash
pytest -v --no-cov 2>&1 | Tee-Object -FilePath logs\pytest\pytest.log  # PowerShell
pytest -v --no-cov > logs/pytest/pytest.log 2>&1  # CMD/Linux
```

## Структура тестов

### conftest.py
Общие фикстуры pytest, mock данные, вспомогательные функции:
- `test_engine` — In-memory SQLite движок
- `test_db` — Сессия базы данных для тестов
- `client` — FastAPI TestClient
- `test_project` — Тестовый проект в БД
- `mock_env_vars` — Mock переменных окружения

### test_webhooks.py
Unit-тесты для обработчиков веб-хуков:
- `TestHealthChecks` — Проверка health endpoints
- `TestTFSWebhook` — TFS/Git веб-хуки
- `TestTFVCWebhook` — TFVC веб-хуки
- `TestSonarQubeWebhook` — SonarQube веб-хуки
- `TestWebhookIntegration` — Интеграционные тесты
- `TestRateLimiting` — Rate limiting тесты

**Покрытие:**
- Health check endpoints
- Аутентификация TFS веб-хуков
- Обработка TFVC webhook
- Обработка SonarQube webhook
- Проверка подписи
- Создание задач Jira
- Полные интеграционные сценарии

### test_cache.py
Unit-тесты для кэширования:
- `TestInMemoryCache` — In-memory бэкенд кэша
- `TestSonarQubeCache` — Менеджер кэша SonarQube
- `TestCacheTTLPresets` — Настройки TTL кэша
- `TestGlobalCacheInstance` — Управление глобальным кэшем
- `TestCacheIntegration` — Интеграция с SonarQube клиентом

### test_logging.py
Unit-тесты для логирования:
- `TestContextFilter` — Фильтр контекста
- `TestDailyRotatingFileHandler` — Обработчик ротации логов
- `TestLoggerCreation` — Создание логгеров
- `TestSetupLogging` — Настройка логирования
- `TestLogContext` — Context manager для контекста
- `TestConvenienceFunctions` — Вспомогательные функции
- `TestLoggingIntegration` — Полная интеграция

### test_services.py
Unit-тесты для сервисного слоя:
- `TestRepositoryService` — Сервис репозиториев (Git/TFVC)
- `TestGitChanges` — Обнаружение изменений Git
- `TestTFVCChanges` — Обнаружение изменений TFVC
- `TestJenkinsService` — Сервис Jenkins
- `TestJiraService` — Сервис Jira
- `TestCRUDValidation` — Валидация данных проекта

### test_integration.py
Интеграционные тесты:
- `TestGitWebhookIntegration` — Git webhook end-to-end
- `TestSonarQubeWebhookIntegration` — SonarQube webhook end-to-end
- `TestHealthCheckIntegration` — Health check тесты
- `TestProjectManagementIntegration` — Управление проектами

## Тестовые данные

### Учётные данные по умолчанию
- Username: `test`
- Password: `test`

### Тестовые данные проекта
```python
TEST_PROJECT_DATA = {
    "group_id": 1,
    "author_email": "test@example.com",
    "sonar_project_name": "TestProject",
    "sonar_project_key": "test_project_key",
    "jira_project": "TEST",
    "cvs_system": "Git",
    "tfs_path": "http://repo.git",
    "another_branch": "master",
    "pvs_check_conf_name": "Release",
    "pvs_check_arch": "x64",
    # ... остальные поля
}
```

## Написание новых тестов

### Пример добавления теста

```python
def test_my_custom_scenario(client, test_db, mock_env_vars):
    """Test custom scenario."""
    # Arrange
    payload = {...}
    headers = {
        **get_basic_auth_headers(TEST_WEBHOOK_USERNAME, TEST_WEBHOOK_PASSWORD),
        "X-TFS-Repo-Type": "Git",
        ...
    }
    
    # Act
    with patch('app.webhooks.trigger_jenkins_build') as mock_jenkins:
        response = client.post("/webhook", json=payload, headers=headers)
    
    # Assert
    assert response.status_code == 200
    mock_jenkins.assert_called()
```

### Best Practices

1. **Используйте фикстуры** — `test_db`, `client`, `mock_env_vars`
2. **Mock внешних API** — Jenkins, SonarQube, Jira
3. **Проверяйте несколько условий** — status code, вызовы mock, данные в БД
4. **Используйте параметризацию** для похожих тестов:
   ```python
   @pytest.mark.parametrize("email,expected", [
       ("valid@example.com", True),
       ("invalid", False),
   ])
   def test_email_validation(email, expected):
       ...
   ```

## Устранение неполадок

### Ошибка импорта
Убедитесь, что запускаете тесты из корня проекта:
```bash
cd c:\qwen_code\SAST\PVS_Sonar_WebHook_FastAPI
pytest
```

### Тесты не находят фикстуры
Проверьте, что `conftest.py` находится в папке `tests/`:
```
tests/
├── conftest.py  ← должен быть здесь
├── test_*.py
```

### Проблемы с asyncio
Для async тестов убедитесь, что используется правильный режим:
```python
@pytest.mark.asyncio
async def test_async_function():
    ...
```

### Логирование не работает
Проверьте, что директория для логов существует:
```bash
mkdir logs\pytest
```

## CI/CD Интеграция

Добавьте в ваш CI pipeline:

```yaml
# Пример для GitHub Actions
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest --cov=app --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

## Статистика тестов

| Файл | Тестов | Описание |
|------|--------|----------|
| test_cache.py | 17 | Кэширование |
| test_integration.py | 9 | Интеграционные |
| test_logging.py | 20 | Логирование |
| test_services.py | 30 | Сервисный слой |
| test_webhooks.py | 23 | Веб-хуки |
| **ВСЕГО** | **99** | **Полное покрытие** |
