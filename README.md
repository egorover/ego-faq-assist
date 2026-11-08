# EgoFAQ Assist

Локальный MVP FAQ-ассистента: FastAPI, embeddings, FAISS, контролируемый RAG, память сессий и самостоятельный веб-чат. В демонстрационной базе используются только вымышленные сведения.

## Быстрый запуск

Требуется Python 3.10+ и доступ к совместимому API для embeddings и генерации ответов.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Заполните `.env` по одному из вариантов ниже, затем постройте индекс и запустите приложение:

```powershell
python -m app.build_index
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

Откройте http://127.0.0.1:8000. `GET /health` проверяет, что сервер запущен; `GET /ready` сообщает, построен ли индекс. Без настроенных API credentials веб-интерфейс и health endpoint доступны, но построение индекса и генерация ответов требуют действующих ключей.

## Настройка LLM

### ProxyAPI (по умолчанию)

```env
LLM_PROVIDER=proxyapi
PROXYAPI_API_KEY=ваш_ключ
PROXYAPI_BASE_URL=https://совместимый-endpoint/v1
PROXYAPI_MODEL=название_chat_модели
```

Укажите API key, base URL и модель из настроек ProxyAPI. Адрес и название модели намеренно не зашиты в код. Фактическая совместимость моделей зависит от вашего endpoint.

### Прямой OpenAI API

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=ваш_ключ
OPENAI_MODEL=gpt-4o-mini
```

Смените `LLM_PROVIDER` и заполните соответствующие credentials; автоматического переключения при сбое нет. Рестарт приложения применит изменение.

### Embeddings

Выбор embeddings независим от chat-модели. Например, можно использовать ProxyAPI для ответов и OpenAI для индексации:

```env
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=ваш_ключ
EMBEDDING_MODEL=text-embedding-3-small
```

Либо задайте отдельные `EMBEDDING_API_KEY` и `EMBEDDING_BASE_URL`, если используется отдельный endpoint. Многие API для генерации текста не предоставляют embeddings — проверьте это в документации своего endpoint. Модель embeddings должна оставаться одинаковой для построения индекса и поисковых запросов. При смене модели или embedding provider перестройте индекс командой `python -m app.build_index`.

Не добавляйте `.env` и реальные ключи в Git. Проверка реального внешнего подключения требует действующих credentials и отдельного тестового запроса.

## База знаний и API

- `data/faqs.json` — массив объектов с обязательными строками `question` и `answer`; опциональное поле `source`.
- `data/*.txt` — дополнительный документ на файл: первая непустая строка считается заголовком, остальные — содержимым.
- Переиндексация выполняется `python -m app.build_index`.
- `POST /chat`: `{"message":"Когда проходят занятия?","session_id":null,"top_k":3}`. В ответе — `answer`, `session_id` и список релевантных `sources` с similarity.
- `GET /health` — liveness; `GET /ready` — readiness индекса.

Порог задается через `SIMILARITY_THRESHOLD` (cosine similarity от 0 до 1), число результатов — `TOP_K` (или `top_k` в запросе). При отсутствии материалов выше порога ассистент не вызывает LLM и предлагает обратиться в поддержку. История сообщений сохраняется в SQLite (`MEMORY_DB_PATH`) и используется только внутри переданной сессии.

CORS по умолчанию разрешает только `http://localhost:8000`; список дополнительных origin задается через `CORS_ORIGINS` через запятую. В production настройте его для точных origin.

## Разработка и тесты

```powershell
python -m pytest -q
```

Тесты используют fake embeddings и LLM, не требуют ключей и не отправляют платные запросы.

## Структура

- `app/api.py` — HTTP endpoints, провода конфигурации и error handling.
- `app/providers.py` — независимые OpenAI-compatible LLM и embedding adapters.
- `app/ingestion.py`, `app/vector_store.py`, `app/rag.py` — ingestion, FAISS, retrieval и ответ.
- `app/memory.py` — персистентная SQLite-память сессий.
- `frontend/` — адаптивный интерфейс, который обслуживается тем же приложением.
- `data/faqs.json` — вымышленный демонстрационный FAQ.

Подробности: [ARCHITECTURE.md](./ARCHITECTURE.md), [AUDIT_REPORT.md](./AUDIT_REPORT.md), [SECURITY_REPORT.md](./SECURITY_REPORT.md), [PROJECT_STATE.md](./PROJECT_STATE.md), [ROADMAP.md](./ROADMAP.md), [CHANGELOG.md](./CHANGELOG.md).
