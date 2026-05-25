"""
Services package.

Business logic services for:
- Repository operations (Git/TFVC)
- Jenkins CI/CD
- SonarQube webhook processing
- Jira integration
"""

from app.services.repository_service import (
    check_git_changes,
    check_tfvc_changes,
    check_tfvc_merge,
    is_c_file,
    is_cmake_file,
)

from app.services.jenkins_service import (
    JenkinsService,
    get_jenkins_service,
    trigger_jenkins_build,
)

from app.services.sonarqube_webhook_service import (
    SonarQubeWebhookProcessor,
    process_sonarqube_webhook,
    verify_webhook_signature,
    parse_webhook_payload,
)

from app.services.jira_service import (
    JiraService,
    get_jira_service,
    get_jira_client,
    check_exist_task,
    create_jira_issue,
    add_comment,
)

__all__ = [
    # Repository service
    'check_git_changes',
    'check_tfvc_changes',
    'check_tfvc_merge',
    'is_c_file',
    'is_cmake_file',
    'get_head_commit_git',
    'get_latest_changeset_tfvc',
    
    # Jenkins service
    'JenkinsService',
    'get_jenkins_service',
    'trigger_jenkins_build',
    
    # SonarQube webhook service
    'SonarQubeWebhookProcessor',
    'process_sonarqube_webhook',
    'verify_webhook_signature',
    'parse_webhook_payload',
    
    # Jira service
    'JiraService',
    'get_jira_service',
    'get_jira_client',
    'check_exist_task',
    'create_jira_issue',
    'add_comment',
]
