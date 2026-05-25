"""
Сервис Jira для операций отслеживания задач.

Обрабатывает:
- Инициализация клиента Jira и управление подключением
- Поиск спринтов
- Создание и обновление задач
- Управление наблюдателями
"""

from typing import Optional, List
from jira import JIRA
from jira.resources import Issue

from app.logging_config import get_logger
from app.config import settings

logger = get_logger(__name__)


# Сервис для операций Jira
class JiraService:

    # Инициализация сервиса Jira
    def __init__(self):
        self._client: Optional[JIRA] = None
        self._server_url = settings.JIRA_URL
        self._username = settings.JIRA_USERNAME
        self._password = settings.JIRA_PASSWORD
        self._verify_cert = 'app\\atlas-arqa-ru-chain.pem'

    @property
    # Получить или создать клиент Jira
    def client(self) -> Optional[JIRA]:
        if self._client is None:
            self._initialize_client()
        return self._client

    # Инициализация подключения клиента Jira
    def _initialize_client(self) -> None:
        try:
            self._client = JIRA(
                options={
                    'server': self._server_url,
                    'verify': self._verify_cert,
                    'check_update': False
                },
                basic_auth=(self._username, self._password),
                max_retries=1
            )
            logger.info("Клиент Jira успешно инициализирован")
        except Exception as e:
            logger.error(f"Ошибки авторизации в Jira:\n{e}")
            self._client = None

    # Переподключиться к серверу Jira
    def reconnect(self) -> bool:
        self._client = None
        self._initialize_client()
        return self._client is not None

    # Проверить подключение к Jira
    def is_connected(self) -> bool:
        return self._client is not None

    # Получить ключ проекта Jira по имени
    def get_project_key(self, project_name: str) -> Optional[str]:
        if not self.client:
            logger.error("Клиент Jira не инициализирован")
            return None

        try:
            all_projects = self.client.projects()

            for project in all_projects:
                # Проверка по ключу проекта
                if project.key == project_name:
                    logger.info(f"Найден проект по ключу: {project.key}")
                    return project.key
                # Проверка по имени проекта
                elif project.name == project_name:
                    logger.info(f"Найден проект по имени: {project.key}")
                    return project.key

            logger.warning(f"Проект '{project_name}' не найден в Jira")
            return None

        except Exception as e:
            logger.error(f"Ошибка получения ключа проекта: {e}")
            return None

    # Получить активный спринт для проекта
    def get_active_sprint(
        self,
        project_key: str,               # Ключ проекта Jira
        version: Optional[str] = None   # Опциональная версия для сопоставления с именем спринта
    ) -> tuple[Optional[str], Optional[str]]:
        if not self.client:
            return None, None

        try:
            # Поиск доски, привязанной к проекту
            boards = self.client.boards(projectKeyOrID=project_key)
            if not boards:
                logger.error(f"Не найдено досок для проекта {project_key}")
                return None, None

            board = boards[0]

            # Получение всех спринтов доски
            all_sprints = self.client.sprints(board.id)

            # Фильтрация только активных спринтов
            active_sprints = [s for s in all_sprints if s.state == 'active']

            if not active_sprints:
                logger.warning(f"В проекте '{project_key}' нет активных спринтов")
                return None, None

            # Поиск спринта, соответствующего версии
            if version:
                for sprint in active_sprints:
                    if version in sprint.name:
                        logger.info(f"Найден подходящий спринт: {sprint.name} (ID: {sprint.id})")
                        return str(sprint.id), sprint.name

            # Возврат первого активного спринта если нет совпадения версии
            sprint = active_sprints[0]
            logger.info(f"Использование спринта: {sprint.name} (ID: {sprint.id})")
            return str(sprint.id), sprint.name

        except Exception as e:
            logger.error(f"Ошибка получения активного спринта: {e}")
            return None, None

    # Создать новую задачу Jira
    def create_issue(
        self,
        project_key: str,                       # Ключ проекта Jira
        summary: str,                           # Краткое описание задачи
        description: str,                       # Описание задачи
        issue_type: str = "Bug",                # Тип задачи (Bug, Task, etc.)
        sprint_id: Optional[str] = None,        # Опциональный ID спринта
        assignee: Optional[str] = None,         # Опциональный исполнитель
        custom_fields: Optional[dict] = None,   # Опциональные пользовательские поля
        version: Optional[str] = None           # Опциональная версия (Affected Version)
    ) -> Optional[Issue]:
        if not self.client:
            logger.error("Клиент Jira не подключён")
            return None

        try:
            issue_fields = {
                'project': {'key': project_key},
                'summary': summary,
                'description': description,
                'issuetype': {'name': issue_type},
            }

            if assignee:
                issue_fields['assignee'] = {'name': assignee}

            # Получаем версии проекта и устанавливаем Affected Version
            if version:
                try:
                    project_versions = self.client.project_versions(project_key)
                    # Ищем версию по имени
                    matching_version = None
                    for v in project_versions:
                        if v.name == version:
                            matching_version = v
                            break

                    if matching_version:
                        issue_fields['versions'] = [{'id': matching_version.id}]
                        logger.info(f"Установлена Affected Version: {version} (ID: {matching_version.id})")
                    else:
                        # Если версия не найдена, используем последнюю доступную
                        if project_versions:
                            last_version = project_versions[-1]
                            issue_fields['versions'] = [{'id': last_version.id}]
                            logger.info(f"Версия {version} не найдена. Использована последняя: {last_version.name}")
                        else:
                            logger.warning(f"В проекте {project_key} нет версий. Affected Version не установлена.")
                except Exception as e:
                    logger.error(f"Ошибка получения версий проекта: {e}")

            if custom_fields:
                issue_fields.update(custom_fields)

            issue = self.client.create_issue(**issue_fields)
            logger.info(f"Создана задача: {issue.key}")

            # Добавление в спринт если указан
            if sprint_id:
                try:
                    self.client.add_issues_to_sprint(sprint_id, [issue.key])
                    logger.info(f"Добавлено {issue.key} в спринт {sprint_id}")
                except Exception as e:
                    logger.warning(f"Не удалось добавить задачу в спринт: {e}")

            return issue

        except Exception as e:
            logger.error(f"Ошибка создания задачи: {e}", exc_info=True)
            return None

    # Добавить наблюдателя к задаче
    def add_watcher(self, issue: Issue, username: str) -> bool:
        if not self.client:
            return False

        try:
            self.client.add_watcher(issue, username)
            logger.info(f"Добавлен наблюдатель {username} к {issue.key}")
            return True
        except Exception as e:
            logger.warning(f"Не удалось добавить наблюдателя: {e}")
            return False

    # Добавить комментарий к задаче
    def add_comment(self, issue_key: str, comment: str) -> bool:
        if not self.client:
            return False

        try:
            issue = self.client.issue(issue_key)
            self.client.add_comment(issue, comment)
            logger.info(f"Добавлен комментарий к {issue_key}")
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления комментария: {e}")
            return False

    # Поиск задач с использованием JQL
    def search_issues(self, jql: str, max_results: int = 50) -> List[Issue]:
        if not self.client:
            return []

        try:
            issues = self.client.search_issues(jql, maxResults=max_results)
            return issues
        except Exception as e:
            logger.error(f"Ошибка поиска задач: {e}")
            return []

    # Получить задачу по ключу
    def get_issue(self, issue_key: str) -> Optional[Issue]:
        if not self.client:
            return None

        try:
            return self.client.issue(issue_key)
        except Exception as e:
            logger.error(f"Ошибка получения задачи: {e}")
            return None


# Глобальный экземпляр сервиса
_jira_service: Optional[JiraService] = None


# Получить или создать экземпляр сервиса Jira
def get_jira_service() -> JiraService:
    global _jira_service
    if _jira_service is None:
        _jira_service = JiraService()
    return _jira_service


# Получить клиент Jira (обратная совместимость)
def get_jira_client() -> Optional[JIRA]:
    service = get_jira_service()
    return service.client


# Проверить, существует ли задача Jira для проблемы SonarQube
def check_exist_task(sonar_issue_key: str) -> bool:
    service = get_jira_service()
    if not service.client:
        return False

    try:
        # Используем оператор ~ (contains) вместо = так как поле не поддерживает точное сравнение
        jql = f'type=bug and "SonarQube Issue ID"~"{sonar_issue_key}"'
        issues = service.search_issues(jql, max_results=1)
        return len(issues) > 0
    except Exception as e:
        logger.error(f"Ошибка проверки существования задачи: {e}")
        return False


# Создать задачу Jira для проблемы SonarQube
def create_jira_issue(
    project,                    # Объект проекта с jira_project
    summary: str,               # Краткое описание
    description: str,           # Описание
    sonarqube_issue_id: str,    # ID проблемы SonarQube
    issue_type: str = "Bug"     # Тип задачи
) -> Optional[Issue]:
    service = get_jira_service()

    # Получение ключа проекта
    project_key = service.get_project_key(project.jira_project)
    if not project_key:
        return None

    # Получение активного спринта
    sprint_id, sprint_name = service.get_active_sprint(
        project_key,
        project.version
    )

    # Пользовательские поля для интеграции SonarQube
    custom_fields = {'customfield_12205': sonarqube_issue_id}

    # Создание задачи с версией (Affected Version)
    issue = service.create_issue(
        project_key=project_key,
        summary=summary,
        description=description,
        issue_type=issue_type,
        sprint_id=sprint_id,
        assignee=None,  # TODO: Реализовать поиск исполнителя
        custom_fields=custom_fields,
        version=project.version  # Передаём версию для Affected Version
    )

    return issue


# Добавить комментарий к задаче Jira для исправленной проблемы SonarQube
def add_comment(sonar_issue_key: str) -> bool:
    service = get_jira_service()

    # Поиск задачи Jira по SonarQube ID (используем ~ вместо =)
    jql = f'type=bug and "SonarQube Issue ID"~"{sonar_issue_key}"'
    issues = service.search_issues(jql, max_results=1)

    if not issues:
        logger.warning(f"Не найдена задача Jira для проблемы SonarQube {sonar_issue_key}")
        return False

    comment = f"Исправлено в SonarQube: {sonar_issue_key}"
    return service.add_comment(issues[0], comment)
