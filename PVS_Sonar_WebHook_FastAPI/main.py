from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Путь к БД
DB_PATH = "pvs_sonar.db"

# Функция для подключения к SQLite
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Возвращает данные как словарь
    return conn

# Модель данных
class ProjectData:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Маршрут для отображения формы
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects")
    projects = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "projects": projects})

# Маршрут для обработки формы
@app.post("/submit", response_class=HTMLResponse)
def submit_project(
    request: Request,
    GROUP_ID: str = Form(...),
    AUTHOR_EMAIL: str = Form(...),
    SONAR_PROJECT_NAME: str = Form(...),
    SONAR_PROJECT_KEY: str = Form(...),
    JIRA_PROJECT: str = Form(None),
    CVS_SYSTEM: str = Form(...),
    TFS_PATH: str = Form(...),
    SUB_MODULES: bool = Form(False),
    ANOTHER_BRANCH: str = Form(...),
    LIFE_TIME: str = Form(None),
    CMAKE_MSBUILD: str = Form(...),
    SELECT_VCXPROJ: str = Form(None),
    PVS_EXCLUDE_VCXPROJ: str = Form(None),
    PVS_EXCLUDE_PATH: str = Form(None),
    PVS_CHECK_CONF_NAME: str = Form(...),
    PVS_CHECK_ARCH: str = Form(...),
    disabled: bool = Form(False),
    content_win: str = Form(None),
    content_linux: str = Form(None),
    version: str = Form(None),
    disable_jira: bool = Form(True)
):
    # Сохранение данных в БД
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO projects (
            GROUP_PROJECT, AUTHOR_EMAIL, SONAR_PROJECT_NAME, SONAR_PROJECT_KEY,
            JIRA_PROJECT, CVS_SYSTEM, TFS_PATH, SUB_MODULES, ANOTHER_BRANCH,
            LIFE_TIME, CMAKE_MSBUILD, SELECT_VCXPROJ, PVS_EXCLUDE_VCXPROJ, PVS_EXCLUDE_PATH, PVS_CHECK_CONF_NAME,
            PVS_CHECK_ARCH,, disabled, content_win, content_linux, version, disable_jira
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            GROUP_ID, AUTHOR_EMAIL, SONAR_PROJECT_NAME, SONAR_PROJECT_KEY, JIRA_PROJECT,
            CVS_SYSTEM, TFS_PATH, SUB_MODULES, ANOTHER_BRANCH, LIFE_TIME, CMAKE_MSBUILD,
            SELECT_VCXPROJ, PVS_EXCLUDE_VCXPROJ,PVS_EXCLUDE_PATH,PVS_CHECK_CONF_NAME, PVS_CHECK_ARCH, disabled,
            content_win, content_linux, version, disable_jira
        )
    )
    conn.commit()
    conn.close()

    return templates.TemplateResponse("index.html", {"request": request, "message": "Проект добавлен"})

# Маршрут для отключения/включения проекта
@app.post("/toggle_project")
def toggle_project(id: int = Form(...), action: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    project_path = f"path_to_project_{id}"  # Реальный путь из БД
    if action == "disable":
        os.rename(project_path, project_path + "_disabled")
    elif action == "enable":
        os.rename(project_path + "_disabled", project_path)
    conn.close()
    return {"status": "success"}
