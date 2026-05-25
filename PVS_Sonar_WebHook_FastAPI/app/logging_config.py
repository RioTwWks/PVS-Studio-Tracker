"""
Централизованная конфигурация логирования.

Предоставляет:
- Единую настройку логирования для всех модулей
- Ежедневную ротацию с автоматической очисткой старых логов
- Структурированное логирование с контекстом (repo_type, repo_name, project, etc.)
- Раздельные логгеры для разных компонентов
- Вывод в консоль и файл
- Настраиваемые уровни логирования
"""

import logging
import os
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any
import glob


# Шаблоны формата логов
FORMAT_DETAILED = '%(asctime)s [%(levelname)s] [%(name)s] [%(repo_type)s/%(repo_name)s] %(message)s'
FORMAT_SIMPLE = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
FORMAT_CONSOLE = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Период хранения логов по умолчанию (дни)
DEFAULT_LOG_RETENTION_DAYS = 30

# Уровни логирования
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


# Добавляет значения контекста по умолчанию в записи лога
class ContextFilter(logging.Filter):
    # Гарантирует, что все записи лога имеют поля repo_type и repo_name, даже если они не были явно предоставлены.

    DEFAULT_CONTEXT = {
        'repo_type': 'SYSTEM',
        'repo_name': 'UNKNOWN',
    }

    def filter(self, record):
        # Добавление контекста по умолчанию если отсутствует
        for key, default_value in self.DEFAULT_CONTEXT.items():
            if not hasattr(record, key):
                setattr(record, key, default_value)
        return True


# Обработчик файла с ежедневной ротацией и автоматической очисткой старых логов
class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    Возможности:
    - Ротация логов в полночь (проверка при каждой записи)
    - Хранение логов в течение указанного периода
    - Автоматическая очистка старых логов
    - Автоматическое создание структуры директорий
    """

    def __init__(
        self,
        filename: str,
        retention_days: int = DEFAULT_LOG_RETENTION_DAYS,
        encoding: str = 'utf-8',
        delay: bool = False
    ):
        # Создание директории если не существует
        log_dir = Path(filename).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Инициализация родителя с ежедневной ротацией
        super().__init__(
            filename=filename,
            when='D',  # Ежедневная ротация
            interval=1,
            backupCount=retention_days,
            encoding=encoding,
            delay=delay,
            utc=False,
            atTime=None
        )

        self.retention_days = retention_days
        self.base_filename = filename

        # Начальная очистка старых логов
        self.cleanup_old_logs()

    # Проверяет необходимость ротации при каждой записи
    def shouldRollover(self, record):
        # Переопределяем метод для проверки даты при каждой записи лога, а не только в определённое время
        # Получаем текущую дату
        current_time = datetime.now()
        current_date = current_time.date()

        # Получаем дату последнего ролловера
        if hasattr(self, '_last_rollover_date'):
            last_rollover_date = self._last_rollover_date
        else:
            # Первый запуск - инициализируем датой создания файла
            try:
                file_stat = os.stat(self.baseFilename)
                file_mtime = datetime.fromtimestamp(file_stat.st_mtime)
                last_rollover_date = file_mtime.date()
            except:
                last_rollover_date = current_date

            self._last_rollover_date = last_rollover_date

        # Если дата изменилась - делаем ротацию
        if current_date != last_rollover_date:
            self._last_rollover_date = current_date
            return True

        return False

    # Удаление файлов логов старше периода хранения
    def cleanup_old_logs(self):
        try:
            # Получение директории и шаблона имени файла
            log_dir = Path(self.base_filename).parent
            filename_pattern = Path(self.base_filename).name.split('.')[0]

            # Расчёт даты отсечения
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)

            # Поиск всех совпадающих файлов логов
            pattern = str(log_dir / f"{filename_pattern}*")
            log_files = glob.glob(pattern)

            # Удаление старых файлов
            removed_count = 0
            for log_file in log_files:
                file_path = Path(log_file)
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                if file_mtime < cutoff_date:
                    try:
                        file_path.unlink()
                        removed_count += 1
                    except OSError as e:
                        logging.warning(f"Не удалось удалить старый файл лога {log_file}: {e}")

            if removed_count > 0:
                logging.info(f"Очищено {removed_count} старых файлов логов")

        except Exception as e:
            logging.warning(f"Ошибка при очистке логов: {e}")

    # Расширение ротации родителя для очистки старых логов
    def doRollover(self):
        super().doRollover()
        # Очистка старых логов после ротации
        self.cleanup_old_logs()


# Настройка корневого логгера с обработчиками файла и консоли
def setup_logging(
    log_level: str = 'INFO',                            # Глобальный уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    log_dir: str = 'logs',                              # Директория для файлов логов
    retention_days: int = DEFAULT_LOG_RETENTION_DAYS,   # Количество дней хранения файлов логов
    console_output: bool = True,                        # Включить вывод в консоль
    context_filter: bool = True                         # Добавить фильтр контекста со значениями по умолчанию
) -> None:

    # Получение или создание корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVELS.get(log_level.upper(), logging.INFO))

    # Очистка существующих обработчиков (важно для сценариев перезагрузки)
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Создание директории логов
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Создание форматтера
    formatter = logging.Formatter(FORMAT_DETAILED, datefmt=DATE_FORMAT)

    # Обработчик основного лога приложения (ежедневная ротация)
    main_log_file = log_path / 'app.log'
    main_handler = DailyRotatingFileHandler(
        filename=str(main_log_file),
        retention_days=retention_days
    )
    main_handler.setFormatter(formatter)
    main_handler.setLevel(LOG_LEVELS.get(log_level.upper(), logging.INFO))
    root_logger.addHandler(main_handler)

    # Обработчик консоли (если включено)
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(FORMAT_CONSOLE, datefmt=DATE_FORMAT))
        console_handler.setLevel(LOG_LEVELS.get(log_level.upper(), logging.INFO))
        root_logger.addHandler(console_handler)

    # Добавление фильтра контекста
    if context_filter:
        context = ContextFilter()
        for handler in root_logger.handlers:
            handler.addFilter(context)

    # Логирование сообщения о запуске
    root_logger.info(
        "Логирование инициализировано",
        extra={
            'repo_type': 'SYSTEM',
            'repo_name': 'INIT'
        }
    )


# Получить или создать логгер с опциональным выделенным обработчиком файла
def get_logger(
    name: str,                          # Имя логгера (обычно __name__)
    log_dir: Optional[str] = None,      # Опциональная выделенная директория логов (создаёт поддиректорию)
    log_level: Optional[str] = None,    # Опциональный конкретный уровень логирования для этого логгера
    add_file_handler: bool = False      # Добавить выделенный обработчик файла для этого логгера
) -> logging.Logger:

    logger = logging.getLogger(name)

    # Установка конкретного уровня логирования если предоставлен
    if log_level:
        logger.setLevel(LOG_LEVELS.get(log_level.upper(), logging.INFO))

    # Добавление выделенного обработчика файла если запрошено
    if add_file_handler and log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        log_file = log_path / f"{name.replace('.', '_')}.log"
        file_handler = DailyRotatingFileHandler(filename=str(log_file))
        file_handler.setFormatter(logging.Formatter(FORMAT_DETAILED, datefmt=DATE_FORMAT))

        logger.addHandler(file_handler)

    return logger   # Настроенный экземпляр логгера


# Получить логгер для конкретного компонента с предустановленным контекстом
def get_component_logger(
    component: str,                 # Имя компонента (webhook, sonarqube, jira, etc.)
    repo_type: str = 'SYSTEM',      # Тип репозитория (Git, TFVC, etc.)
    repo_name: str = 'UNKNOWN'      # Имя репозитория/проекта
 ) -> logging.LoggerAdapter:

    logger = get_logger(f"app.{component}")

    # Создание адаптера с предустановленным контекстом
    adapter = logging.LoggerAdapter(logger, {
        'repo_type': repo_type,
        'repo_name': repo_name
    })

    return adapter  # LoggerAdapter с предустановленным контекстом


# Менеджер контекста для временного контекста лога
class LogContext:

    def __init__(self, **context):
        self.context = context
        self.old_context = {}

    def __enter__(self):
        # Сохранение текущего контекста
        self.old_context = getattr(logging, '_log_context', {})

        # Объединение с новым контекстом
        new_context = {**self.old_context, **self.context}
        logging._log_context = new_context

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Восстановление предыдущего контекста
        if self.old_context:
            logging._log_context = self.old_context
        else:
            delattr(logging, '_log_context')


# Логирование сообщения с дополнительным контекстом
def log_with_context(
    logger: logging.Logger,                     # Экземпляр логгера
    level: int,                                 # Уровень логирования (logging.INFO, logging.ERROR, etc.)
    message: str,                               # Сообщение лога
    context: Optional[Dict[str, Any]] = None    # Словарь дополнительного контекста
):
    extra = context or {}

    # Объединение с глобальным контекстом если существует
    global_context = getattr(logging, '_log_context', {})
    extra = {**global_context, **extra}

    logger.log(level, message, extra=extra)


# Вспомогательные функции для распространённых шаблонов логирования

# Логирование запуска приложения/сервиса
def log_startup(logger: logging.Logger, service_name: str):
    logger.info(
        f"Запуск {service_name}",
        extra={'repo_type': 'SYSTEM', 'repo_name': 'STARTUP'}
    )


# Логирование остановки приложения/сервиса
def log_shutdown(logger: logging.Logger, service_name: str):
    logger.info(
        f"Остановка {service_name}",
        extra={'repo_type': 'SYSTEM', 'repo_name': 'SHUTDOWN'}
    )


# Логирование ошибки с полным traceback и контекстом
def log_error_with_traceback(logger: logging.Logger, message: str, exc: Exception, **context):
    logger.error(
        message,
        extra={
            'repo_type': context.get('repo_type', 'SYSTEM'),
            'repo_name': context.get('repo_name', 'ERROR'),
            'exception': str(exc)
        },
        exc_info=True
    )


# Инициализация логирования при импорте модуля (может быть переопределено)
# Вызовите setup_logging() в вашем главном приложении
setup_logging()
