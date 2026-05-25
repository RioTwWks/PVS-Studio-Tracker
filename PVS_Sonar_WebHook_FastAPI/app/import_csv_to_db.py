import sqlite3
import csv

def csv_to_sqlite(csv_file, db_file, table_name):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Проверяем, существует ли таблица
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    with open(csv_file, 'r', encoding='utf-8') as file:
        csv_reader = csv.reader(file)
        headers = next(csv_reader)

        # Если таблицы нет — создаём её с колонками из CSV
        if not table_exists:
            columns = ', '.join([f'"{col}" TEXT' for col in headers])
            cursor.execute(f'CREATE TABLE {table_name} ({columns})')
        # Если таблица есть, предполагаем, что структура совпадает с заголовками CSV

        # Подготавливаем запрос на вставку
        placeholders = ', '.join(['?'] * len(headers))
        insert_sql = f'INSERT INTO {table_name} VALUES ({placeholders})'

        # Вставляем все строки
        for row in csv_reader:
            cursor.execute(insert_sql, row)

    conn.commit()
    conn.close()

# Пример использования
csv_to_sqlite('files.csv', 'pvs_sonar.db', 'files')
