"""Admin detection by client IP/hostname (CI project management)."""

from __future__ import annotations

import logging
import socket
from functools import lru_cache
from typing import TypedDict

from fastapi import Request

from pvs_tracker.ci_config import ci_settings

logger = logging.getLogger(__name__)


class ClientInfo(TypedDict):
    ip: str
    hostname: str


@lru_cache(maxsize=1)
def get_admin_ips() -> list[str]:
    return ["127.0.0.1", "::1"] + [
        ip.strip() for ip in ci_settings.ADMIN_IPS.split(",") if ip.strip()
    ]


@lru_cache(maxsize=1)
def get_admin_hostnames() -> list[str]:
    return [hn.strip() for hn in ci_settings.ADMIN_HOSTNAMES.split(",") if hn.strip()]


def get_client_info(request: Request) -> ClientInfo:
    client_ip = request.client.host if request.client else "unknown"
    try:
        client_hostname = socket.gethostbyaddr(client_ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        client_hostname = "Unknown"
    return {"ip": client_ip, "hostname": client_hostname}


def is_admin(request: Request) -> bool:
    info = get_client_info(request)
    return info["ip"] in get_admin_ips() or info["hostname"] in get_admin_hostnames()
