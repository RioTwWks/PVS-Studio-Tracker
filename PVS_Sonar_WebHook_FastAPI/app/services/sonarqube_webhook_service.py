"""
Сервис обработки веб-хуков SonarQube.

Обрабатывает:
- Валидация полезной нагрузки веб-хука
- Проверка подписи
- Обработка проблем
- Создание задач Jira
- Отслеживание исправленных проблем
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app import crud
from app.cache import get_cache
from app.sonarqube_api_client import sonarqube_client, sonarqube_client_token
from app.services.jira_service import get_jira_service
from app.services.repository_service import get_commit_author_git, get_tfvc_changeset_author

logger = get_logger(__name__)


# Процессор для обработки веб-хуков SonarQube
class SonarQubeWebhookProcessor:

    # Инициализация процессора
    def __init__(self, db: Session):
        self.db = db
        self.cache = get_cache()

    # Проверить подпись веб-хука SonarQube
    def verify_signature(
        self,
        request,                        # Объект запроса
        body: bytes,                    # Байты тела запроса
        secret: str,                    # Секрет веб-хука
        verify_signature: bool = True   # Включить/отключить проверку
    ) -> bool:
        if not verify_signature or not secret:
            logger.info("Проверка подписи отключена или секрет не задан")
            return True

        signature_header = request.headers.get("X-Sonar-Webhook-HMAC-SHA256")
        if not signature_header:
            logger.warning("Отсутствует заголовок подписи X-Sonar-Webhook-HMAC-SHA256")
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

            logger.info("Подпись успешно проверена")
            return True

        except Exception as e:
            logger.error(f"Ошибка проверки подписи: {e}", exc_info=True)
            return False

    # Исправить некорректную строку JSON (отсутствующие кавычки вокруг ключей)
    def fix_json_string(self, json_str: str) -> str:
        import re
        # Шаблон для поиска ключей без кавычек
        pattern = r'(\s*)(\w+)(\s*):'

        def replace_func(match):
            # Добавление кавычек вокруг ключа
            return f'{match.group(1)}"{match.group(2)}"{match.group(3)}:'

        fixed_str = re.sub(pattern, replace_func, json_str)

        # Замена одинарных кавычек на двойные
        fixed_str = fixed_str.replace("'", '"')

        return fixed_str

    # Разобрать полезную нагрузку веб-хука
    def parse_payload(self, body_bytes: bytes) -> Tuple[bool, Optional[Dict], str]:
        try:
            body_str = body_bytes.decode('utf-8')
            logger.debug(f"Получено тело: {body_str[:200]}...")

            # Попытка разбора JSON
            try:
                payload_data = json.loads(body_str)
                return True, payload_data, ""
            except json.JSONDecodeError as e:
                logger.warning(f"Первая попытка разбора JSON не удалась: {e}")

                # Попытка исправить некорректный JSON
                try:
                    fixed_body = self.fix_json_string(body_str)
                    payload_data = json.loads(fixed_body)
                    logger.info("JSON успешно исправлен и разобран")
                    return True, payload_data, ""
                except json.JSONDecodeError as e2:
                    logger.error(f"Исправление JSON не помогло: {e2}")
                    logger.error(f"Исходное тело: {body_str[:500]}...")
                    return False, None, f"Неверный JSON: {e2}"

        except Exception as e:
            logger.error(f"Ошибка разбора полезной нагрузки: {e}", exc_info=True)
            return False, None, str(e)

    # Обработать полезную нагрузку веб-хука SonarQube
    def process_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_key = payload.get('project', {}).get('key', '')
        project_name = payload.get('project', {}).get('name', '')
        quality_gate_status = payload.get('qualityGate', {}).get('status', '')
        analysis_status = payload.get('status', '')
        task_id = payload.get('taskId', '')

        logger.info(
            f"Обработка веб-хука SonarQube: "
            f"проект={project_name} ({project_key}), "
            f"quality gate={quality_gate_status}, "
            f"статус анализа={analysis_status}, "
            f"taskId={task_id}"
        )

        # Инвалидация кэша для этого проекта
        self.cache.invalidate_project(project_key)
        logger.info(f"Кэш инвалидирован для проекта: {project_key}")

        # Поиск проекта в базе данных
        project = crud.get_project_by_sonar_key(self.db, project_key)
        if not project:
            logger.error(f"Проект с ключом {project_key} не найден в БД")
            return {
                "status": "error",
                "message": f"Проект {project_key} не найден"
            }

        logger.info(f"Найден проект в БД: {project.sonar_project_name}")

        # Проверка release ветки - включение Jira
        if 'release' in project.another_branch.lower():
            crud.enable_jira(self.db, project.id)
            logger.info(f"Создание задач Jira включено для release ветки {project.another_branch}")
            return {
                "status": "success",
                "message": "Release ветка обнаружена, Jira включена"
            }

        # Обработка проблем
        issues_result = self._process_issues(project)

        # Обработка исправленных проблем
        fixed_result = self._process_fixed_issues(project)

        return {
            "status": "success",
            "message": f"Обработано {issues_result['count']} проблем, {fixed_result['count']} исправлено",
            "issues": issues_result,
            "fixed": fixed_result
        }

    # Обработать новые проблемы для проекта
    def _process_issues(self, project) -> Dict[str, Any]:
        issues_data = sonarqube_client.get_project_issues(project.sonar_project_key)
        total_issues = issues_data.get("total", 0)
        issues_list = issues_data.get("issues", [])

        logger.info(f"Найдено {total_issues} проблем для проекта '{project.sonar_project_name}'")

        if not issues_list:
            return {"count": 0, "created": 0}

        created_count = 0

        for issue in issues_list:
            issue_line = issue.get('line')
            component_key = issue.get('component')

            if not issue_line or not component_key:
                logger.error(f"У проблемы отсутствует номер строки или ключ компонента: {issue.get('key')}")
                continue

            # Получение фрагмента кода
            code_context = self._get_code_snippet(component_key, int(issue_line))
            if not code_context:
                continue

            # Форматирование кода для отображения
            formatted_code = self._format_code_snippet(code_context, int(issue_line))

            # Создание задачи Jira если включено
            if not project.disable_jira:
                jira_service = get_jira_service()
                if not jira_service.check_exist_task(issue.get('key')):
                    created = self._create_jira_issue(jira_service, project, issue, formatted_code)
                    if created:
                        created_count += 1
            else:
                logger.debug(f"Создание Jira отключено для проекта {project.sonar_project_name}")

        return {"count": len(issues_list), "created": created_count}

    # Получить фрагмент кода вокруг строки проблемы
    def _get_code_snippet(self, component_key: str, line_number: int) -> Optional[Dict]:
        try:
            success, result = sonarqube_client_token.get_code_snippet(
                component_key, line_number, 5
            )

            if success:
                return result
            else:
                logger.error(f"Ошибка получения кода: {result.get('error')}")
                return None

        except Exception as e:
            logger.error(f"Ошибка получения фрагмента кода: {e}", exc_info=True)
            return None

    # Форматировать фрагмент кода для отображения
    def _format_code_snippet(self, code_context: Dict, issue_line: int) -> List[str]:
        formatted_lines = []

        for line_num, line_text in code_context.get("clean_sources", []):
            # Использование --> для строки с ошибкой, пробелы для остальных
            marker = "-->" if line_num == issue_line else "   "
            formatted_line = f"L{line_num:4d} {marker} {line_text}"
            formatted_lines.append(formatted_line)

        return formatted_lines  # Список отформатированных строк кода

    # Создать задачу Jira для проблемы SonarQube
    def _create_jira_issue(
        self,
        jira_service,               # Экземпляр сервиса Jira
        project,                    # Объект проекта
        issue: Dict,                # Словарь проблемы SonarQube
        formatted_code: List[str]   # Отформатированный код
    ) -> bool:
        try:
            if project.cvs_system == 'Git':
                assignee_name, assignee_email = get_commit_author_git(project)
            elif project.cvs_system == 'TFVC':
                assignee_name, assignee_email = get_tfvc_changeset_author(project)
            logger.info(f"assignee_name = {assignee_name}, assignee_email = {assignee_email}")
            sonarqube_issue_id = issue.get('key')

            # Построение описания
            component_file = issue.get('component', '').split(':')[1]
            description = (
                f"В файле {component_file} найдена проблема: {issue.get('message')}\n"
                f"Тип: {issue.get('type')}, Правило: {issue.get('rule')}\n"
                f"Приоритет: {issue.get('severity')}\n\n"
                f"{{code:cpp}}\n{'\n'.join(formatted_code)}\n{{code}}\n\n"
                f"Ссылка: [http://qube/project/issues?open={sonarqube_issue_id}&id={project.sonar_project_key}|"
                f"http://qube/project/issues?open={sonarqube_issue_id}&id={project.sonar_project_key}]"
            )

            # Получение ключа проекта и спринта
            project_key = jira_service.get_project_key(project.jira_project)
            if not project_key:
                logger.error(f"Не удалось получить ключ проекта Jira для {project.jira_project}")
                return False

            sprint_id, _ = jira_service.get_active_sprint(project_key, project.version)

            # Пользовательские поля для интеграции SonarQube
            custom_fields = {'customfield_12205': sonarqube_issue_id}

            created_issue = jira_service.create_issue(
                project_key=project_key,
                summary=issue.get('message'),
                description=description,
                issue_type='Bug',
                sprint_id=sprint_id,
                assignee=assignee_name,
                custom_fields=custom_fields
            )

            if created_issue:
                # Добавление наблюдателя
                self._add_jira_watcher(jira_service, created_issue)
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка создания задачи Jira: {e}", exc_info=True)
            return False

    # Добавить руководителя проекта как наблюдателя к задаче Jira
    def _add_jira_watcher(self, jira_service, issue) -> None:
        try:
            if not jira_service.client:
                return

            issue_key = issue.key
            project_key = issue_key.split('-')[0] if '-' in issue_key else None

            if project_key:
                project_obj = jira_service.client.project(project_key)
                if project_obj and hasattr(project_obj, 'lead') and project_obj.lead:
                    jira_service.add_watcher(issue, project_obj.lead.displayName)
                    logger.info(f"Добавлен наблюдатель {project_obj.lead.displayName} к {issue_key}")
        except Exception as e:
            logger.warning(f"Не удалось добавить наблюдателя: {e}")

    # Обработать исправленные проблемы для проекта
    def _process_fixed_issues(self, project) -> Dict[str, Any]:
        success, result = sonarqube_client.get_fixed_issues(project.sonar_project_key)

        if not success:
            logger.info(f"Нет исправленных проблем для проекта {project.sonar_project_name}")
            return {"count": 0, "commented": 0}

        fixed_issues = result.get('issues', [])
        total = result.get('total', 0)

        logger.info(f"Всего исправлено проблем: {total}")

        commented_count = 0
        today = datetime.now().date()

        jira_service = get_jira_service()

        for issue in fixed_issues:
            close_date_str = issue.get('closeDate', '')
            if close_date_str:
                try:
                    parsed_date = datetime.fromisoformat(close_date_str.replace('Z', '+00:00'))
                    if parsed_date.astimezone().date() == today:
                        # Поиск и комментирование задачи Jira
                        jql = f'"SonarQube Issue ID" = "{issue.get("key")}"'
                        jira_issues = jira_service.search_issues(jql, max_results=1)
                        if jira_issues:
                            jira_service.add_comment(
                                jira_issues[0],
                                f"Исправлено в SonarQube: {issue.get('key')}"
                            )
                            commented_count += 1
                            logger.info(f"Добавлен комментарий к исправленной проблеме {issue.get('key')}")
                    else:
                        logger.debug(f"Исправление старое, пропускаем: {close_date_str}")
                except Exception as e:
                    logger.error(f"Ошибка обработки даты исправленной проблемы: {e}")

        return {"count": total, "commented": commented_count}


# Вспомогательные функции

# Обработать полезную нагрузку веб-хука SonarQube
def process_sonarqube_webhook(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    processor = SonarQubeWebhookProcessor(db)
    return processor.process_webhook(payload)


# Проверить подпись веб-хука SonarQube
def verify_webhook_signature(
    request,                # Запрос
    body: bytes,            # Байты тела
    secret: str,            # Секрет веб-хука
    verify: bool = True     # Включить проверку
) -> bool:
    processor = SonarQubeWebhookProcessor(None)  # type: ignore
    return processor.verify_signature(request, body, secret, verify)


# Разобрать полезную нагрузку веб-хука SonarQube
def parse_webhook_payload(body_bytes: bytes) -> Tuple[bool, Optional[Dict], str]:
    processor = SonarQubeWebhookProcessor(None)  # type: ignore
    return processor.parse_payload(body_bytes)
