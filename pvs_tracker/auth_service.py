"""Authentication service with JWT token support and RBAC."""

import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from pvs_tracker.models import User, UserRole
from pvs_tracker.security import hash_password, verify_password
from pvs_tracker.db import engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", "dev-change-me"))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

security = HTTPBearer(auto_error=False)

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("pvs_tracker.auth")

# ---------------------------------------------------------------------------
# Token generation and validation
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    # 🔐 Гарантируем, что 'sub' — строка (требование PyJWT/RFC 7519)
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        logger.debug(f"🔐 Decoding token with SECRET_KEY preview: {SECRET_KEY[:10]}...")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.debug(f"✅ Token payload: {payload}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.error("❌ Token expired")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"❌ Invalid token: {e}")
        logger.error(f"   Token: {token[:50]}...")
        logger.error(f"   Expected key: {SECRET_KEY}")
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# User authentication
# ---------------------------------------------------------------------------

def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password."""
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    # Update last login
    user.last_login = datetime.utcnow()
    session.add(user)
    session.commit()
    return user


def create_user(
    session: Session,
    username: str,
    password: str,
    email: Optional[str] = None,
    role: UserRole = UserRole.VIEWER,
) -> User:
    """Create a new user with hashed password."""
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Dependency injection for FastAPI
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """Get current user from session or JWT token."""
    # 🔑 Check session-based auth (from main.py login)
    username = request.session.get("user")  # ← ИСПРАВЛЕНО: было "user_id"
    if username:
        with Session(engine) as session:
            # Find user by username (string from session)
            user = session.exec(select(User).where(User.username == username)).first()
            if user and user.is_active:
                return user
    
    # Check JWT token (for API clients)
    if credentials:
        try:
            payload = decode_token(credentials.credentials)
            user_id = payload.get("sub")
            if user_id:
                with Session(engine) as session:
                    return session.get(User, int(user_id))
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
