import subprocess
import shutil
import json
import re
import hashlib
import tempfile
import win32api
import logging
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from pydantic import BaseModel
import requests

from .config import settings

logger = logging.getLogger(__name__)


# Конфигурация API сервера (для запуска через планировщик)
API_BASE_URL = settings.get("API_BASE_URL", "http://localhost:8080")
API_SCAN_ENDPOINT = f"{API_BASE_URL}/api/scan-results"


# Модели данных для передачи результатов через API
class FileScanResult(BaseModel):
    # Результат сканирования одного файла
    project_key: str
    filename: str
    version: str
    file_hash: str


class ScanResult(BaseModel):
    # Результаты сканирования всех файлов
    files: List[FileScanResult]


def send_scan_results_to_api(scan_result: dict, api_url: str = None):
    """
    Отправить результаты сканирования на FastAPI сервер.

    Scanner.py запускается через планировщик задач Windows от имени sast_bot
    и отправляет результаты через REST API вместо прямого доступа к БД.

    Args:
        scan_result: Словарь с результатами сканирования {'files': [...]}
        api_url: URL endpoint (по умолчанию http://localhost:8080/api/scan-results)

    Returns:
        True если успешно, False иначе
    """
    if api_url is None:
        api_url = "http://localhost:8080/api/scan-results"

    try:
        logger.info(f"📤 Отправка {len(scan_result.get('files', []))} результатов на {api_url}")
        response = requests.post(api_url, json=scan_result, timeout=30)
        response.raise_for_status()
        logger.info(f"✅ Результаты успешно отправлены: {response.json()}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки результатов через API: {e}")
        return False


# Извлекает информацию о версии, описании, копирайте из PE‑файла
def get_pe_version_info(filepath):
    filepath = Path(filepath).resolve()
    if not filepath.exists():
        raise FileNotFoundError(f"Файл не найден: {filepath}")
    try:
        info = win32api.GetFileVersionInfo(str(filepath), "\\")
        trans = win32api.GetFileVersionInfo(str(filepath), "\\VarFileInfo\\Translation")
        if not trans:
            lang, codepage = 0x0409, 0x04E4
        else:
            lang, codepage = trans[0]

        def get_prop(prop_name):
            try:
                str_info = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{prop_name}"
                return win32api.GetFileVersionInfo(str(filepath), str_info)
            except:
                return None

        def format_version(ms, ls):
            return f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"

        file_ms = info.get('FileVersionMS', 0)
        file_ls = info.get('FileVersionLS', 0)
        prod_ms = info.get('ProductVersionMS', 0)
        prod_ls = info.get('ProductVersionLS', 0)

        return {
            "FileDescription": get_prop("FileDescription"),
            "FileVersion": format_version(file_ms, file_ls) if file_ms or file_ls else get_prop("FileVersion"),
            "ProductVersion": format_version(prod_ms, prod_ls) if prod_ms or prod_ls else get_prop("ProductVersion"),
            "ProductName": get_prop("ProductName"),
            "LegalCopyright": get_prop("LegalCopyright"),
            "CompanyName": get_prop("CompanyName"),
            "OriginalFilename": get_prop("OriginalFilename"),
        }
    except Exception as e:
        return {"error": f"Ошибка получения версии: {e}"}


# Получает информацию о цифровых подписях через PowerShell
def get_digital_signatures(filepath):
    filepath = Path(filepath).resolve()
    if not filepath.exists():
        raise FileNotFoundError(f"Файл не найден: {filepath}")

    ps_script = f'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
try {{
    $sig = Get-AuthenticodeSignature -LiteralPath "{filepath}"
    if ($sig.Status -eq "Valid") {{
        $cert = $sig.SignerCertificate
        $result = @{{
            Status = $sig.Status.ToString()
            StatusMessage = $sig.StatusMessage
            IsOSBinary = $sig.IsOSBinary
            SignerCertificate = @{{
                Subject = $cert.Subject
                Issuer = $cert.Issuer
                Thumbprint = $cert.Thumbprint
                SerialNumber = $cert.GetSerialNumberString()
                NotBefore = $cert.NotBefore.ToString('yyyy-MM-dd HH:mm:ss')
                NotAfter = $cert.NotAfter.ToString('yyyy-MM-dd HH:mm:ss')
                FriendlyName = $cert.FriendlyName
                HasPrivateKey = $cert.HasPrivateKey
                SignatureAlgorithm = $cert.SignatureAlgorithm.FriendlyName
            }}
        }}
        if ($sig.TimeStamperCertificate) {{
            $result.TimeStamperCertificate = @{{
                Subject = $sig.TimeStamperCertificate.Subject
                Thumbprint = $sig.TimeStamperCertificate.Thumbprint
                NotBefore = $sig.TimeStamperCertificate.NotBefore.ToString('yyyy-MM-dd HH:mm:ss')
                NotAfter = $sig.TimeStamperCertificate.NotAfter.ToString('yyyy-MM-dd HH:mm:ss')
            }}
            $result.SigningTime = $sig.TimeStamperCertificate.NotBefore.ToString('yyyy-MM-dd HH:mm:ss')
        }}
        if ($sig.SignatureType -eq "Catalog") {{
            $result.SignatureType = "Catalog"
            $hash = (Get-FileHash -Path "{filepath}" -Algorithm SHA1).Hash
            $result.FileHash = $hash
        }}
        $result | ConvertTo-Json -Depth 5
    }} elseif ($sig.Status -eq "NotSigned") {{
        @{{ "Status" = "NotSigned" }} | ConvertTo-Json
    }} else {{
        @{{ "Status" = $sig.Status.ToString(); "StatusMessage" = $sig.StatusMessage }} | ConvertTo-Json
    }}
}} catch {{
    @{{ "error" = $_.Exception.Message }} | ConvertTo-Json
}}
'''
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        if result.returncode != 0:
            return {"error": f"PowerShell failed (code {result.returncode}): {result.stderr[:200]}"}
        output = result.stdout.strip()
        if not output:
            return {"error": "PowerShell вернул пустой вывод"}
        return json.loads(output)
    except Exception as e:
        return {"error": f"Исключение: {type(e).__name__}: {e}"}


# Извлекает точное время подписания из certutil -dump (UTC datetime)
def get_signing_time_from_certutil(filepath):
    filepath = Path(filepath).resolve()
    if not filepath.exists():
        return None
    try:
        result = subprocess.run(
            ["certutil", "-dump", str(filepath)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=30
        )
        output = result.stdout + result.stderr
        patterns = [
            r'GENERALIZED_TIME\s*[:=]\s*(\d{14,15}Z)',
            r'UTCTime\s*[:=]\s*(\d{12}Z)',
            r'(?:Signing|Signature|Timestamp|Signer\s+Signing)\s+Time\s*[:=]\s*(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})',
            r'Общее\s+время\s*[:=]\s*(\d{14,15}Z)',
            r'Время\s+(?:подписания|штампа)\s*[:=]\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})',
            r'(\d{14}Z)',
            r'(\d{12}Z)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, output, re.IGNORECASE)
            for time_str in matches:
                if time_str.upper().endswith('Z'):
                    digits = time_str[:-1]
                    if len(digits) == 14:
                        dt = datetime.strptime(digits, '%Y%m%d%H%M%S')
                    elif len(digits) == 12:
                        dt = datetime.strptime(digits, '%y%m%d%H%M%S')
                    else:
                        continue
                    return dt.replace(tzinfo=timezone.utc)
                elif re.match(r'\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}', time_str):
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
                        try:
                            dt = datetime.strptime(time_str, fmt)
                            return dt.replace(tzinfo=timezone.utc)
                        except:
                            continue
                elif re.match(r'\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}', time_str):
                    dt = datetime.strptime(time_str, '%d.%m.%Y %H:%M:%S')
                    return dt.replace(tzinfo=timezone.utc)
        return None
    except Exception:
        return None


# Запускает robocopy /L /S /MAXAGE:<max_age> и возвращает список полных путей к файлам
def run_robocopy_and_get_files(source_dir, log_dir=None, max_age=1):
    if log_dir:
        log_path = Path(log_dir) / "robocopy_filelist.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temp_log = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False, encoding='utf-8')
        log_path = Path(temp_log.name)
        temp_log.close()

    cmd = [
        "robocopy", str(source_dir), str(Path("D:\\temp")),
        "/L", "/S", f"/MAXAGE:{max_age}",
        "/FP", "/NJH", "/NJS", "/NS", "/NC", "/NDL",
        "/MT:8", f"/LOG:{log_path}"
    ]

    logging.debug(f"Robocopy: поиск файлов, изменённых за последние {max_age} сутки...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='cp866', errors='replace')

    if result.returncode >= 8:
        raise RuntimeError(f"Robocopy ошибка (код {result.returncode}): {result.stderr}")

    if not log_path.exists():
        raise FileNotFoundError(f"Лог-файл не создан: {log_path}")

    file_paths = []
    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            # Простейшая проверка: похоже на путь Windows
            if line and len(line) > 3 and line[1] == ':' and line[2] == '\\':
                file_paths.append(line)
            elif line.startswith('\\') or line.startswith('"') or line.startswith("'"):
                cleaned = line.strip('"\'').strip()
                if cleaned and (Path(cleaned).drive or cleaned.startswith('\\\\')):
                    file_paths.append(cleaned)

    if not log_dir:
        log_path.unlink(missing_ok=True)

    logging.info(f"Robocopy: найдено {len(file_paths)} файлов (все типы).")
    return file_paths


# Оставляет только файлы с заданными расширениями (без учёта регистра)
def filter_files_by_extension(file_paths, extensions=None):     # extensions: множество расширений, например {'.exe', '.dll'}
    if extensions is None:
        extensions = {'.exe', '.dll'}
    filtered = []
    for path_str in file_paths:
        p = Path(path_str)
        if p.suffix.lower() in extensions:
            filtered.append(path_str)
    logging.debug(f"После фильтрации по {extensions}: осталось {len(filtered)} файлов.")
    return filtered


# Вычисляет SHA-256 хэш файла
def calculate_sha256(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    path = Path(file_path)

    # Проверка существования файла
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    # Открытие файла в бинарном режиме ('rb')
    with open(path, "rb") as f:
        # Чтение файла частями (chunks), чтобы не загружать весь файл в память
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


# Анализирует один файл: версия, подпись, время подписания, хэш
def process_single_file(filepath: Path) -> dict:
    result = {
        "file_path": str(filepath),
        "file_name": filepath.name,
        "last_modified": None,
        "sha256": None,
        "version_info": {},
        "signature_info": {},
        "signing_time_utc": None,
        "error": None
    }
    try:
        if not filepath.exists():
            result["error"] = "Файл не существует"
            return result

        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
        result["last_modified"] = mtime.isoformat()

        result["sha256"] = calculate_sha256(filepath)
        result["version_info"] = get_pe_version_info(filepath)
        result["signature_info"] = get_digital_signatures(filepath)

        signing_time = get_signing_time_from_certutil(filepath)
        if signing_time:
            result["signing_time_utc"] = signing_time.isoformat()

    except Exception as e:
        result["error"] = f"Необработанное исключение: {type(e).__name__}: {e}"
    return result


# Копирует файл во временную папку, удаляет цифровую подпись (если есть) и возвращает SHA256 хэш файла без подписи
def get_hash_without_signature(original_path: Path, temp_dir: Path, signtool_path: Path) -> str:
    # Создаём уникальное имя для временной копии
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    temp_filename = f"temp_{original_path.stem}_{timestamp}{original_path.suffix}"
    temp_file = temp_dir / temp_filename

    # Копируем оригинал
    shutil.copy2(original_path, temp_file)
    logger.debug(f"Создана временная копия: {temp_file}")

    try:
        # Запускаем signtool remove
        cmd = [str(signtool_path), "remove", "/s", str(temp_file)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            # Если удаление не удалось (например, файл не подписан), логируем предупреждение
            logger.warning(
                f"signtool remove вернул код {result.returncode} для {original_path.name}. "
                f"Stderr: {result.stderr.strip()}"
            )
            # В этом случае считаем, что подпись отсутствует – хэш останется как у копии (равной оригиналу)

        # Вычисляем SHA256 полученного файла (после возможного удаления подписи)
        file_hash = calculate_sha256(temp_file)
        return file_hash

    finally:
        # Удаляем временный файл
        temp_file.unlink(missing_ok=True)
        logger.debug(f"Временный файл удалён: {temp_file}")


# Запускает сканирование, обрабатывает файлы и сохраняет версии в БД
def run_scan():
    source_dir = Path(settings.SCAN_SOURCE_DIR)
    log_dir = Path(settings.SCAN_LOG_DIR) if settings.SCAN_LOG_DIR else None
    max_age = settings.SCAN_MAX_AGE_DAYS
    target_extensions = set(settings.SCAN_TARGET_EXTENSIONS)
    expected_subject_pattern = settings.SCAN_EXPECTED_CERT_SUBJECT  # может быть подстрокой или регуляркой

    logger.info(f"Начало сканирования в {source_dir} за последние {max_age} сутки")

    # 1. Получаем все изменённые файлы через robocopy
    all_files = run_robocopy_and_get_files(source_dir, log_dir, max_age)
    files_to_analyze = filter_files_by_extension(all_files, target_extensions)

    if not files_to_analyze:
        logger.info("Нет файлов для анализа.")
        return

    # 2. Анализируем параллельно
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_path = {executor.submit(process_single_file, Path(p)): p for p in files_to_analyze}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                data = future.result()
                results.append(data)
            except Exception as e:
                logger.error(f"Ошибка при обработке {path}: {e}")
                results.append({"file_path": path, "error": f"Ошибка потока: {e}"})

    # 3. Формирование результатов для отправки через API
    api_results = {"files": []}

    for file_data in results:
        file_path = file_data["file_path"]
        file_name = Path(file_path).name.lower()
        error = file_data.get("error")
        if error:
            logger.error(f"Ошибка обработки {file_name}: {error}")
            continue

        if file_name == "ql_test.exe":
            logger.info(f"Файл {file_name} не имеет версии (для тестов), пропускаем.")
            continue

        # Проверяем Subject сертификата
        sig_info = file_data.get("signature_info", {})
        signer_cert = sig_info.get("SignerCertificate", {})
        subject_name = signer_cert.get("Subject", "")
        if expected_subject_pattern.lower() and expected_subject_pattern.lower() not in subject_name.lower():
            logger.info(f"Файл {file_name} имеет неподходящий сертификат (subject: {subject_name}), пропускаем.")
            continue

        original_path = Path(file_data["file_path"])
        temp_dir = Path(settings.TEMP_DIR)
        signtool_path = Path(settings.SIGNTOOL_PATH)

        try:
            hash_without_sig = get_hash_without_signature(original_path, temp_dir, signtool_path)
        except Exception as e:
            logger.error(f"Не удалось получить хэш без подписи для {file_name}: {e}")
            continue

        # Извлекаем данные для отправки
        version = file_data.get("version_info", {}).get("FileVersion")
        if not version:
            logger.warning(f"Файл {file_name} не имеет версии. Пропускаем.")
            continue

        # Добавляем в результаты
        # project_key берём из настроек или из пути к файлу
        api_results["files"].append({
            "project_key": settings.get("SCAN_PROJECT_KEY", "unknown"),
            "filename": file_name,
            "version": version,
            "file_hash": hash_without_sig
        })

    # Отправляем результаты через API
    if api_results["files"]:
        logger.info(f"📤 Найдено {len(api_results['files'])} файлов для отправки")
        send_scan_results_to_api(api_results, API_SCAN_ENDPOINT)
    else:
        logger.info("Нет результатов для отправки")

    logger.info("Сканирование завершено.")


# Функции для отправки результатов через API (для запуска через планировщик)
def send_scan_results_to_api(scan_result: dict, api_url: str = None):
    """
    Отправить результаты сканирования на FastAPI сервер.

    Scanner.py запускается через планировщик задач Windows от имени sast_bot
    и отправляет результаты через REST API вместо прямого доступа к БД.

    Args:
        scan_result: Словарь с результатами сканирования {'files': [...]}
        api_url: URL endpoint (по умолчанию http://localhost:8080/api/scan-results)

    Returns:
        True если успешно, False иначе
    """
    if api_url is None:
        api_url = "http://localhost:8080/api/scan-results"

    try:
        logger.info(f"📤 Отправка {len(scan_result.get('files', []))} результатов на {api_url}")
        response = requests.post(api_url, json=scan_result, timeout=30)
        response.raise_for_status()
        logger.info(f"✅ Результаты успешно отправлены: {response.json()}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки результатов через API: {e}")
        return False
