import sys
from pathlib import Path
# Добавляем путь к проекту, чтобы импортировать модули app
sys.path.append(str(Path(__file__).parent))

from app.scanner import run_scan
import logging

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    run_scan()
