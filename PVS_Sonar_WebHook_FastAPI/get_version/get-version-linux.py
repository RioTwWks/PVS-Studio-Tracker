from glob import glob
import http.client
import json
import logging
from os import getenv
from re import search
from subprocess import call
from urllib import parse

logging.basicConfig(level=logging.DEBUG)

# Получение переменных среды
group = getenv('GROUP')
sonar_project_key = getenv('SONAR_PROJECT_KEY')
sonar_project_name = getenv('SONAR_PROJECT_NAME')
proj_dir = getenv('DIR_FOR_PYTHON')
pvs_exclude = getenv('PVS_EXCLUDE_PATH')
select_vcxproj = getenv('SELECT_VCXPROJ')
cvs_system = getenv('CVS_SYSTEM')

# Определение системы контроля версии
if cvs_system == 'Git':
    cvs_system = 'git'
elif cvs_system == 'TFVC':
    cvs_system = 'tfvc'

# Путь для Sonar Scanner
sonar_path = getenv('sonar_path')
if not sonar_path:
    sonar_path = "./"
    logging.debug(f"sonar_path = {sonar_path}")

if pvs_exclude:
    exclude_dirs = pvs_exclude.split(",")
else:
    exclude_dirs = pvs_exclude

# Добавление PVS_EXCLUDE_PATH в Sonar properties
sonar_exlude = ""
if pvs_exclude:
    exclude_dirs = pvs_exclude.split(",")
    for exclude in exclude_dirs:
        sonar_exlude = f'{sonar_exlude},{exclude}/**'

# Поиск версии в CMake файле
def find_cmake_version(find_file, file_name_deb):
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    files = glob(f'{proj_dir}/**/*{find_file}.cmake*', recursive=True)
    for file in files:
        file_path = file
        call(f'grep -e "VER" -e "MIN" -e "MAJ" -e "PATCH" {file_path} > {file_path}_grep', shell=True)
        logging.debug(f'DEBUG: Find file {file_name_deb}.cmake with version: {file_path}')
        with open(f'{file_path}_grep', 'r+') as file:
            for line in file:
                ver = search(r'.*VER.* \d+', line)
                if ver:
                    if search(r'.*MAJ.*', line):
                        major = search(r'(\d+)', line)
                        major = int(major.group(1))
                    elif search(r'.*MIN.*', line):
                        minor = search(r'(\d+)', line)
                        minor = int(minor.group(1))
                    elif search(r'.*PATCH.*', line):
                        patch = search(r'(\d+)', line)
                        patch = int(patch.group(1))
                        break

# Поиск версии в CMakeLists.txt файле
def find_cmakelist_version(find_file, file_name_deb):
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    files = glob(f'{proj_dir}/**/*{find_file}.txt*', recursive=True)
    for file in files:
        file_path = file
        call(f'grep -e "VER" -e "MIN" -e "MAJ" -e "PATCH" {file_path} > {file_path}_grep', shell=True)
        logging.debug(f'DEBUG: Find file {file_name_deb}.txt with version: {file_path}')
        with open(f'{file_path}_grep', 'r+') as file:
            for line in file:
                ver = search(r'.*VER.* \d+', line)
                if ver:
                    if search(r'.*MAJ.*', line):
                        major = search(r'(\d+)', line)
                        major = int(major.group(1))
                    elif search(r'.*MIN.*', line):
                        minor = search(r'(\d+)', line)
                        minor = int(minor.group(1))
                    elif search(r'.*PATCH.*', line):
                        patch = search(r'(\d+)', line)
                        patch = int(patch.group(1))
                        break

def get_upper_two_levels(path):
    # Разделяем путь на компоненты
    parts = path.split('\\')
    
    # Убираем начальные '.' или '' (пустой компонент от абсолютного пути)
    if parts and parts[0] in ('.', ''):
        parts.pop(0)
    
    # Оставляем все компоненты, кроме двух последних
    remaining = parts[:-2] if len(parts) >= 2 else []
    
    # Формируем результат
    return '/' + '/'.join(remaining) + ('/' if remaining else '')

# Поиск версии в файле VersionInfo.h для группы QAdmin
def find_version_for_qadmin_group():
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    if "QAdministrator_Client" in sonar_project_name or "QAdministrator_Server" in sonar_project_name:
        files = glob(f'{proj_dir}/Exchange/Common/VersionInfo.h', recursive=True)
    else:
        try:
            files = glob(f'{proj_dir}{get_upper_two_levels(select_vcxproj)}**\\VersionInfo.h', recursive=True)
            logging.debug(f'Find in {files}')
        except:
            files = glob(f'{proj_dir}\\**/*CMakeLists.txt*', recursive=True)
    for file in files:
        file_path = file
        logging.debug(f'DEBUG: Find QAdmin file VersionInfo.h with version: {file_path}')
        with open(file_path, 'r+') as file:
            for line in file:
                ver = search(r'.*VER.* \d+', line)
                if ver:
                    if search(r'.*MAJ.*', line):
                        major = search(r'(\d+)', line)
                        major = int(major.group(1))
                    elif search(r'.*MIN.*', line):
                        minor = search(r'(\d+)', line)
                        minor = int(minor.group(1))
                    elif search(r'.*PATCH.*', line):
                        patch = search(r'(\d+)', line)
                        patch = int(patch.group(1))
                        break

if group == 'QA':
    find_version_for_qadmin_group()
else:
    find_cmake_version('*ersion', 'Version')

    if not major and not minor and not patch:
        file_name = search(r'.+[.](.+)[.]*(.*)', sonar_project_key)
        logging.debug(f'DEBUG: File Version.cmake without version. Find: {file_name.group(1)}.cmake')
        find_cmake_version(file_name.group(2), 'project_name')
        if not major and not minor and not patch:
            find_cmake_version(file_name.group(1), 'project_name')

    if not major and not minor and not patch:
        find_cmakelist_version('*MakeLists.txt', 'CMakeLists.txt')

logging.debug(f'DEBUG: Project Version {major}.{minor}.{patch}')

if major == None and minor == None and patch == None:
    raise ValueError('Version not found')

params = """
sonar.sourceEncoding=CP1251
sonar.language=cxx

sonar.sources=""" + sonar_path + """

sonar.exclusions=build_dir/**,build_cmake/**,build.cmake/**,out/**,.git/**,**/*.cmake,**/*.doc,**/*.docx,**/*.ipch,**/*.rc,**/*.ico,**/*.cur,**/*.ini,**/*.gitignore,**/*.gitmodules,**/*.pas,**/*.props,**/*.txt,**/*.json,**/*.dpr,**/*.dproj,**/*.clang-format,**/*.sh,**/*.vcxproj,**/*.lim,**/*.data,**/*.sql,**/*.sln,**/*.filters,**/*.in,**/*.def,**/*.bat,**/*.bpg,**/*.dof,**/*.vssscc,**/*.lib,**/*.png,**/README,**/*.mc,**/COPYING,**/Makefile,**/version,**/*.cmd,**/*.p7s,**/*.dll,**/*.pc,**/FAQ,**/*.nupkg,**/*.py,**/*.profile,**/*.gz,**/PARDP,**/TRGEN,**/*.a,**/*.exe,**/*.vspscc,**/*.xml,**/*.inl,**/*.gitattributes,**/*.targets,**/*.doxy,**/*.log,**/*.bmp,**/*.wav,**/*.pdb,**/*.jpg,**/*.LIB,**/*.rule,**/*.bin,**/*.obj,**/*.recipe,**/*.tlog,**/*.lastbuildstate,**/*.stamp,**/*.depend,**/*.tmpl,**/*.ac,**/*.html,**/*.pl,**/*.am,**/*.supp,**/*.template,**/*.pump,**/*.ICO,**/*.BMP,**/*.RC,**/*.DEF,**/*.TXT,**/*.manifest,**/*.lua,**/*.css,**/*.gif,**/*.pdf,**/*.mdb,**/*.aps,**/*.user,**/*.list,**/*.cfg,**/*.Linux,**/*.Windows,**/*.md,**/*.h_bmp,**/*.htm,**/*.dsp,**/*.dsw,**/*.rc2,**/*.plg,**/*.dsc,**/*.mte,lua5.4.1/**,lua5.3.5/**,**/*.pch,**/*.iobj,**/*.inl,GTest/**""" + sonar_exlude + """
sonar.pvs-studio.reportPath=pvs.json

sonar.scm.disabled=false

sonar.scm.provider=git
"""

with open(proj_dir + '/sonar-project.properties', 'w', encoding='cp1251') as f:
    f.write(f'sonar.projectKey={sonar_project_key}\nsonar.projectName={sonar_project_name}\n\nsonar.projectVersion={major}.{minor}.{patch}\n{params}')

# Отправка версии в БД сервера
def send_version(sonar_project_key, major, minor, patch):
    logging.debug(f"Отправка POST запроса с версией к FastAPI серверу...")

    form_data = {
        "project_key": sonar_project_key,
        "project_ver": f"{major}.{minor}.{patch}"
    }

    # Кодируем данные
    encoded_data = parse.urlencode(form_data)

    # Устанавливаем соединение
    conn = http.client.HTTPConnection("qube", 8080, timeout=10)

    try:
        # Отправляем запрос
        conn.request(
            "POST",
            "/project/version",
            body=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(encoded_data)),
                "User-Agent": "PostClient/1.0"
            }
        )

        # Получаем ответ
        response = conn.getresponse()

        logging.debug(f"Статус: {response.status} {response.reason}")

        # Читаем ответ
        response_body = response.read().decode('utf-8')

        if response.status == 200:
            logging.debug(f"Запрос успешно выполнен")

            # Пытаемся распарсить JSON
            try:
                json_response = json.loads(response_body)
                logging.debug(f"JSON ответ: {json.dumps(json_response, indent=2, ensure_ascii=False)}")
            except:
                logging.debug(f"Текстовый ответ: {response_body}")
        else:
            logging.error(f"Ошибка запроса: {response.status}")
            logging.error(f"Тело ответа: {response_body}")

        return response.status, response_body

    except Exception as e:
        logging.error(f"Ошибка при отправке запроса: {e}")
        raise
    finally:
        conn.close()

status, response = send_version(sonar_project_key, major, minor, patch)
