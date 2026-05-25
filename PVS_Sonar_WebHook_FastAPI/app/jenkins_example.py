from jenkinsapi.jenkins import Jenkins
import urllib3 # работа с HTTP-запросами
import xml.etree.ElementTree as ET

# Отключаем предупреждения '1097: InsecureRequestWarning'
urllib3.disable_warnings(category=urllib3.exceptions.InsecureRequestWarning)

# Подключение с использованием API-токена (рекомендуется)
jenkins = Jenkins(
    'https://newbuilder',
    username='ieme',
    password='28f14cd8f9835f8743dc993078f2524c',
    ssl_verify = False,
    use_crumb = True,
    timeout=20
)

# Получить список всех задач
#job_names = jenkins.keys()
#print(job_names)

# Получить объект конкретной задачи
job = jenkins['Test_FastAPI']
config_xml = job.get_config()

#print(config_xml)

# Парсинг XML
#root = ET.fromstring(config_xml)




# Извлекает ВСЕ команды Batch и Shell из задачи, включая те, что внутри ConditionalBuilder
def extract_batch_shell_commands():
    server = Jenkins(
        'https://newbuilder',
        username='ieme',
        password='28f14cd8f9835f8743dc993078f2524c',
        ssl_verify = False,
        use_crumb = True,
        timeout=20
    )
    job = server['Test_FastAPI']
    config_xml = job.get_config()
    root = ET.fromstring(config_xml)
    
    print(f"=== Команды из задачи: 'Test_FastAPI' ===\n")
    
    # Словарь для хранения всех найденных команд
    all_commands = {
        'batch': [],  # (путь, команда)
        'shell': []   # (путь, команда)
    }
    
    # Функция для поиска команд в любом месте XML
    def find_commands(element, path=""):
        current_path = f"{path}/{element.tag}" if path else element.tag
        
        # Проверяем, является ли элемент командой
        if element.tag == 'hudson.tasks.BatchFile':
            command_elem = element.find('command')
            if command_elem is not None and command_elem.text:
                all_commands['batch'].append((current_path, command_elem.text))
                
        elif element.tag == 'hudson.tasks.Shell':
            command_elem = element.find('command')
            if command_elem is not None and command_elem.text:
                all_commands['shell'].append((current_path, command_elem.text))
                
        # Рекурсивно обходим дочерние элементы
        for child in element:
            find_commands(child, current_path)
    
    # Запускаем поиск
    find_commands(root)
    
    # Выводим результаты
    if all_commands['batch']:
        print("=== BATCH КОМАНДЫ ===")
        for i, (path, cmd) in enumerate(all_commands['batch'], 1):
            print(f"\nBatch #{i} (путь: {path}):")
            # Показываем команду с нумерацией строк
            lines = cmd.strip().split('\n')
            for j, line in enumerate(lines):
                print(f"  {j+1:2}: {line}")
    
    if all_commands['shell']:
        print("\n=== SHELL КОМАНДЫ ===")
        for i, (path, cmd) in enumerate(all_commands['shell'], 1):
            print(f"\nShell #{i} (путь: {path}):")
            lines = cmd.strip().split('\n')
            for j, line in enumerate(lines):
                print(f"  {j+1:2}: {line}")
    
    return all_commands

commands = extract_batch_shell_commands()






def replace_entire_step(step_info, new_content):
    """
    Полная замена конкретного шага сборки
    
    :param step_info: словарь с идентификацией шага
        Пример: {'type': 'batch', 'number': 1}  # Batch #1
        Или: {'type': 'shell', 'number': 2}    # Shell #2
    
    :param new_content: новая команда (строка)
    """
    server = Jenkins(
        'https://newbuilder',
        username='ieme',
        password='28f14cd8f9835f8743dc993078f2524c',
        ssl_verify = False,
        use_crumb = True,
        timeout=20
    )
    job = server['Test_FastAPI']
    config_xml = job.get_config()
    root = ET.fromstring(config_xml)
    
    # Определяем тип элемента XML
    tag_map = {
        'batch': 'hudson.tasks.BatchFile',
        'shell': 'hudson.tasks.Shell'
    }
    
    target_tag = tag_map.get(step_info['type'])
    if not target_tag:
        print(f"Неизвестный тип шага: {step_info['type']}")
        return False
    
    # Находим ВСЕ элементы этого типа
    all_elements = list(root.findall(f'.//{target_tag}'))
    
    print(f"Найдено элементов {target_tag}: {len(all_elements)}")
    
    # Проверяем, существует ли нужный номер
    if step_info['number'] < 1 or step_info['number'] > len(all_elements):
        print(f"Шаг #{step_info['number']} не существует. Всего шагов: {len(all_elements)}")
        return False
    
    # Получаем нужный элемент
    target_element = all_elements[step_info['number'] - 1]
    
    # Находим элемент <command> внутри
    command_elem = target_element.find('command')
    
    if command_elem is None:
        # Если элемента command нет, создаём его
        command_elem = ET.SubElement(target_element, 'command')
    
    # Сохраняем старую команду для лога
    old_content = command_elem.text if command_elem.text else ""
    
    # Заменяем содержимое
    command_elem.text = new_content
    
    # Сохраняем изменения
    updated_config = ET.tostring(root, encoding='unicode')
    job.update_config(updated_config)
    
    print(f"✓ Шаг {step_info['type'].upper()} #{step_info['number']} успешно заменён!")
    print(f"\nБыло ({len(old_content.splitlines())} строк):")
    print("-" * 50)
    print(old_content[:500] + ("..." if len(old_content) > 500 else ""))
    print(f"\nСтало ({len(new_content.splitlines())} строк):")
    print("-" * 50)
    print(new_content[:500] + ("..." if len(new_content) > 500 else ""))
    
    return True



# Упрощённая версия Batch #1
new_batch1 = """@echo off
setlocal enabledelayedexpansion

echo Упрощённый скрипт клонирования
echo CVS_SYSTEM: %CVS_SYSTEM%

if "%CVS_SYSTEM%"=="Git" (
    echo Клонируем Git репозиторий
    git clone --depth=1 "%TFS_PATH%" .
) else (
    echo Клонируем TFVC репозиторий
    call "%JENKINS_HOME%\\CODE_ANALYSIS\\Git-TF\\git-tf" clone "%TFS_PATH%" .
)

if errorlevel 1 (
    echo Ошибка клонирования
    exit /b 1
)"""

replace_entire_step(
    step_info={'type': 'batch', 'number': 1},
    new_content=new_batch1
)



# Упрощённый Shell #1 для Linux
new_shell1 = """#!/bin/bash
set -ex

echo "Упрощённый скрипт для Linux"

if [[ "${CVS_SYSTEM}" == "Git" ]]; then
    echo "Клонируем Git репозиторий"
    git clone --depth=1 "${TFS_PATH}" .
elif [[ "${CVS_SYSTEM}" == "TFVC" ]]; then
    echo "Клонируем TFVC репозиторий"
    git-tf clone --depth=1 "${TFS_PATH}" .
fi

if [ $? -ne 0 ]; then
    echo "Ошибка клонирования"
    exit 1
fi"""

replace_entire_step(
    step_info={'type': 'shell', 'number': 1},
    new_content=new_shell1
)



# Сокращённая версия Batch #2
new_batch2 = """@echo off
setlocal enabledelayedexpansion

echo === Упрощённый PVS-Studio анализ ===

rem Находим проектную директорию
for /f %%i in ('dir /b /ad') do set PROJ_DIR=%%i
echo Рабочая директория: %PROJ_DIR%
cd "%WORKSPACE%\\%PROJ_DIR%"

rem Запускаем PVS-Studio
echo Запуск PVS-Studio анализа...
call "C:\\Program Files (x86)\\PVS-Studio\\PVS-Studio_Cmd.exe" ^
    -c %PVS_CHECK_CONF_NAME% ^
    -p %PVS_CHECK_ARCH% ^
    -r ^
    --target %SLN_PATH% ^
    --output pvs-win.json

if errorlevel 1 (
    echo Анализ завершился с ошибками
    exit /b 1
)

echo Анализ успешно завершён
exit 0"""

replace_entire_step(
    step_info={'type': 'batch', 'number': 2},
    new_content=new_batch2
)




# Интерактивная замена шагов с выбором шаблонов
def batch_replacer_with_templates():
    
    templates = {
        'batch': {
            'simple_git_clone': """@echo off
echo Простое клонирование Git
git clone "%TFS_PATH%" .""",
            
            'pvs_analysis_light': """@echo off
echo Облегчённый PVS-Studio анализ
call "PVS-Studio_Cmd.exe" --target solution.sln --output report.json""",
            
            'custom': None  # Пользовательский ввод
        },
        'shell': {
            'linux_git_clone': """#!/bin/bash
echo Клонирование для Linux
git clone "$TFS_PATH" .""",
            
            'linux_pvs_analysis': """#!/bin/bash
echo PVS-Studio для Linux
pvs-studio-analyzer analyze -o pvs.log""",
            
            'custom': None
        }
    }
    
    print("=== Замена шагов сборки ===")
    
    # Выбор типа шага
    step_type = input("Тип шага (batch/shell): ").strip().lower()
    if step_type not in ['batch', 'shell']:
        print("Неверный тип. Допустимо: batch, shell")
        return
    
    # Выбор номера
    try:
        step_number = int(input(f"Номер шага {step_type.upper()} (1 или 2): "))
    except ValueError:
        print("Номер должен быть числом")
        return
    
    # Выбор шаблона
    print(f"\nДоступные шаблоны для {step_type}:")
    template_keys = list(templates[step_type].keys())
    for i, key in enumerate(template_keys, 1):
        print(f"  {i}. {key}")
    print(f"  {len(template_keys)+1}. Ввести вручную")
    
    try:
        choice = int(input("Выберите шаблон: "))
    except ValueError:
        print("Неверный выбор")
        return
    
    # Получение нового содержимого
    if choice == len(template_keys) + 1:
        print(f"\nВведите новый скрипт для {step_type.upper()} #{step_number}:")
        print("(введите END на отдельной строке для завершения)")
        lines = []
        while True:
            line = input()
            if line.strip() == 'END':
                break
            lines.append(line)
        new_content = '\n'.join(lines)
    elif 1 <= choice <= len(template_keys):
        template_key = template_keys[choice - 1]
        if template_key == 'custom':
            new_content = input("Введите скрипт: ")
        else:
            new_content = templates[step_type][template_key]
    else:
        print("Неверный выбор шаблона")
        return
    
    # Подтверждение
    print(f"\nБудет заменён {step_type.upper()} #{step_number}")
    print("Новое содержимое:")
    print("-" * 50)
    print(new_content[:300] + ("..." if len(new_content) > 300 else ""))
    print("-" * 50)
    
    confirm = input("\nПодтвердить замену? (y/N): ").strip().lower()
    if confirm == 'y':
        # Вызов основной функции
        replace_entire_step(
            jenkins_url='http://localhost:8080',
            job_name='Test_FastAPI',
            step_info={'type': step_type, 'number': step_number},
            new_content=new_content,
            username='admin',
            api_token='ваш_токен'
        )
    else:
        print("Отменено")





def bulk_replace_steps(jenkins_url, job_name, replacements, username=None, api_token=None):
    """
    Массовая замена нескольких шагов за один раз
    
    :param replacements: список словарей
        [
            {'type': 'batch', 'number': 1, 'content': 'новый_скрипт_batch1'},
            {'type': 'shell', 'number': 2, 'content': 'новый_скрипт_shell2'}
        ]
    """
    server = Jenkins(jenkins_url, username=username, password=api_token)
    job = server[job_name]
    config_xml = job.get_config()
    root = ET.fromstring(config_xml)
    
    # Группируем замены по типу
    changes_made = []
    
    for replacement in replacements:
        step_type = replacement['type']
        step_number = replacement['number']
        new_content = replacement['content']
        
        tag_map = {'batch': 'hudson.tasks.BatchFile', 'shell': 'hudson.tasks.Shell'}
        target_tag = tag_map.get(step_type)
        
        if not target_tag:
            print(f"Пропуск: неизвестный тип {step_type}")
            continue
        
        # Находим элемент
        all_elements = list(root.findall(f'.//{target_tag}'))
        
        if step_number < 1 or step_number > len(all_elements):
            print(f"Пропуск: {step_type.upper()} #{step_number} не существует")
            continue
        
        target_element = all_elements[step_number - 1]
        command_elem = target_element.find('command')
        
        if command_elem is None:
            command_elem = ET.SubElement(target_element, 'command')
        
        # Запоминаем для отчёта
        old_lines = len(command_elem.text.splitlines()) if command_elem.text else 0
        new_lines = len(new_content.splitlines())
        
        # Заменяем
        command_elem.text = new_content
        changes_made.append({
            'type': step_type,
            'number': step_number,
            'old_lines': old_lines,
            'new_lines': new_lines
        })
    
    if changes_made:
        # Сохраняем все изменения разом
        updated_config = ET.tostring(root, encoding='unicode')
        job.update_config(updated_config)
        
        # Отчёт
        print("✓ Выполнены замены:")
        print("-" * 50)
        for change in changes_made:
            print(f"  {change['type'].upper()} #{change['number']}: "
                  f"{change['old_lines']} строк → {change['new_lines']} строк")
        print(f"\nВсего изменено шагов: {len(changes_made)}")
        return True
    else:
        print("Не было изменений")
        return False

# Пример массовой замены
#bulk_replace_steps(
#    jenkins_url='http://jenkins:8080',
#    job_name='Test_FastAPI',
#    replacements=[
#        {
#            'type': 'batch',
#            'number': 1,
#            'content': """@echo off
#echo Новая упрощённая версия Batch #1
#echo Клонирование репозитория
#git clone "%TFS_PATH%" ."""
#        },
#        {
#            'type': 'shell', 
#            'number': 1,
#            'content': """#!/bin/bash
#echo Новая упрощённая версия Shell #1
#git clone "$TFS_PATH" ."""
#        }
#    ]
#)





