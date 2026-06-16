from collections import defaultdict
import json
import logging
import os
from pathlib import Path
import platform
import sys

from lxml import etree

logging.basicConfig(level=logging.DEBUG)


# Нормализация пути
def normalize_path(path: str, for_key: bool = False) -> str:
    """
    - for_key=True: нижний регистр + '/' (для стабильного ключа дедупликации)
    - for_key=False: оригинальный регистр, но '\\' -> '/'
    """
    if not path:
        return ""
    p = path.replace('\\', '/')
    while p.startswith('./'):
        p = p[2:]
    return p.lower() if for_key else p


# Приведение пути к абсолютному (относительно WORKSPACE)
def to_absolute(path: str, workspace: str) -> str:
    """Если путь не абсолютный, считать его относительно workspace."""
    p = Path(path)
    if not p.is_absolute() and workspace:
        p = Path(workspace) / p
    return normalize_path(str(p), for_key=True)


# Определение затронутых файлов (Windows)
def get_affected_files_windows(hash_dir_before: Path, hash_dir_after: Path, workspace: str):
    """
    Возвращает множество нормализованных абсолютных путей ВСЕХ файлов,
    которые были изменены или чьи зависимости изменились.
    Включает как TU, так и заголовочные файлы.
    """
    def load_hash_state(directory: Path) -> dict:
        state = {}
        if not directory.exists():
            logging.debug(f'Hash directory {directory} does not exist')
            return state
        for json_file in directory.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    tu = item.get('TranslationUnit')
                    if tu:
                        tu_abs = to_absolute(tu, workspace)
                        deps = item.get('Dependencies', {})
                        # Нормализуем все пути из зависимостей
                        norm_deps = {}
                        for k, v in deps.items():
                            norm_key = to_absolute(k, workspace)
                            norm_deps[norm_key] = v
                        state[tu_abs] = {
                            'self_hash': norm_deps.get(tu_abs),
                            'dep_hashes': norm_deps
                        }
            except (json.JSONDecodeError, IOError, OSError):
                continue
        return state

    before = load_hash_state(hash_dir_before)
    after = load_hash_state(hash_dir_after)

    logging.debug(f'Windows hash state: before has {len(before)} TUs, after has {len(after)} TUs')

    if not before:
        logging.warning('No previous hash state – returning None')
        return None

    if not after:
        # В текущем запуске вообще нет данных? Маловероятно, но на всякий случай
        logging.warning('No current hash state – returning None')
        return None

    affected = set()   # теперь здесь будут и TU, и изменённые зависимости
    all_tus = set(before.keys()) | set(after.keys())
    logging.debug(f'Total TUs to compare: {len(all_tus)}')
    for tu in all_tus:
        b = before.get(tu)
        a = after.get(tu)
        if b is None or a is None:
            affected.add(tu)          # новый или удалённый TU
            continue
        # Изменился хеш самого TU
        if b['self_hash'] != a['self_hash']:
            affected.add(tu)
        # Проверяем зависимости: любой файл с изменившимся хешем добавляем в affected
        all_deps = set(b['dep_hashes'].keys()) | set(a['dep_hashes'].keys())
        for dep in all_deps:
            if b['dep_hashes'].get(dep) != a['dep_hashes'].get(dep):
                affected.add(dep)     # заголовок или другой зависимый файл

    logging.debug(f'Windows affected files: {len(affected)}')
    if affected:
        sample = list(affected)[:10]
        logging.debug(f'First 10 affected: {sample}')
    return affected


# Определение затронутых файлов (Linux)
def get_affected_files_linux(modified_files_path: Path, depend_info_path: Path, workspace: str):
    """
    Возвращает:
      - None, если modified_files.txt отсутствует (нет данных)
      - set() пустое, если modified_files.txt существует, но пуст (нет изменений)
      - set(...) с затронутыми TU
    """
    if not modified_files_path.exists():
        logging.warning('modified_files.txt not found – returning None')
        return None

    modified_files = set()
    with open(modified_files_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                # Сразу приводим к абсолютному пути относительно workspace
                modified_files.add(to_absolute(line, workspace))

    if not modified_files:
        logging.info('modified_files.txt is empty – returning empty set')
        return set()

    # строим обратный граф зависимостей (все пути абсолютные)
    reverse_deps = defaultdict(set)
    tu_set = set()

    if depend_info_path.exists():
        try:
            with open(depend_info_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for entry in data:
                args = entry.get('arguments', [])
                tu_path = None
                for i, arg in enumerate(args):
                    if arg == '-c' and i + 1 < len(args):
                        tu_path = args[i + 1]
                        break
                if not tu_path and args:
                    tu_path = args[-1]
                if tu_path:
                    tu_abs = to_absolute(tu_path, workspace)
                    tu_set.add(tu_abs)
                    for dep in entry.get('dependencies', []):
                        dep_abs = to_absolute(dep, workspace)
                        reverse_deps[dep_abs].add(tu_abs)
                    reverse_deps[tu_abs].add(tu_abs)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logging.warning(f'Could not parse depend_info.json: {e}')

    affected = set()
    # Прямо добавляем все изменённые файлы
    affected.update(modified_files)

    # Добавляем TU, зависящие от изменённых файлов
    for modified in modified_files:
        if modified in tu_set:
            affected.add(modified)
        if modified in reverse_deps:
            affected.update(reverse_deps[modified])

    # fallback для файлов, отсутствующих в графе
    for modified in modified_files:
        if modified not in tu_set and modified not in reverse_deps:
            if Path(workspace).exists() and Path(modified).exists():
                affected.add(modified)

    logging.debug(f'Linux affected files: {len(affected)}')
    if affected:
        sample = list(affected)[:10]
        logging.debug(f'First 10 affected: {sample}')
    return affected


# Парсинг .plog в формате NewDataSet -> PVS-Studio_Analysis_Log
def parse_plog(path: Path, workspace: str = None) -> tuple[etree.Element, list[dict]]:
    warnings = []
    root = etree.Element('NewDataSet')
    if not path.exists():
        logging.warning(f'File not found: {path}')
        return root, warnings
    try:
        tree = etree.parse(str(path))
        root = tree.getroot()
    except Exception as e:
        logging.exception(f'Failed to parse {path}: {e}')
        return root, warnings

    # Ищем все блоки PVS-Studio_Analysis_Log
    pvs_blocks = root.findall('PVS-Studio_Analysis_Log')
    logging.debug(f'Found {len(pvs_blocks)} PVS-Studio_Analysis_Log blocks in {path.name}')

    for block in pvs_blocks:
        file_elem = block.find('File')
        line_elem = block.find('Line')
        code_elem = block.find('ErrorCode')

        file_raw = file_elem.text.strip() if file_elem is not None and file_elem.text else ''
        line_str = line_elem.text.strip() if line_elem is not None and line_elem.text else '0'
        code = code_elem.text.strip() if code_elem is not None and code_elem.text else ''

        file_key = to_absolute(file_raw, workspace) if workspace else normalize_path(file_raw, for_key=True)
        try:
            line = int(line_str)
        except ValueError:
            line = 0
        col = 0   # столбец в этой схеме отсутствует

        warning_key = (file_key, line, col, code)
        warnings.append({
            'element': block,          # сам блок PVS-Studio_Analysis_Log
            'file_raw': file_raw,
            'file_key': file_key,
            'line': line,
            'col': col,
            'code': code,
            'warning_key': warning_key,
        })

    logging.debug(f'Parsed {path.name}: {len(warnings)} warnings extracted')
    return root, warnings


# Слияние полного и инкрементального отчётов
def merge_full_inc(full_plog: Path, inc_plog: Path, affected_files, workspace: str) -> etree.Element:
    """
    - affected_files: множество абсолютных путей файлов, затронутых изменениями.
      Может быть None (нет данных), пустым (изменений нет) или непустым.
    - Для файлов, не входящих в affected_files, сохраняются предупреждения из полного отчёта.
    - Все предупреждения инкрементального отчёта добавляются.
    - Дедупликация по ключу (file, line, col, code).
    """
    root_full, full_warns = parse_plog(full_plog, workspace)
    root_inc, inc_warns = parse_plog(inc_plog, workspace)

    logging.debug(f'Full report: {len(full_warns)} warnings, Incremental: {len(inc_warns)} warnings')
    if affected_files is None:
        logging.info('affected_files=None – no change data, keeping all full-report warnings')
    else:
        logging.debug(f'affected_files contains {len(affected_files)} files')
        if len(affected_files) <= 20:
            logging.debug(f'Affected: {affected_files}')
        else:
            logging.debug(f'Affected (first 20): {list(affected_files)[:20]}')

    if not inc_warns:
        logging.info('No incremental warnings, returning full report as-is')
        return root_full if full_warns else root_inc

    # Собираем итоговый словарь предупреждений: ключ -> объект предупреждения
    merged = {}

    # 1. Инкрементальный отчёт (весь)
    for w in inc_warns:
        merged[w['warning_key']] = w

    # 2. Полный отчёт: добавляем только для незатронутых файлов
    kept_from_full = 0
    skipped_affected = 0
    skipped_duplicate = 0
    for w in full_warns:
        key = w['warning_key']
        if affected_files is None:
            # без данных – всё сохраняем
            if key not in merged:
                merged[key] = w
                kept_from_full += 1
            else:
                skipped_duplicate += 1
        else:
            # Удаляем старые предупреждения для любого изменённого файла
            if w['file_key'] in affected_files:
                skipped_affected += 1
                logging.debug(f'Dropping full-report warning (affected file): {w["file_raw"]} ({key})')
            elif key not in merged:
                merged[key] = w
                kept_from_full += 1
            else:
                skipped_duplicate += 1

    logging.info(f'Merge results: kept_from_full={kept_from_full}, skipped_affected={skipped_affected}, skipped_duplicate={skipped_duplicate}, total={len(merged)}')

    # Формируем новый XML
    if inc_warns:
        new_root = etree.fromstring(etree.tostring(root_inc))  # глубокая копия
    else:
        new_root = etree.fromstring(etree.tostring(root_full))

    # Удаляем все существующие блоки PVS-Studio_Analysis_Log
    for block in new_root.findall('PVS-Studio_Analysis_Log'):
        new_root.remove(block)

    # Добавляем отобранные блоки
    for w in merged.values():
        new_root.append(w['element'])

    return new_root


# Кросс-платформенное слияние Windows + Linux
def merge_cross_os(win_plog: Path, linux_plog: Path, output_plog: Path, workspace: str):
    """Объединяет отчёты с заменой Windows-путей на Linux."""
    root_win, win_warns = parse_plog(win_plog, workspace)
    root_linux, linux_warns = parse_plog(linux_plog, workspace)

    # Пути Windows уже нормализованы в parse_plog, но ещё содержат диск и бэкслеши.
    # Производим замену на лету при формировании ключа для дедупликации.
    def linux_path_for_key(file_raw: str) -> str:
        p = file_raw
        # Заменяем D:\ или D:/ на /home/builder@arqa.ru/
        if p.startswith('D:') and len(p) > 2 and p[2] in ('\\', '/'):
            p = '/home/builder@arqa.ru' + p[2:]
        p = p.replace('\\', '/')
        return normalize_path(p, for_key=True)

    merged_by_key = {}
    # сначала Linux (приоритет при совпадении)
    for w in linux_warns:
        key = (linux_path_for_key(w['file_raw']), w['line'], w['col'], w['code'])
        merged_by_key[key] = w

    win_added = 0
    win_duplicates = 0
    for w in win_warns:
        key = (linux_path_for_key(w['file_raw']), w['line'], w['col'], w['code'])
        if key not in merged_by_key:
            # Заменяем Windows-путь на Linux в <File>
            file_elem = w['element'].find('File')
            if file_elem is not None:
                new_path = w['file_raw']
                if new_path.startswith('D:') and len(new_path) > 2 and new_path[2] in ('\\', '/'):
                    new_path = '/home/builder@arqa.ru' + new_path[2:]
                new_path = new_path.replace('\\', '/')
                file_elem.text = new_path

            # Заменяем Windows-пути в <Positions>
            positions_elem = w['element'].find('Positions')
            if positions_elem is not None:
                for pos in positions_elem.findall('Position'):
                    if pos.text:
                        pt = pos.text
                        if pt.startswith('D:') and len(pt) > 2 and pt[2] in ('\\', '/'):
                            pt = '/home/builder@arqa.ru' + pt[2:]
                        pt = pt.replace('\\', '/')
                        pos.text = pt

            merged_by_key[key] = w
            win_added += 1
        else:
            win_duplicates += 1

    logging.debug(f'Cross-OS merge: Linux warnings = {len(linux_warns)}, Windows warnings = {len(win_warns)}')
    logging.debug(f'Cross-OS merge: added {win_added} Windows warnings, {win_duplicates} duplicates (kept Linux version)')

    # Формируем итоговый XML
    if linux_warns:
        new_root = etree.fromstring(etree.tostring(root_linux))
    else:
        new_root = etree.fromstring(etree.tostring(root_win))

    # Удаляем все старые блоки PVS-Studio_Analysis_Log
    for block in new_root.findall('PVS-Studio_Analysis_Log'):
        new_root.remove(block)

    for w in merged_by_key.values():
        new_root.append(w['element'])

    # Запись с pretty-print
    tree = etree.ElementTree(new_root)
    tree.write(str(output_plog), encoding='utf-8', xml_declaration=True, pretty_print=True)
    logging.debug(f'Cross-OS merged report saved to {output_plog}')


def main():
    workspace = os.getenv('WORKSPACE')
    group = os.getenv('GROUP')
    sonar_project = os.getenv('SONAR_PROJECT_NAME')
    dir_for_python = os.getenv('DIR_FOR_PYTHON')

    if not all([workspace, group, sonar_project, dir_for_python]):
        logging.error('Missing required environment variables')
        sys.exit(1)

    base_dir = Path(workspace) / 'pvs_inc_hashes' / group / sonar_project
    inc_dir = Path(dir_for_python)

    system = platform.system()
    logging.debug(f'Running on {system}, workspace={workspace}')

    if system == 'Windows':
        full_win = base_dir / 'pvs-win.plog'
        inc_win = inc_dir / 'pvs-win.plog'

        if not inc_win.exists():
            logging.error(f'Incremental Windows report not found: {inc_win}')
            sys.exit(1)

        # Определяем затронутые TU через .pvs-hash
        hash_before = inc_dir / '.pvs-hash_copy'
        hash_after = inc_dir / '.pvs-hash'
        affected = get_affected_files_windows(hash_before, hash_after, workspace)
        # Если affected None (нет состояния), то передадим None для сохранения всего

        if affected is not None:
            logging.debug(f'Windows affected files: {len(affected)}')
        else:
            logging.warning('No affected files data – full report will be kept completely')

        merged_tree = merge_full_inc(full_win, inc_win, affected, workspace)

        full_win.parent.mkdir(parents=True, exist_ok=True)
        tree = etree.ElementTree(merged_tree)
        tree.write(str(full_win), encoding='utf-8', xml_declaration=True, pretty_print=True)
        logging.debug(f'Windows full report updated: {full_win}')

    elif system == 'Linux':
        full_linux = base_dir / 'pvs-linux.plog'
        inc_linux = inc_dir / 'pvs-linux.plog'

        if not inc_linux.exists():
            logging.error(f'Incremental Linux report not found: {inc_linux}')
            sys.exit(1)

        # Определяем затронутые TU через modified_files.txt + depend_info.json
        modified_path = inc_dir / 'modified_files.txt'
        depend_path = inc_dir / 'depend_info.json'
        affected = get_affected_files_linux(modified_path, depend_path, workspace)

        if affected is not None:
            logging.debug(f'Linux affected files: {len(affected)}')
        else:
            logging.warning('No modified_files.txt – full report will be kept completely')

        merged_linux = merge_full_inc(full_linux, inc_linux, affected, workspace)

        full_linux.parent.mkdir(parents=True, exist_ok=True)
        tree = etree.ElementTree(merged_linux)
        tree.write(str(full_linux), encoding='utf-8', xml_declaration=True, pretty_print=True)
        logging.debug(f'Linux full report updated: {full_linux}')

        # Кроссплатформенное объединение
        full_win = base_dir / 'pvs-win.plog'
        if not full_win.exists():
            logging.error(f'Windows report not found for cross-OS merge: {full_win}')
            sys.exit(1)
        merge_cross_os(full_win, full_linux, inc_dir / 'pvs.plog', workspace)

    else:
        logging.error(f'Unsupported OS: {system}')
        sys.exit(1)


if __name__ == '__main__':
    main()
