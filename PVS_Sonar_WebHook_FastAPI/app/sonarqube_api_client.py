from datetime import date
import json
import requests
import logging
import re
from typing import Dict, List, Optional, Tuple

from .config import settings
from .cache import get_cache, CacheTTL

logger = logging.getLogger("sonarqube_api")

class SonarQubeAPIClient:

    def __init__(self):
        self.base_url = settings.SONARQUBE_URL
        self.session = requests.Session()
        self._cache = get_cache()

    # Получить метрики проекта
    def get_project_measures(self, project_key: str, metrics: List[str] = None) -> Dict:
        # Try cache first
        cached = self._cache.get("measures/component", {"component": project_key})
        if cached is not None:
            logger.debug(f"Cache hit for project measures: {project_key}")
            return cached

        if metrics is None:
            metrics = [
                "bugs", "vulnerabilities", "code_smells",
                "coverage", "duplicated_lines_density",
                "ncloc", "reliability_rating", "security_rating",
                "sqale_rating", "alert_status"
            ]

        url = f"{self.base_url}/api/measures/component"
        params = {
            "component": project_key,
            "metricKeys": ",".join(metrics)
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            # Cache the result
            self._cache.set("measures/component", result, {"component": project_key}, CacheTTL.MEASURES)
            return result
        except Exception as e:
            logger.error(f"Ошибка получения метрик для {project_key}: {e}")
            return {}

    # Получить проблемы проекта
    def get_project_issues(self, project_key: str, types: List[str] = None) -> Dict:
        # Try cache first
        cache_params = {"componentKeys": project_key, "types": types}
        cached = self._cache.get("issues/search", cache_params)
        if cached is not None:
            logger.debug(f"Cache hit for project issues: {project_key}")
            return cached

        today = date.today()

        if types is None:
            types = ["BUG", "VULNERABILITY", "CODE_SMELL"]

        url = f"{self.base_url}/api/issues/search"
        params = {
            "componentKeys": project_key,
            "types": ",".join(types),
            "resolved": "false",
            "inNewCodePeriod": "true"
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            # Cache the result
            self._cache.set("issues/search", result, cache_params, CacheTTL.ISSUES)
            return result
        except Exception as e:
            logger.error(f"Ошибка получения проблем для {project_key}: {e}")
            return {}

    # Получает список исправленных (Fixed) проблем для проекта.
    def get_fixed_issues(self, project_key: str, additional_params: dict = None) -> Tuple[bool, Dict]:
        # Try cache first
        cache_params = {"componentKeys": project_key, "additional": additional_params}
        cached = self._cache.get("issues/search:fixed", cache_params)
        if cached is not None:
            logger.debug(f"Cache hit for fixed issues: {project_key}")
            return True, cached

        api_url = f"{self.base_url}/api/issues/search"

        # Базовые параметры для запроса исправленных проблем
        params = {
            'componentKeys': project_key,
            'resolutions': 'FIXED',
            's': 'FILE_LINE'  # Сортировка для стабильного результата при пагинации
        }

        # Добавляем дополнительные параметры фильтрации, если они переданы
        if additional_params:
            params.update(additional_params)

        logger.info(f"Запрос исправленных проблем для проекта: {project_key}")

        try:
            # Используем сессию с авторизацией
            response = self.session.get(api_url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                total_fixed = data.get('total', 0)
                logger.info(f"Найдено исправленных проблем: {total_fixed}")

                # Cache the result
                self._cache.set("issues/search:fixed", data, cache_params, CacheTTL.ISSUES)
                return True, data
            else:
                error_msg = f"Ошибка HTTP {response.status_code}: {response.text}"
                logger.error(error_msg)
                return False, {"error": error_msg}

        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка сети: {str(e)}"
            logger.error(error_msg)
            return False, {"error": error_msg}

    # Создает новый проект в SonarQube
    def create_sq_project(self, project_key: str, project_name: str, branch: str) -> Tuple[bool, Dict]:
        api_url = f"{self.base_url}/api/projects/create"

        try:
            # Подготавливаем данные формы
            data = {
                'project': project_key,
                'name': project_name,
                'mainBranch': branch,
            }

            logger.info(f"Попытка создать проект: ключ='{project_key}', имя='{project_name}'")

            # Используем self.session, который уже настроен с авторизацией (токеном)
            response = self.session.post(api_url, data=data, timeout=30)

            if response.status_code == 200:
                logger.info(f"Проект '{project_name}' успешно создан в SonarQube")
                return True, response.json()
            else:
                error_msg = f"Ошибка HTTP {response.status_code}: {response.text}"
                logger.error(error_msg)
                return False, {"error": error_msg, "status_code": response.status_code}

        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка сети при создании проекта: {str(e)}"
            logger.error(error_msg)
            return False, {"error": error_msg}
        except ValueError as e:
            error_msg = f"Ошибка разбора JSON-ответа: {str(e)}"
            logger.error(error_msg)
            return False, {"error": error_msg}

# Создаем глобальный экземпляр клиента
sonarqube_client = SonarQubeAPIClient()


class SonarQubeAPIClientToken:
    def __init__(self):
        self.base_url = settings.SONARQUBE_URL
        self.token = settings.SONARQUBE_TOKEN
        self.session = requests.Session()
        if self.token:
            self.session.auth = (self.token, '')
        self._cache = get_cache()

    # Получить список веток проекта
    def get_project_branches(self, project_key: str) -> List[Dict]:
        # Try cache first
        cached = self._cache.get("project_branches/list", {"project": project_key})
        if cached is not None:
            logger.debug(f"Cache hit for project branches: {project_key}")
            return cached

        url = f"{self.base_url}/api/project_branches/list"
        params = {"project": project_key}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json().get("branches", [])

            # Cache the result
            self._cache.set("project_branches/list", result, {"project": project_key}, CacheTTL.PROJECT_INFO)
            return result
        except Exception as e:
            logger.error(f"Ошибка получения веток для {project_key}: {e}")
            return []

    # Получить security hotspots
    def get_project_hotspots(self, project_key: str) -> Dict:
        url = f"{self.base_url}/api/hotspots/search"
        params = {
            "projectKey": project_key,
            "resolution": "FIXED",
            "ps": 50
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения hotspots для {project_key}: {e}")
            return {}

    # Получить детальный статус quality gate
    def get_project_qualitygates_status(self, project_key: str) -> Dict:
        # Try cache first
        cached = self._cache.get("qualitygates/project_status", {"projectKey": project_key})
        if cached is not None:
            logger.debug(f"Cache hit for quality gate status: {project_key}")
            return cached

        url = f"{self.base_url}/api/qualitygates/project_status"
        params = {"projectKey": project_key}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            # Cache the result
            self._cache.set("qualitygates/project_status", result, {"projectKey": project_key}, CacheTTL.QUALITY_GATE)
            return result
        except Exception as e:
            logger.error(f"Ошибка получения статуса quality gate для {project_key}: {e}")
            return {}

    # Получить основную информацию о проекте
    def get_project_info(self, project_key: str) -> Dict:
        url = f"{self.base_url}/api/projects/search"
        params = {"projects": project_key}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            projects = response.json().get("components", [])
            return projects[0] if projects else {}
        except Exception as e:
            logger.error(f"Ошибка получения информации о проекте {project_key}: {e}")
            return {}

    # Получить детали анализа по ID
    def get_analysis_details(self, analysis_id: str) -> Dict:
        url = f"{self.base_url}/api/project_analyses/search"
        params = {"project": analysis_id}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения деталей анализа {analysis_id}: {e}")
            return {}

    # Получить информацию о задаче Compute Engine
    #def get_ce_activity(self, task_id: str) -> Dict:
    #    url = f"{self.base_url}/api/ce/activity"
    #    params = {"componentId": task_id}
    #
    #    try:
    #        response = self.session.get(url, params=params, timeout=10)
    #        response.raise_for_status()
    #        tasks = response.json().get("tasks", [])
    #        for task in tasks:
    #            if task.get("id") == task_id:
    #                return task
    #        return {}
    #    except Exception as e:
    #        logger.error(f"Ошибка получения информации о задаче {task_id}: {e}")
    #        return {}

    # Получает фрагмент кода вокруг указанной строки
    def get_code_snippet(self, component_key: str, line_number: int, context_lines: int = 5) -> Optional[Dict]:
        # Рассчитываем диапазон строк
        from_line = max(1, line_number - context_lines)
        to_line = line_number + context_lines

        logger.info(f"Попытка получить код для {component_key} (строки {from_line}-{to_line})")

        # Формируем URL и заголовки
        api_url = f"{self.base_url}/api/sources/show"
        params = {
            "key": component_key,
            "from": from_line,
            "to": to_line
        }

        logger.info(f"URL запроса: {api_url}")
        logger.info(f"Параметры: {params}")

        # ВРЕМЕННО: используем сессию без авторизации для тестирования
        no_auth_session = requests.Session()  # Новая сессия без auth

        try:
            response = no_auth_session.get(api_url, params=params, timeout=30)

            # Explicitly set UTF-8 encoding to handle Russian characters correctly
            response.encoding = 'utf-8'

            # Логируем статус ответа
            logger.info(f"Статус ответа: {response.status_code}")
            logger.info(f"Заголовки ответа: {dict(response.headers)}")

            # Если ответ не успешный, логируем текст ошибки
            if response.status_code != 200:
                logger.error(f"Ошибка HTTP {response.status_code} при запросе кода")
                logger.error(f"Текст ошибки: {response.text[:500]}")
                return None

            data = response.json()
            logger.info(f"Получен ответ JSON: {json.dumps(data, ensure_ascii=False)[:500]}...")

            # Если ответ содержит данные
            if "sources" in data:
                # Функция для очистки HTML-тегов
                def clean_html_tags(code_line: str) -> str:
                    import re
                    return re.sub(r'<[^>]+>', '', code_line)
                # Очищаем каждую строку кода от тегов
                cleaned_sources = []
                for line_data in data["sources"]:
                    # line_data = [номер_строки, "текст_строки_с_html"]
                    if len(line_data) >= 2:
                        cleaned_line = clean_html_tags(line_data[1])
                        cleaned_sources.append((line_data[0], cleaned_line))

                logger.info(f"Успешно получен код для {component_key} (строки {from_line}-{to_line})")
                logger.info(f"Очищенные строки: {cleaned_sources}")

                return {
                    "from_line": from_line,
                    "to_line": to_line,
                    "sources": cleaned_sources
                }
            else:
                logger.warning(f"Ответ API не содержит ключа 'sources' для {component_key}")
                logger.warning(f"Полный ответ: {json.dumps(data, ensure_ascii=False)}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе кода для {component_key}: {str(e)}", exc_info=True)
            return None
        except ValueError as e:
            logger.error(f"Ошибка при разборе JSON-ответа для {component_key}: {str(e)}")
            logger.error(f"Сырой ответ: {response.text[:1000] if 'response' in locals() else 'Нет ответа'}")
            return None

    # Получает фрагмент кода и возвращает строки в удобном формате.
    def get_code_snippet(self, component_key: str, line_number: int, context_lines: int = 5) -> tuple:
        from_line = max(1, line_number - context_lines)
        to_line = line_number + context_lines

        url = f"{self.base_url}/api/sources/show"
        params = {"key": component_key, "from": from_line, "to": to_line}

        try:
            response = requests.get(url, params=params, timeout=10)
            
            # Explicitly set UTF-8 encoding to handle Russian characters correctly
            response.encoding = 'utf-8'

            if response.status_code == 200:
                data = response.json()

                if "sources" in data:
                    # Обрабатываем и очищаем строки
                    processed_sources = []
                    raw_lines = []  # Строки как есть (с HTML)
                    clean_lines = []  # Очищенные строки

                    for line_data in data["sources"]:
                        if len(line_data) >= 2:
                            line_num = line_data[0]
                            line_text = line_data[1]

                            raw_lines.append((line_num, line_text))

                            # Очищаем от HTML тегов
                            clean_text = re.sub(r'<[^>]+>', '', line_text)
                            clean_lines.append((line_num, clean_text))

                    return True, {
                        "raw_sources": raw_lines,  # [(3, '{'), (4, '<span class="p">#...')]
                        "clean_sources": clean_lines,  # [(3, '{'), (4, '#ifdef WIN32')]
                        "range": (from_line, to_line),
                        "issue_line": line_number,
                        "component": component_key
                    }
                else:
                    return False, {"error": "No sources key in response", "response": data}
            else:
                return False, {"error": f"HTTP {response.status_code}", "text": response.text[:200]}

        except Exception as e:
            return False, {"error": str(e)}

    # Удаляет проект из SonarQube через API
    def delete_project(self, project_key: str) -> bool:
        try:
            url = f"{self.base_url}/api/projects/delete"
            params = {"project": project_key}

            response = self.session.post(url, params=params, timeout=30)

            if response.status_code == 204:
                logger.info(f"Проект {project_key} успешно удален из SonarQube")
                return True
            elif response.status_code == 404:
                logger.warning(f"Проект {project_key} не найден в SonarQube")
                return True
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('errors', [{}])[0].get('msg', 'Unknown error')
                except:
                    error_msg = response.text

                logger.error(f"Ошибка при удалении проекта из SonarQube: {error_msg}")
                return False

        except requests.ConnectionError:
            logger.error("Ошибка соединения с SonarQube")
            raise
        except requests.Timeout:
            logger.error("Таймаут при соединении с SonarQube")
            raise
        except Exception as e:
            logger.error(f"Исключение при удалении проекта из SonarQube: {str(e)}")
            return False

    # Редактирует ключ проекта в SonarQube
    def update_sq_project_key(self, project_key: str, new_project_key: str) -> Tuple[bool, Dict]:
        api_url = f"{self.base_url}/api/projects/update_key"

        try:
            # Подготавливаем данные формы
            data = {
                'from': project_key,
                'to': new_project_key,
            }

            print(f"Попытка обновить ключ проекта: старый ключ='{project_key}', новый ключ='{new_project_key}'")

            # Используем self.session, который уже настроен с авторизацией (токеном)
            response = self.session.post(api_url, data=data, timeout=30)

            if response.status_code >= 200 or response.status_code <= 300:
                print(f"Ключ проекта '{project_key}' успешно обновлён на '{new_project_key}' в SonarQube")
                return True, response.json()
            else:
                error_msg = f"Ошибка HTTP {response.status_code}: {response.text}"
                print(error_msg)
                return False, {"error": error_msg, "status_code": response.status_code}

        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка сети при обновлении ключа проекта: {str(e)}"
            print(error_msg)
            return False, {"error": error_msg}
        except ValueError as e:
            error_msg = f"Ошибка разбора JSON-ответа: {str(e)}"
            print(error_msg)
            return False, {"error": error_msg}

# Создаем глобальный экземпляр клиента
sonarqube_client_token = SonarQubeAPIClientToken()
