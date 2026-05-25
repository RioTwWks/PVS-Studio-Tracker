from pydantic_settings import BaseSettings


# Настройки приложения из переменных окружения
class Settings(BaseSettings):

    # SonarQube
    SONARQUBE_URL: str = "http://qube"
    SONARQUBE_TOKEN: str = "sonarqube_token"

    SONARQUBE_WEBHOOK_SECRET: str = "default_secret_here"
    SONARQUBE_VERIFY_SIGNATURE: bool = False  # По умолчанию отключаем для тестов
    SONARQUBE_STRICT_SIGNATURE: bool = False  # Строгая проверка подписи

    # Настройки Basic Auth (если требуется)
    SONARQUBE_REQUIRE_AUTH: bool = False  # Требовать ли Basic Auth
    SONARQUBE_USERNAME: str = "admin"
    SONARQUBE_PASSWORD: str = "admin"

    # Веб-хуки
    WEBHOOK_USERNAME: str = "admin"
    WEBHOOK_PASSWORD: str = "admin"

    # Jenkins
    JENKINS_URL: str = "https://newbuilder"
    JENKINS_JOB_NAME: str = "Test_FastAPI"
    JENKINS_USERNAME: str = "admin"
    JENKINS_TOKEN: str = "jenkins_token"

    # Jira
    JIRA_USERNAME: str = "admin"
    JIRA_PASSWORD: str = "admin"
    JIRA_URL: str = "https://salta:8443"

    # Администраторы
    ADMIN_IPS: str = "192.168.32.139,192.168.32.133,192.168.32.79"
    ADMIN_HOSTNAMES: str = "pc-ieme,pc-vvor,pc-aalex"

    # Настройки email (если ещё нет)
    EMAIL_FROM: str = "sonar@arqa.local"
    EMAIL_TO: str = "ieme@arqa.ru"
    SMTP_HOST: str = "192.168.47.116"
    SMTP_PORT: int = 25

    # Настройки сканера
    SCAN_SOURCE_DIR: str = r"\\qlen\SoftPile\quik\2Test"            # Откуда собирать файлы
    SCAN_LOG_DIR: str = r"D:\SAST\PVS_Sonar_WebHook_FastAPI\temp"   # Куда сохранить список файлов (None = временный)
    SCAN_MAX_AGE_DAYS: int = 64                                      # Период в днях
    SCAN_TARGET_EXTENSIONS: list = [".exe", ".dll"]
    SCAN_EXPECTED_CERT_SUBJECT: str = "CN=ARQA Technologies LLC"    # Ожидаемый Subject сертификата (подстрока)

    # Путь к временной папке проекта (для копирования файлов)
    TEMP_DIR: str = "D:\\SAST\\PVS_Sonar_WebHook_FastAPI\\temp"

    # Полный путь к signtool.exe (лежит в той же папке)
    SIGNTOOL_PATH: str = "D:\\SAST\\PVS_Sonar_WebHook_FastAPI\\temp\\signtool.exe"

    class Config:
        env_file = ".env"


# Глобальный экземпляр настроек
settings = Settings()
