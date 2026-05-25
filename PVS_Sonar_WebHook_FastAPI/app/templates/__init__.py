# Настройка шаблона и помощники.

from fastapi.templating import Jinja2Templates
from functools import lru_cache


@lru_cache()
# Получить кэшированный экземпляр Jinja2Templates.
def get_templates() -> Jinja2Templates:
    return Jinja2Templates(directory="app/templates")   # Экземпляр Jinja2Templates настроен для каталога приложений/шаблонов
