"""CI orchestration settings (Jenkins, TFS webhooks, Jira)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class CISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    WEBHOOK_USERNAME: str = "builder"
    WEBHOOK_PASSWORD: str = "password"

    JENKINS_URL: str = "https://newbuilder"
    JENKINS_JOB_NAME: str = "Test_FastAPI"
    JENKINS_USERNAME: str = "admin"
    JENKINS_TOKEN: str = "jenkins_token"

    JIRA_URL: str = "https://jira.example.com"
    JIRA_USERNAME: str = "admin"
    JIRA_PASSWORD: str = "admin"
    JIRA_VERIFY_CERT: str = ""
    JIRA_FINGERPRINT_FIELD: str = "customfield_12205"

    TFS_BASE_URL: str = "http://qtfs:8080/tfs/QUIK"

    ADMIN_IPS: str = "127.0.0.1"
    ADMIN_HOSTNAMES: str = "localhost"

    CI_TEMP_DIR: str = "temp_repos"


ci_settings = CISettings()
