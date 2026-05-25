# Модуль интеграции Jira

from typing import Optional
from jira import JIRA

from app.services.jira_service import (
    get_jira_client as _get_jira_client,
    check_exist_task as _check_exist_task,
    create_jira_issue as _create_jira_issue,
    add_comment as _add_comment,
)

from app.logging_config import get_logger

logger = get_logger(__name__)


# Обратная совместимость - прямой экспорт функций

# Получить экземпляр клиента Jira
def get_jira_client() -> Optional[JIRA]:
    return _get_jira_client()


# Проверка, существует ли проблема Jira для проблемы SonarQube
def check_exist_task(sonar_issue_key: str) -> bool:
    return _check_exist_task(sonar_issue_key)


# Создание бага в Jira для issue SonarQube
def create_jira_issue(
    project,                    # Объект проекта
    summary: str,               # Заголовок
    description: str,           # Описание
    sonarqube_issue_id: str,    # SonarQube issue ID
    issue_type: str = "Bug"     # Issue type
):
    return _create_jira_issue(
        project=project,
        summary=summary,
        description=description,
        sonarqube_issue_id=sonarqube_issue_id,
        issue_type=issue_type
    )   # Созданная проблема или None


# Добавление комментария к багу Jira для исправленной issue в SonarQube
def add_comment(sonar_issue_key: str) -> bool:
    return _add_comment(sonar_issue_key)
