from glob import glob
import http.client
import json
from os import getenv
from re import search
from urllib import parse

# Получение переменных среды
sonar_project_key = getenv('SONAR_PROJECT_KEY')
sonar_project_name = getenv('SONAR_PROJECT_NAME')
proj_dir = getenv('DIR_FOR_PYTHON')
cmake_msbuild = getenv('CMAKE_MSBUILD')
sln_name = getenv('sln_name')
sln_name = (sln_name.split("."))[0]
pvs_exclude = getenv('PVS_EXCLUDE_PATH')
# Путь для Sonar Scanner
sonar_path = getenv('sonar_path')
if not sonar_path:
    sonar_path = "./"

# Добавление PVS_EXCLUDE_PATH в Sonar properties
sonar_exlude = ""
if pvs_exclude:
    exclude_dirs = pvs_exclude.split(",")
    for exclude in exclude_dirs:
        sonar_exlude = sonar_exlude + ',' + exclude + '/**'

# Поиск версии в файле Version.rc
def find_fileversion(file_name):
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    files = glob(proj_dir + '\\**/*' + file_name + '-utf-8.rc*', recursive=True)
    for file in files:
        file_path = file
        print('DEBUG: Find file Version.rc with version: ' + file_path)
        for exclude in exclude_dirs:
            if exclude in file_path:
                exclude_file = True
                print('DEBUG: Found file Version.rc in EXLUDE. Go Next!')
        if not exclude_file:
            with open(file_path, 'r+', encoding='cp866') as file:
                for line in file:
                    match = search(r'.*FILEVERSION (\d+),(\d+),(\d+),\d+', line)
                    if match:
                        major = int(match.group(1))
                        minor = int(match.group(2))
                        patch = int(match.group(3))

# Поиск версии в CMake файле
def find_cmake_version(find_file, file_name_deb):
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    files = glob(proj_dir + '\\**/*' + find_file + '.cmake*', recursive=True)
    for file in files:
        file_path = file
        print('DEBUG: Find file ' + file_name_deb + '.cmake with version: ' + file_path)
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

# Поиск версии в файле VersionInfo.h для группы QAdmin
def find_version_for_qadmin_group():
    global major, minor, patch, exclude_file
    major, minor, patch, exclude_file = None, None, None, None

    files = glob(proj_dir + '\\**\\VersionInfo.h', recursive=True)
    for file in files:
        file_path = file
        print('DEBUG: Find QAdmin file VersionInfo.h with version: ' + file_path)
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


if cmake_msbuild == 'MSBuild':
    find_fileversion(sln_name)

    if not major and not minor and not patch:
        find_fileversion('*ersion')

        if not major and not minor and not patch:
            find_fileversion('*')

elif cmake_msbuild == 'CMake':
    find_cmake_version('*ersion', 'Version')

    if not major and not minor and not patch:
        file_name = search(r'.*[.](.*)', sonar_project_key)
        print ('DEBUG: File Version.cmake without version. Find: ' + file_name.group(1) + '.cmake')
        find_cmake_version(file_name.group(1), 'project_name')

else:
    raise ValueError('ERROR: CMAKE_MSBUILD is defined incorrectly')

print (f'DEBUG: Project Version {major}.{minor}.{patch}')

if major == None and minor == None and patch == None:
    if len(glob(proj_dir + '\\**\\VersionInfo.h', recursive=True)) > 0 : # QuikAdministrator has their own view on storing project version
        find_version_for_qadmin_group()

if major == None and minor == None and patch == None:
    raise ValueError('ERROR: Version not found')

params = """
sonar.sourceEncoding=CP1251
sonar.language=cxx

sonar.sources=""" + sonar_path + """

sonar.exclusions=build_dir/**,build_cmake/**,build.cmake/**,out/**,.git/**,**/*.cmake,**/*.doc,**/*.docx,**/*.ipch,**/*.rc,**/*.ico,**/*.cur,**/*.ini,**/*.gitignore,**/*.gitmodules,**/*.pas,**/*.props,**/*.txt,**/*.json,**/*.dpr,**/*.dproj,**/*.clang-format,**/*.sh,**/*.vcxproj,**/*.lim,**/*.data,**/*.sql,**/*.sln,**/*.filters,**/*.in,**/*.def,**/*.bat,**/*.bpg,**/*.dof,**/*.vssscc,**/*.lib,**/*.png,**/README,**/*.mc,**/COPYING,**/Makefile,**/version,**/*.cmd,**/*.p7s,**/*.dll,**/*.pc,**/FAQ,**/*.nupkg,**/*.py,**/*.profile,**/*.gz,**/PARDP,**/TRGEN,**/*.a,**/*.exe,**/*.vspscc,**/*.xml,**/*.inl,**/*.gitattributes,**/*.targets,**/*.doxy,**/*.log,**/*.bmp,**/*.wav,**/*.pdb,**/*.jpg,**/*.LIB,**/*.rule,**/*.bin,**/*.obj,**/*.recipe,**/*.tlog,**/*.lastbuildstate,**/*.stamp,**/*.depend,**/*.tmpl,**/*.ac,**/*.html,**/*.pl,**/*.am,**/*.supp,**/*.template,**/*.pump,**/*.ICO,**/*.BMP,**/*.RC,**/*.DEF,**/*.TXT,**/*.manifest,**/*.lua,**/*.css,**/*.gif,**/*.pdf,**/*.mdb,**/*.aps,**/*.user,**/*.list,**/*.cfg,**/*.Linux,**/*.Windows,**/*.md,**/*.h_bmp,**/*.htm,**/*.dsp,**/*.dsw,**/*.rc2,**/*.plg,**/*.dsc,**/*.mte,lua5.4.1/**,lua5.3.5/**""" + sonar_exlude + """
sonar.pvs-studio.reportPath=pvs-win.json

sonar.scm.provider=git

sonar.scm.disabled=true
"""

with open(proj_dir + '\\sonar-project.properties', 'w', encoding='cp1251') as f:
    f.write('sonar.projectKey=' + sonar_project_key + '\n' +
        'sonar.projectName=' + sonar_project_name + '\n\n' +
        f'sonar.projectVersion={major}.{minor}.{patch}\n' +
        params)

# Отправка версии в БД сервера
def send_version(sonar_project_key, major, minor, patch):
    print("DEBUG: Отправка POST запроса с версией к FastAPI серверу...")

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
            "/version",
            body=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(encoded_data)),
                "User-Agent": "PostClient/1.0"
            }
        )

        # Получаем ответ
        response = conn.getresponse()

        print(f"DEBUG: Статус: {response.status} {response.reason}")

        # Читаем ответ
        response_body = response.read().decode('utf-8')

        if response.status == 200:
            print("DEBUG: Запрос успешно выполнен")

            # Пытаемся распарсить JSON
            try:
                json_response = json.loads(response_body)
                print(f"DEBUG: JSON ответ: {json.dumps(json_response, indent=2, ensure_ascii=False)}")
            except:
                print(f"DEBUG: Текстовый ответ: {response_body}")
        else:
            print(f"ERROR: Ошибка запроса: {response.status}")
            print(f"ERROR: Тело ответа: {response_body}")

        return response.status, response_body

    except Exception as e:
        print(f"ERROR: Ошибка при отправке запроса: {e}")
        raise
    finally:
        conn.close()

status, response = send_version(sonar_project_key, major, minor, patch)
