"""Authentication service with JWT token support, LDAP, and RBAC."""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from pvs_tracker.auth import LdapIdentity, ldap_authenticate, ldap_auth_method, ldap_is_enabled
from pvs_tracker.db import engine
from pvs_tracker.models import User, UserRole
from pvs_tracker.security import hash_password, verify_password

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", "dev-change-me"))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _normalize_username(username: str) -> str:
    return username.strip()


def _authenticate_local(user: User, password: str) -> bool:
    if user.auth_provider != "local":
        return False
    if not user.password_hash:
        return False
    return verify_password(password, user.password_hash)


def provision_ldap_user(session: Session, identity: LdapIdentity) -> User:
    """Create or update a user record after successful LDAP bind."""
    user = session.exec(select(User).where(User.username == identity.username)).first()
    if user:
        user.auth_provider = "ldap"
        user.display_name = identity.display_name or user.display_name
        if identity.email:
            user.email = identity.email
        if identity.first_name:
            user.first_name = identity.first_name
        if identity.last_name:
            user.last_name = identity.last_name
    else:
        user = User(
            username=identity.username,
            email=identity.email,
            display_name=identity.display_name,
            first_name=identity.first_name,
            last_name=identity.last_name,
            password_hash=None,
            auth_provider="ldap",
            role=UserRole.VIEWER,
            is_active=True,
        )
        session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_credentials(
    session: Session,
    username: str,
    password: str,
) -> Optional[User]:
    """Authenticate via local password and/or LDAP (unified entry point)."""
    login = _normalize_username(username)
    if not login or not password:
        return None

    user = session.exec(select(User).where(User.username == login)).first()

    if user and user.auth_provider == "local":
        if not user.is_active:
            return None
        if not _authenticate_local(user, password):
            return None
        user.last_login = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    if ldap_is_enabled() and (user is None or user.auth_provider == "ldap"):
        identity = ldap_authenticate(login, password)
        if not identity:
            return None
        user = provision_ldap_user(session, identity)
        if not user.is_active:
            return None
        user.last_login = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    if user and not ldap_is_enabled():
        if not user.is_active or not _authenticate_local(user, password):
            return None
        user.last_login = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return None


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """Backward-compatible alias for API login."""
    return authenticate_credentials(session, username, password)


def create_user(
    session: Session,
    username: str,
    password: str,
    email: Optional[str] = None,
    role: UserRole = UserRole.VIEWER,
    *,
    auth_provider: str = "local",
) -> User:
    """Create a new user with hashed password (local accounts only)."""
    user = User(
        username=_normalize_username(username),
        email=email,
        password_hash=hash_password(password),
        auth_provider=auth_provider,
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def establish_session(request: Request, user: User) -> None:
    """Store authenticated user in the session cookie."""
    request.session["user_id"] = user.id
    request.session["user"] = user.username


def clear_session(request: Request) -> None:
    request.session.clear()


def _load_user_by_session(request: Request, session: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = session.get(User, int(user_id))
        if user and user.is_active:
            return user

    username = request.session.get("user")
    if username:
        user = session.exec(select(User).where(User.username == str(username))).first()
        if user and user.is_active:
            if user.id is not None:
                request.session["user_id"] = user.id
            return user
    return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """Get current user from session or JWT token."""
    with Session(engine) as session:
        user = _load_user_by_session(request, session)
        if user:
            return user

    if credentials:
        try:
            payload = decode_token(credentials.credentials)
            user_id = payload.get("sub")
            if user_id:
                with Session(engine) as session:
                    user = session.get(User, int(user_id))
                    if user and user.is_active:
                        return user
        except HTTPException:
            pass
        except Exception:
            pass

    return None


def require_auth(user: Optional[User] = Depends(get_current_user)) -> User:
    """Require authentication - raise 401 if not authenticated."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    return user


def require_role(required_role: UserRole):
    """Require a specific role or higher."""

    def _require_role(user: User = Depends(require_auth)) -> User:
        role_hierarchy = {UserRole.VIEWER: 0, UserRole.USER: 1, UserRole.ADMIN: 2}
        if role_hierarchy.get(user.role, 0) < role_hierarchy.get(required_role, 0):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _require_role


def require_admin(user: User = Depends(require_auth)) -> User:
    """Require admin role."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_user_project_role(user: User, project_id: int) -> UserRole:
    """Get user's role for a specific project (project-level overrides global role)."""
    with Session(engine) as session:
        from pvs_tracker.models import ProjectMember

        membership = session.exec(
            select(ProjectMember).where(
                ProjectMember.user_id == user.id,
                ProjectMember.project_id == project_id,
            )
        ).first()
        if membership:
            return membership.role
    return user.role


def can_access_project(user: User, project_id: int, required_role: UserRole = UserRole.VIEWER) -> bool:
    """Check if user can access a project with the required role."""
    role_hierarchy = {UserRole.VIEWER: 0, UserRole.USER: 1, UserRole.ADMIN: 2}
    user_role = get_user_project_role(user, project_id)
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)


def can_modify_project(user: User, project_id: int) -> bool:
    """Check if user can modify a project (admin or project USER+)."""
    return can_access_project(user, project_id, UserRole.USER) or user.role == UserRole.ADMIN


def get_auth_settings_public() -> dict[str, object]:
    """Read-only auth configuration for admin UI."""
    return {
        "ldap_enabled": ldap_is_enabled(),
        "ldap_auth_method": ldap_auth_method(),
    }
