from json import dump, load
from os import getenv
from pathlib import Path
import sys

proj_dir = getenv('DIR_FOR_PYTHON')

# Чтение JSON-файлов
with open(proj_dir + '/pvs-win.json', 'r', encoding='utf-8') as win_file:
    data_win = load(win_file)

pvs_linux_file = Path(proj_dir + '/pvs-linux.json')
if pvs_linux_file.is_file():
    with open(proj_dir + '/pvs-linux.json', 'r', encoding='utf-8') as linux_file:
        data_linux = load(linux_file)

    # Добавление всех предупреждений из первого файла во второй
    data_linux['warnings'].extend(data_win['warnings'])

    # Сохранение результата в новый файл
    with open(proj_dir + '/pvs.json', 'w', encoding='utf-8') as combined_file:
        dump(data_linux, combined_file, ensure_ascii=False, indent=4)

    # Приведение путей в единый формат
    with open(proj_dir + '/pvs.json', 'r', encoding='utf-8') as file:
        filedata = file.read()

    filedata = filedata.replace('\\\\', '/')
    filedata = filedata.replace('D:', '/home/builder@arqa.ru')

    with open(proj_dir + '/pvs.json', 'w') as file:
        file.write(filedata)

# Если анализ провалился, то этот скрипт вернёт exit code 44 и будет заливка анализа Windows-версии в Sonar
else:
    # Приведение путей в единый формат
    with open(proj_dir + '/pvs-win.json', 'r', encoding='utf-8') as file:
        filedata = file.read()

    filedata = filedata.replace('\\\\', '/')
    filedata = filedata.replace('D:', '/home/builder@arqa.ru')

    with open(proj_dir + '/pvs.json', 'w') as file:
        file.write(filedata)
    sys.exit(44)
