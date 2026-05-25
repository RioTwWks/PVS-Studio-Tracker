import hashlib
from pathlib import Path

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

print(calculate_sha256(r'\\qlen\SoftPile\quik\2Test\QuikLimit\5.0.0\quiklimit\windows\QL_Test.exe'))
