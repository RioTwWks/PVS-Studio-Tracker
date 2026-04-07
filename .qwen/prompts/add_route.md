Добавь новый endpoint в main.py по спецификации из spec.md.
- Используй Depends(get_session) и Depends(require_auth)
- Верни JSON с валидацией Pydantic
- Добавь логирование через logger
- Не меняй существующие роуты
- В конце укажи: curl-команду для теста и ожидаемый HTTP-статус