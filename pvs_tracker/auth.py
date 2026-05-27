"""LDAP authentication (SonarQube-style: bind + search + user bind)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from ldap3 import ALL, SIMPLE, NTLM, Connection, Server
from ldap3.core.exceptions import LDAPException

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LdapIdentity:
    """Attributes resolved after successful LDAP bind."""
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def ldap_is_enabled() -> bool:
    return _env_bool("LDAP_ENABLED", False)


def ldap_auth_method() -> str:
    return os.getenv("LDAP_AUTH_METHOD", "simple").strip().lower()


def _ldap_server() -> Server:
    url = os.getenv("LDAP_URL", "ldap://localhost:389").strip()
    use_tls = _env_bool("LDAP_USE_TLS", False)
    return Server(url, get_info=ALL, use_ssl=use_tls)


def _new_flow_available() -> bool:
    """True if bind DN and password are set, enabling new search+bind flow."""
    return bool(os.getenv("LDAP_BIND_DN", "").strip() and os.getenv("LDAP_BIND_PASSWORD", "").strip())


def _get_config(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _search_and_bind(username: str, password: str) -> Optional[LdapIdentity]:
    """
    Новый метод: привязка сервисного аккаунта, поиск пользователя,
    затем проверка пароля через привязку DN пользователя.
    """
    server = _ldap_server()
    bind_dn = _get_config("LDAP_BIND_DN")
    bind_pw = _get_config("LDAP_BIND_PASSWORD")
    user_base = _get_config("LDAP_USER_BASE_DN")
    user_request_template = _get_config("LDAP_USER_REQUEST", "(&(objectClass=inetOrgPerson)(uid={login}))")
    real_name_attr = _get_config("LDAP_USER_REAL_NAME_ATTRIBUTE", "cn")
    email_attr = _get_config("LDAP_USER_EMAIL_ATTRIBUTE", "mail")
    follow_ref = _env_bool("LDAP_FOLLOW_REFERRALS", True)
    downcase = _env_bool("LDAP_DOWNCASE", False)

    if downcase:
        username = username.lower()

    # 1. Подключение сервисного аккаунта
    try:
        conn = Connection(
            server,
            user=bind_dn,
            password=bind_pw,
            authentication=SIMPLE,
            receive_timeout=int(os.getenv("LDAP_BIND_TIMEOUT", "10")),
            auto_bind=True,
            auto_referrals=follow_ref,
        )
    except LDAPException as exc:
        logger.warning("Service bind failed: %s", exc)
        return None

    # 2. Поиск пользователя по фильтру
    user_request = user_request_template.replace("{login}", username)
    try:
        conn.search(
            search_base=user_base,
            search_filter=user_request,
            attributes=[real_name_attr, email_attr, "givenName", "sn"],
            size_limit=1,
        )
    except LDAPException as exc:
        logger.warning("User search failed: %s", exc)
        conn.unbind()
        return None

    if not conn.entries:
        logger.info("No LDAP entry found for %s", username)
        conn.unbind()
        return None

    entry = conn.entries[0]
    user_dn = str(entry.entry_dn)

    # 3. Проверка пароля (привязка пользователя)
    try:
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            authentication=SIMPLE,
            receive_timeout=int(os.getenv("LDAP_BIND_TIMEOUT", "10")),
            auto_bind=True,
            auto_referrals=follow_ref,
        )
        user_conn.unbind()  # успешная привязка подтвердила пароль
    except LDAPException:
        logger.info("Password check failed for %s", username)
        conn.unbind()
        return None

    # 4. Извлечение атрибутов
    display_name = getattr(entry, real_name_attr, None)
    display_name = str(display_name) if display_name else None
    email = getattr(entry, email_attr, None)
    email = str(email) if email else None
    first_name = getattr(entry, "givenName", None)
    first_name = str(first_name) if first_name else None
    last_name = getattr(entry, "sn", None)
    last_name = str(last_name) if last_name else None

    conn.unbind()
    return LdapIdentity(
        username=username,
        email=email,
        display_name=display_name,
        first_name=first_name,
        last_name=last_name,
    )


def _old_flow_bind_dn(username: str) -> str:
    """Старый метод построения DN для прямой привязки."""
    method = ldap_auth_method()
    domain = os.getenv("LDAP_USER_DOMAIN", "").strip()
    if method == "ntlm":
        if domain:
            return f"{domain}\\{username}"
        return username
    if domain:
        return f"{username}@{domain}"
    return username


def _old_flow_authenticate(username: str, password: str) -> Optional[LdapIdentity]:
    """Старый метод: прямая привязка с построением DN."""
    login = username.strip()
    timeout = int(os.getenv("LDAP_BIND_TIMEOUT", "10"))
    method = ldap_auth_method()
    auth_type = NTLM if method == "ntlm" else SIMPLE
    bind_dn = _old_flow_bind_dn(login)

    try:
        server = _ldap_server()
        conn = Connection(
            server,
            user=bind_dn,
            password=password,
            authentication=auth_type,
            receive_timeout=timeout,
            auto_bind=False,
        )
        if not conn.bind():
            logger.info("LDAP bind failed for user %s", login)
            return None

        # Поиск атрибутов (опционально, как было)
        base_dn = os.getenv("LDAP_BASE_DN", "").strip()
        if base_dn:
            try:
                conn.search(
                    base_dn,
                    f"(sAMAccountName={login})",
                    attributes=["mail", "displayName", "givenName", "sn", "cn"],
                    size_limit=1,
                )
                if conn.entries:
                    entry = conn.entries[0]
                    attrs = {}
                    for key in ("mail", "displayName", "givenName", "sn", "cn"):
                        if hasattr(entry, key) and entry[key].value:
                            attrs[key] = str(entry[key].value)
                    email = attrs.get("mail")
                    display_name = attrs.get("displayName") or attrs.get("cn")
                    first_name = attrs.get("givenName")
                    last_name = attrs.get("sn")
                    return LdapIdentity(
                        username=login,
                        email=email,
                        display_name=display_name,
                        first_name=first_name,
                        last_name=last_name,
                    )
            except LDAPException as exc:
                logger.debug("LDAP attribute search failed for %s: %s", login, exc)

        # Если поиск не удался, возвращаем идентификатор без дополнительных атрибутов
        return LdapIdentity(username=login)

    except LDAPException as exc:
        logger.warning("LDAP error for user %s: %s", login, exc)
        return None


def ldap_authenticate(username: str, password: str) -> Optional[LdapIdentity]:
    """Проверка учётных данных через LDAP.
    Использует новый метод (bind+search) если задан LDAP_BIND_DN,
    иначе старый метод (прямая привязка).
    """
    if not ldap_is_enabled():
        return None
    if not username.strip() or not password:
        return None

    if _new_flow_available():
        return _search_and_bind(username, password)
    else:
        return _old_flow_authenticate(username, password)
