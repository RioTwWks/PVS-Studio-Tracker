# Установка зависимостей

import subprocess
import sys

packages = [
    "slowapi==0.1.9",
    "redis==5.2.1",
    "pytest==8.3.5",
    "pytest-asyncio==0.24.0",
    "pytest-cov==6.0.0",
    "httpx==0.28.1",
    "respx==0.22.0",
]

print("Установка зависимостей...")
for package in packages:
    print(f"Установка {package}...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

print("Все зависимости успешно установлены!")
