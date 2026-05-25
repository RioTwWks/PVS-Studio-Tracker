# Быстрый тест, чтобы узнать, может ли приложение запуститься

try:
    from slowapi import Limiter
    print("✓ slowapi установлен")
except ImportError as e:
    print(f"✗ slowapi НЕ установлен: {e}")
    print("  Запуск: pip install -r requirements.txt")

try:
    from app.main import app
    print("✓ app.main успешно импортирован")
except Exception as e:
    print(f"✗ импорт app.main провалился: {e}")
