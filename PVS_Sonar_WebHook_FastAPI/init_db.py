# Инициализация БД

from app.database import engine
from app import models

def main():
    print("Создание таблиц БД...")
    models.Base.metadata.create_all(bind=engine)
    print("✓ БД успешно инициализирована!")

if __name__ == "__main__":
    main()
