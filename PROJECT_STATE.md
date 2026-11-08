# Состояние проекта

## MVP реализован

- FastAPI endpoints `/chat`, `/health`, `/ready`.
- Отдельные OpenAI-compatible chat adapters для ProxyAPI (default) и OpenAI.
- Независимая настройка embedding provider, модели, ключа и endpoint.
- FAQ JSON и TXT ingestion; FAISS cosine similarity retrieval и configurable threshold.
- Источники, сессионная persistent memory в SQLite, статический responsive chat UI.
- Демо-FAQ с вымышленными данными; fake-provider автоматические тесты.

## Проверки и фактические границы

- `python -m pytest -q`: 17 passed.
- `python -m compileall -q app tests` и `node --check frontend\app.js`: passed.
- Live HTTP smoke без credentials: `/` и `/health` вернули 200, `/ready` и `/chat` вернули ожидаемый 503 из-за отсутствующего индекса.
- Внешние chat/embedding подключения не проверены: credentials не предоставлялись.
- Не запускались production deployment, внешний репозиторий или интеграция с личным сайтом.
- Перед живым использованием следует построить индекс со своими данными и настроенными API credentials.
- Автоматические тесты выполняются локально на fake providers и не отправляют запросы в сеть.
