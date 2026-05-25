# Утилиты и вспомогательные функции администратора

from fastapi import Request
from functools import lru_cache
from typing import Dict

from app.config import settings


@lru_cache(maxsize=1000)
# Получение кэшированного списка IP-адресов администраторов
def get_admin_ips() -> list:
    return ["127.0.0.1"] + [ip.strip() for ip in settings.ADMIN_IPS.split(",")]


@lru_cache(maxsize=1000)
# Получение кэшированного списка имён хостов администраторов
def get_admin_hostnames() -> list:
    return [hn.strip() for hn in settings.ADMIN_HOSTNAMES.split(",")]


# Получение информации о клиенте (IP и имя хоста)
def get_client_info(request: Request) -> Dict[str, str]:
    client_ip = request.client.host

    # Попытка получить имя хоста (может не работать в некоторых окружениях)
    try:
        import socket
        client_hostname = socket.gethostbyaddr(client_ip)[0]
    except (socket.herror, socket.gaierror, Exception):
        client_hostname = "Unknown"

    return {
        "ip": client_ip,
        "hostname": client_hostname
    }


# Проверка, является ли запрос от администратора
def is_admin(request: Request) -> bool:
    # Статус администратора определяется по IP-адресу или имени хоста, соответствующим настроенным спискам администраторов.
    client_info = get_client_info(request)

    return (client_info["ip"] in get_admin_ips() or 
            client_info["hostname"] in get_admin_hostnames())
