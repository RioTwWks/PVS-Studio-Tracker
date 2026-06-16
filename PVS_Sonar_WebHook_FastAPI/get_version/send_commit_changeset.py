from glob import glob
import http.client
import json
import logging
from os import getenv
from re import search
from urllib import parse

logging.basicConfig(level=logging.DEBUG)

# Получение переменных среды
group = getenv('GROUP')
sonar_project_key = getenv('SONAR_PROJECT_KEY')
sonar_project_name = getenv('SONAR_PROJECT_NAME')
proj_dir = getenv('DIR_FOR_PYTHON')
commit_changeset = getenv('COMMIT')

# Отправка коммита в БД сервера
def send_commit_changeset(sonar_project_key, commit_changeset):
    logging.debug(f"Отправка POST запроса с версией к FastAPI серверу...")

    form_data = {
        "project_key": sonar_project_key,
        "commit_changeset": commit_changeset
    }
    logging.debug(f"Передаваемые параметры: {form_data}")

    # Кодируем данные
    encoded_data = parse.urlencode(form_data)

    # Устанавливаем соединение
    conn = http.client.HTTPConnection("qube", 8080, timeout=10)

    try:
        # Отправляем запрос
        conn.request(
            "POST",
            "/project/last_commit_changeset",
            body=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(encoded_data)),
                "User-Agent": "PostClient/1.0"
            }
        )

        # Получаем ответ
        response = conn.getresponse()

        logging.debug(f"Статус: {response.status} {response.reason}")

        # Читаем ответ
        response_body = response.read().decode('utf-8')

        if response.status == 200:
            logging.debug(f"Запрос успешно выполнен")

            # Пытаемся распарсить JSON
            try:
                json_response = json.loads(response_body)
                logging.debug(f"JSON ответ: {json.dumps(json_response, indent=2, ensure_ascii=False)}")
            except:
                logging.debug(f"Текстовый ответ: {response_body}")
        else:
            logging.error(f"Ошибка запроса: {response.status}")
            logging.error(f"Тело ответа: {response_body}")

        return response.status, response_body

    except Exception as e:
        logging.error(f"Ошибка при отправке запроса: {e}")
        raise
    finally:
        conn.close()

status, response = send_commit_changeset(sonar_project_key, commit_changeset)