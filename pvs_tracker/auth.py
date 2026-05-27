"""LDAP authentication (SIMPLE / NTLM) — configuration via .env only."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from ldap3 import ALL, NTLM, SIMPLE, Connection, Server
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


def _bind_user_dn(username: str) -> str:
    method = ldap_auth_method()
    domain = os.getenv("LDAP_USER_DOMAIN", "").strip()
    if method == "ntlm":
        if domain:
            return f"{domain}\\{username}"
        return username
    if domain:
        return f"{username}@{domain}"
    return username


def _search_attributes(conn: Connection, username: str) -> dict[str, str]:
    base_dn = os.getenv("LDAP_BASE_DN", "").strip()
    if not base_dn:
        return {}
    try:
        conn.search(
            base_dn,
            f"(sAMAccountName={username})",
            attributes=["mail", "displayName", "givenName", "sn", "cn"],
            size_limit=1,
        )
        if not conn.entries:
            conn.search(
                base_dn,
                f"(uid={username})",
                attributes=["mail", "displayName", "givenName", "sn", "cn"],
                size_limit=1,
            )
        if not conn.entries:
            return {}
        entry = conn.entries[0]
        attrs: dict[str, str] = {}
        for key in ("mail", "displayName", "givenName", "sn", "cn"):
            if hasattr(entry, key) and entry[key].value:
                attrs[key] = str(entry[key].value)
        return attrs
    except LDAPException as exc:
        logger.debug("LDAP attribute search failed for %s: %s", username, exc)
        return {}


def ldap_authenticate(username: str, password: str) -> Optional[LdapIdentity]:
    """Validate credentials against LDAP. Returns identity or None on failure."""
    if not ldap_is_enabled():
        return None
    if not username.strip() or not password:
        return None

    login = username.strip()
    timeout = int(os.getenv("LDAP_BIND_TIMEOUT", "10"))
    method = ldap_auth_method()
    auth_type = NTLM if method == "ntlm" else SIMPLE
    bind_dn = _bind_user_dn(login)

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

        attrs = _search_attributes(conn, login)
        email = attrs.get("mail")
        display_name = attrs.get("displayName") or attrs.get("cn")
        return LdapIdentity(
            username=login,
            email=email,
            display_name=display_name,
            first_name=attrs.get("givenName"),
            last_name=attrs.get("sn"),
        )
    except LDAPException as exc:
        logger.warning("LDAP error for user %s: %s", login, exc)
        return None
