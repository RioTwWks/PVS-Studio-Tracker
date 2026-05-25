"""
Обработчик веб-хука SonarQube.

Получает веб-хуки от SonarQube и обрабатывает результаты анализа.
"""

from datetime import datetime
from fastapi import Request, HTTPException, Depends, status, BackgroundTasks
import hashlib
import hmac
import json
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import re

from .config import settings
from . import crud
from .database import get_db
from .rate_limiter import limiter, RateLimits
from .cache import get_cache
from .logging_config import get_logger, ContextFilter
from .jira_issue import create_jira_issue, check_exist_task, get_jira_client, add_comment
from .sonarqube_api_client import sonarqube_client, sonarqube_client_token

# Настройка логирования для SonarQube веб-хуков
logger = get_logger("sonarqube_webhook", log_dir="logs/sonarqube", add_file_handler=True)

# Добавление фильтра контекста
context_filter = ContextFilter()
for handler in logger.handlers:
    handler.addFilter(context_filter)


# Модели данных для веб-хука SonarQube
class SonarQubeProject(BaseModel):
    # Проект SonarQube
    key: str
    name: str
    url: str = ""


class SonarQubeBranch(BaseModel):
    # Ветка проекта SonarQube
    name: Optional[str] = None
    type: Optional[str] = None
    isMain: Optional[bool] = None
    url: Optional[str] = None


class SonarQubeQualityGateCondition(BaseModel):
    # Условие Quality Gate SonarQube
    metric: str
    operator: str
    value: Optional[str] = None
    status: str
    errorThreshold: Optional[str] = None


class SonarQubeQualityGate(BaseModel):
    # Quality Gate SonarQube
    name: str
    status: str
    conditions: List[SonarQubeQualityGateCondition] = []


class SonarQubeWebhookPayload(BaseModel):
    # Полезная нагрузка веб-хука SonarQube
    serverUrl: str
    taskId: str
    status: str
    analysedAt: str
    changedAt: Optional[str] = None
    revision: Optional[str] = None
    project: SonarQubeProject
    branch: Optional[SonarQubeBranch] = None
    qualityGate: SonarQubeQualityGate
    properties: Optional[Dict[str, Any]] = None


def fix_json_string(json_str: str) -> str:
    # Попытка исправить JSON строку, если она пришла в некорректном формате.
    # Исправляет отсутствующие кавычки вокруг ключей.
    # Паттерн для поиска ключей без кавычек
    # Ищет последовательности слов, за которыми идет двоеточие
    pattern = r'(\s*)(\w+)(\s*):'

    def replace_func(match):
        # Добавление кавычек вокруг ключа
        return f'{match.group(1)}"{match.group(2)}"{match.group(3)}:'

    fixed_str = re.sub(pattern, replace_func, json_str)

    # Замена одинарных кавычек на двойные
    fixed_str = fixed_str.replace("'", '"')

    return fixed_str


# Проверка подписи веб-хука от SonarQube
def verify_sonarqube_signature(
    request: Request,               # Объект запроса
    body: bytes,                    # Байты тела запроса
    secret: str,                    # Секрет веб-хука
    verify_signature: bool = True   # Включить/отключить проверку
) -> bool:
    if not verify_signature or not secret:
        logger.info("Проверка подписи отключена или секрет не задан")
        return True

    signature_header = request.headers.get("X-Sonar-Webhook-HMAC-SHA256")
    if not signature_header:
        logger.warning("Отсутствует заголовок с подписью X-Sonar-Webhook-HMAC-SHA256")
        return False

    try:
        expected_signature = hmac.new(
            key=secret.encode('utf-8'),
            msg=body,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature_header):
            logger.error(f"Неверная подпись. Ожидалось: {expected_signature}, получено: {signature_header}")
            return False

        logger.info("Подпись верифицирована успешно")
        return True

    except Exception as e:
        logger.error(f"Ошибка при проверке подписи: {e}", exc_info=True)
        return False


# Извлечение контекстной информации из заголовков запроса
def extract_request_context(request: Request) -> Dict[str, str]:
    context = {
        "webhook_id": request.headers.get("X-Sonar-Webhook-Id", "unknown"),
        "webhook_timestamp": request.headers.get("X-Sonar-Webhook-Timestamp", "unknown"),
        "user_agent": request.headers.get("User-Agent", "unknown"),
        "client_ip": request.client.host if request.client else "unknown",
        "content_type": request.headers.get("Content-Type", "unknown"),
        "content_length": request.headers.get("Content-Length", "unknown"),
        "signature_header": request.headers.get("X-Sonar-Webhook-HMAC-SHA256", "not_present")
    }

    return context


# Обработка веб-хука от SonarQube
async def process_sonarqube_webhook(
    payload: SonarQubeWebhookPayload,   # Разобранная полезная нагрузка
    context: Dict[str, str],            # Контекст запроса
    db: Session                         # Сессия базы данных
):
    try:
        project_key = payload.project.key
        project_name = payload.project.name
        quality_gate_status = payload.qualityGate.status
        analysis_status = payload.status
        task_id = payload.taskId

        logger.info(
            f"Обработка веб-хука от SonarQube: "
            f"проект={project_name} ({project_key}), "
            f"quality gate={quality_gate_status}, "
            f"статус анализа={analysis_status}, "
            f"taskId={task_id}"
        )

        # Инвалидация кэша для этого проекта (новый анализ завершён)
        cache = get_cache()
        cache.invalidate_project(project_key)
        logger.info(f"Кэш инвалидирован для проекта: {project_key}")

        # Получение дополнительной информации из API SonarQube
        # (закомментировано для оптимизации)
        # if settings.SONARQUBE_TOKEN:
        #     try:
        #         # Получение детальных метрик
        #         measures = sonarqube_client.get_project_measures(project_key)
        #         ...

        # Логирование информации о ветке, если есть
        if payload.branch:
            logger.info(
                f"Ветка: {payload.branch.name}, тип: {payload.branch.type}, "
                f"основная: {payload.branch.isMain}"
            )

        # Логирование условий Quality Gate
        if payload.qualityGate.conditions:
            conditions_info = []
            for condition in payload.qualityGate.conditions:
                value_display = condition.value if condition.value is not None else "NO_VALUE"
                conditions_info.append(
                    f"{condition.metric}: {condition.status} "
                    f"(оператор: {condition.operator}, значение: {value_display})"
                )
            logger.info(f"Условия Quality Gate: {', '.join(conditions_info)}")

        # Логирование свойств, если есть
        if payload.properties:
            logger.info(f"Свойства анализа: {json.dumps(payload.properties, ensure_ascii=False)}")

        # Поиск проекта в БД
        project = crud.get_project_by_sonar_key(db, project_key)
        if not project:
            logger.error(f"Проект с ключом {project_key} не найден в БД")
            return

        logger.info(f"Найден проект в БД: {project.sonar_project_name}")

        # Проверка release ветки - включение Jira
        if 'release' in project.another_branch.lower():
            crud.enable_jira(db, project.id)
            logger.info(f"Создание задач Jira возобновлено для релизной ветки {project.another_branch} после первого сканирования")
            return

        # Получение Issues
        issues_data = sonarqube_client.get_project_issues(project_key)

        total_issues = issues_data.get("total", 0)
        issues_list = issues_data.get("issues", [])

        logger.info(f"Для проекта '{project_name}' найдено проблем (issues): {total_issues}")

        if issues_list:
            logger.info("Список найденных проблем:")
            issues_with_code = []
            for issue in issues_list:
                # Извлечение ключевой информации о каждой проблеме
                logger.info(f"  - Правило: {issue.get('rule')}")
                logger.info(f"    Сообщение: {issue.get('message')}")
                logger.info(f"    Серьезность: {issue.get('severity')}")
                logger.info(f"    Тип: {issue.get('type')}")
                logger.info(f"    Компонент: {issue.get('component')}")
                logger.info(f"    Строка: {issue.get('line')}")
                logger.info(f"    Key: {issue.get('key')}")
                logger.info(f"    Автор: {issue.get('author')}")
                logger.info("    ---")

                # Получение строк кода
                issue_line = issue.get('line')
                component_key = issue.get('component')

                if issue_line and component_key:
                    try:
                        line_num = int(issue_line)
                        success, result = sonarqube_client_token.get_code_snippet(component_key, line_num, 5)
                        if success:
                            issue_code_data = {
                                'issue_info': issue,
                                'code_context': result,
                                'formatted_code': []
                            }
                            issues_with_code.append(issue_code_data)

                            formatted_lines = []
                            for line_num_in_code, line_text in result["clean_sources"]:
                                # Использование --> для строки с ошибкой, пробелы для остальных
                                marker = "-->" if line_num_in_code == line_num else "   "
                                formatted_line = f"L{line_num_in_code:4d} {marker} {line_text}"
                                formatted_lines.append(formatted_line)
                                issue_code_data['formatted_code'].append(formatted_line)

                            # Логирование
                            logger.info(f"Код для проблемы {issue['rule']}:")
                            for line in formatted_lines:
                                logger.info(f"  {line}")

                        else:
                            logger.error(f"Ошибка получения кода: {result.get('error')}")
                            return

                    except ValueError:
                        logger.error(f"Некорректный номер строки в проблеме: {issue_line}")
                        return
                else:
                    logger.error(f"У проблемы отсутствует номер строки или ключ компонента")
                    return

                # Создание задачи Jira если включено
                if project.disable_jira:
                    logger.info(f"Отключено создание задач в Jira. Пропускаем.")
                    return
                else:
                    if not check_exist_task(issue.get('key')):
                        # Получение ID ошибки SonarQube
                        sonarqube_issue_id = issue.get('key')

                        created_issue = create_jira_issue(
                            project,
                            issue.get('message'),
                            f"В файле {issue.get('component').split(':')[1]} найдена проблема {issue.get('message')} типа {issue.get('type')} правила {issue.get('rule')}. Приоритет {issue.get('severity')}.\n{{code:cpp}}\n{'\n'.join(formatted_lines)}\n{{code}}\nСсылка на ошибку в SonarQube: [http://qube/project/issues?open={issue.get('key')}&id={project.sonar_project_key}|http://qube/project/issues?open={issue.get('key')}&id={project.sonar_project_key}]",
                            sonarqube_issue_id=sonarqube_issue_id
                        )
                        if created_issue:
                            try:
                                jira_client = get_jira_client()
                                if jira_client is not None:
                                    # Извлечение ключа проекта из ключа задачи
                                    issue_key = created_issue.key
                                    project_key_from_issue = issue_key.split('-')[0] if '-' in issue_key else None

                                    if project_key_from_issue:
                                        project_obj = jira_client.project(project_key_from_issue)
                                        if project_obj and hasattr(project_obj, 'lead') and project_obj.lead:
                                            jira_client.add_watcher(created_issue, project_obj.lead.displayName)
                                            logger.info(f"Watcher добавлен к задаче {issue_key}: {project_obj.lead.displayName}")
                                    else:
                                        logger.warning(f"Не удалось извлечь ключ проекта из ключа задачи: {issue_key}")
                            except Exception as e:
                                logger.warning(f"Не удалось добавить watcher к задаче: {e}")
                    else:
                        logger.info(f"Задача в Jira уже создана.")

        # Получение списка исправленных Issues
        success, result = sonarqube_client.get_fixed_issues(project_key)
        if success:
            fixed_issues = result.get('issues', [])
            total = result.get('total', 0)
            logger.info(f"Всего исправлено проблем: {total}")
            for issue in fixed_issues:
                logger.info(f"  - Правило: {issue.get('rule')}, Дата закрытия: {issue.get('closeDate')}, ID: {issue.get('key')}")
                parsed_date = datetime.fromisoformat(issue.get('closeDate').replace('Z', '+00:00'))
                if parsed_date.astimezone().date() == datetime.now().astimezone().date():
                    add_comment(issue.get('key'))
                else:
                    logger.info(f"Исправление старое. Пропускаем")
        else:
            logger.info(f"Исправленных багов в проекте {project_name} нет")

        logger.info(f"Веб-хук от SonarQube успешно обработан для проекта {project_name}")

    except Exception as e:
        logger.error(
            f"Ошибка при обработке веб-хука от SonarQube: {e}",
            exc_info=True,
            extra={"repo_name": payload.project.name if payload else "unknown"}
        )
        return


# Эндпоинт для приема веб-хуков от SonarQube
@limiter.limit(RateLimits.SONARQUBE_WEBHOOK)
# Обработчик веб-хуков SonarQube
async def handle_sonarqube_webhook(
    background_tasks: BackgroundTasks,  # Фоновые задачи FastAPI
    request: Request,                   # Запрос FastAPI
    db: Session = Depends(get_db)       # Сессия базы данных
):
    # Получение тела запроса
    body_bytes = await request.body()

    # Извлечение контекста для логирования
    context = extract_request_context(request)

    logger.info(
        f"Получен веб-хук от SonarQube. "
        f"Webhook ID: {context['webhook_id']}, "
        f"IP: {context['client_ip']}, "
        f"Content-Type: {context['content_type']}, "
        f"Content-Length: {context['content_length']}"
    )

    # Проверка подписи если включено
    if settings.SONARQUBE_VERIFY_SIGNATURE:
        if not verify_sonarqube_signature(
            request,
            body_bytes,
            settings.SONARQUBE_WEBHOOK_SECRET,
            settings.SONARQUBE_VERIFY_SIGNATURE
        ):
            if context["signature_header"] != "not_present":
                logger.error("Неверная подпись веб-хука")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Неверная подпись веб-хука"
                )

    try:
        # Декодирование тела запроса
        body_str = body_bytes.decode('utf-8')
        logger.debug(f"Получено тело (raw): {body_str[:200]}...")

        # Попытка разбора JSON
        payload_data = None
        json_error = None

        try:
            payload_data = json.loads(body_str)
        except json.JSONDecodeError as e:
            json_error = str(e)
            logger.warning(f"Первая попытка парсинга JSON не удалась: {e}")

            # Попытка исправить некорректный JSON
            try:
                fixed_body = fix_json_string(body_str)
                payload_data = json.loads(fixed_body)
                logger.info("JSON успешно исправлен и распарсен")
            except json.JSONDecodeError as e2:
                logger.error(f"Исправление JSON не помогло: {e2}")
                logger.error(f"Исходное тело: {body_str[:500]}...")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Неверный JSON: {e2}"
                )

        # Валидация структуры данных через Pydantic
        try:
            payload = SonarQubeWebhookPayload(**payload_data)
        except Exception as e:
            logger.error(f"Ошибка валидации данных: {e}")
            logger.error(f"Данные: {json.dumps(payload_data, indent=2, ensure_ascii=False)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат полезной нагрузки: {e}"
            )

        logger.info(
            f"Веб-хук успешно распарсен. "
            f"Проект: {payload.project.name}, "
            f"Статус Quality Gate: {payload.qualityGate.status}"
        )

        # Добавление фоновой задачи для обработки
        background_tasks.add_task(
            process_sonarqube_webhook,
            payload,
            context,
            db
        )

        return {
            "status": "accepted",
            "message": "Webhook received and queued for processing",
            "project": payload.project.name,
            "quality_gate_status": payload.qualityGate.status,
            "task_id": payload.taskId
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Непредвиденная ошибка при обработке запроса: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {e}"
        )


# Проверка здоровья эндпоинта SonarQube веб-хуков
@limiter.limit(RateLimits.HEALTH_CHECK)
def sonarqube_health_check(request: Request):
    # Проверка работоспособности SonarQube веб-хуков
    logger.info("Проверка работоспособности SonarQube веб-хуков")

    return {
        "status": "ok",
        "service": "sonarqube-webhook",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "verify_signature": settings.SONARQUBE_VERIFY_SIGNATURE,
            "has_secret": bool(settings.SONARQUBE_WEBHOOK_SECRET)
        }
    }
