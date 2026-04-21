"""
PVS-Studio Snapshot Builder — с улучшенной обработкой кодировок для Windows C++ проектов.
"""
import json
import gzip
import os
import sys
from pathlib import Path
from typing import Set

def read_file_with_fallback(file_path: Path) -> tuple[str, str]:
    """
    Читает файл с приоритетом кодировок для Windows C++ проектов.
    Возвращает (content, used_encoding).
    """
    ext = file_path.suffix.lower()
    
    # 🔑 Для .cpp/.h/.c на Windows: пробуем cp1251 ПЕРВЫМ с strict режимом
    if os.name == 'nt' and ext in ['.cpp', '.h', '.c', '.hpp', '.cxx', '.cc']:
        encodings_priority = [
            ('cp1251', 'strict'),   # Windows Cyrillic — первая попытка
            ('cp866', 'strict'),    # DOS/OEM Cyrillic
            ('utf-8', 'strict'),    # UTF-8 без BOM
            ('utf-8-sig', 'strict'),# UTF-8 с BOM
            ('cp1251', 'replace'),  # Fallback с заменой
            ('cp866', 'replace'),
            ('utf-8', 'replace'),
            ('latin-1', 'replace'), # Universal fallback
        ]
    else:
        # Для остальных файлов: стандартный порядок
        encodings_priority = [
            ('utf-8', 'strict'),
            ('utf-8-sig', 'strict'),
            ('cp1251', 'strict'),
            ('cp866', 'strict'),
            ('cp1251', 'replace'),
            ('utf-8', 'replace'),
            ('latin-1', 'replace'),
        ]
    
    for enc, errors in encodings_priority:
        try:
            content = file_path.read_text(encoding=enc, errors=errors)
            
            # Если strict режим сработал — возвращаем сразу
            if errors == 'strict':
                return content, enc
                
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        except Exception:
            continue
    
    # Если ничего не сработало — возвращаем пустую строку
    print(f"❌ Could not read {file_path.name} with any encoding", file=sys.stderr)
    return "", "failed"

def build_snapshot(report_path: str, output_path: str, base_dir: str = "."):
    """Создаёт снапшот исходного кода для файлов из отчёта."""
    
    # Читаем отчёт
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Извлекаем список файлов
    warnings = report.get("warnings", report if isinstance(report, list) else [])
    file_paths: Set[str] = set()

    for w in warnings:
        for pos in w.get("positions", []):
            fp = pos.get("file", "")
            if fp and not fp.startswith("__analysis__"):
                file_paths.add(fp)
        fp = w.get("fileName", "")
        if fp:
            file_paths.add(fp)

    # Читаем содержимое файлов
    snapshot = {}
    base = Path(base_dir).resolve()
    
    print(f"📦 Building snapshot for {len(file_paths)} files...", file=sys.stderr)

    for rel_path in file_paths:
        full_path = base / rel_path
        if full_path.exists() and full_path.is_file():
            try:
                content, used_enc = read_file_with_fallback(full_path)
                
                if used_enc == "failed" or not content:
                    print(f"⚠️ Skipped unreadable file: {rel_path}", file=sys.stderr)
                    continue
                
                # 🔍 Логируем результат
                has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in content[:500])
                print(f"✅ Read: {rel_path} (encoding: {used_enc}, cyrillic: {has_cyrillic})", file=sys.stderr)
                
                # 🔍 Проверяем на "кракозябры" ТОЛЬКО если кириллица НЕ детектирована
                # (если кириллица есть — файл прочитан верно,  могут быть артефактами)
                if '' in content[:200] and not has_cyrillic:
                    print(f"⚠️ Warning:  symbols found in {rel_path} (read as {used_enc})", file=sys.stderr)
                
                key = rel_path.replace("\\", "/")
                snapshot[key] = content
                
            except Exception as e:
                print(f"❌ Failed to process {rel_path}: {e}", file=sys.stderr)
        else:
            print(f"⚠️ File not found: {full_path}", file=sys.stderr)

    # Запись снапшота
    print(f"💾 Writing snapshot to {output_path}...", file=sys.stderr)
    try:
        with gzip.open(output_path, "wt", encoding="utf-8", errors="replace") as f:
            json.dump(
                snapshot, 
                f, 
                ensure_ascii=False,  # 🔑 Сохраняет русские символы как есть
                indent=2, 
                default=str,
                sort_keys=True
            )
        size_kb = os.path.getsize(output_path) / 1024
        print(f"✅ Snapshot created: {output_path} ({len(snapshot)} files, {size_kb:.1f} KB)", file=sys.stderr)
        
    except Exception as e:
        print(f"❌ Failed to write snapshot: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python pvs_snapshot.py <report.json> <output.json.gz> [base_dir]")
        sys.exit(1)
    
    build_snapshot(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ".")
