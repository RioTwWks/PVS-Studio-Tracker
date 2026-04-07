from ldap3 import Server, Connection, ALL, NTLM
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

# Добавьте в main.py: app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

LDAP_SERVER = "ldap://ad.company.local:389"
LDAP_BASE_DN = "DC=company,DC=local"

def get_ldap_connection(username: str, password: str):
    server = Server(LDAP_SERVER, get_info=ALL)
    conn = Connection(server, user=f"{username}@company.local", password=password, authentication=NTLM)
    if not conn.bind():
        raise HTTPException(401, "Неверный логин или пароль")
    return conn

def require_auth(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return user
