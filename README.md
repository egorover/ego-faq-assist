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

Заполните `.env` по одному из вариантов ниже, затем проверьте демонстрационный источник, соберите его в новую версию и запустите приложение:

```powershell
python -m app.build_index --validate demo
python -m app.build_index --source demo
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

Либо задайте отдельные `EMBEDDING_API_KEY` и `EMBEDDING_BASE_URL`, если используется отдельный endpoint. Многие API для генерации текста не предоставляют embeddings — проверьте это в документации своего endpoint. Модель embeddings должна оставаться одинаковой для построения индекса и поисковых запросов. Версия индекса содержит provider/model; несовпадение блокирует readiness. После сборки новой версии перезапустите приложение, чтобы оно загрузило выбранную версию.

Не добавляйте `.env` и реальные ключи в Git. Проверка реального внешнего подключения требует действующих credentials и отдельного тестового запроса.

## Источники знаний и версии индекса

Демонстрационные и будущие реальные данные разделены:

- `data/faqs.json` и `data/*.txt` — текущие демонстрационные материалы. Они содержат только вымышленные сведения.
- `knowledge/real/faqs.json` — отдельный каталог для реального FAQ (`REAL_KNOWLEDGE_DIR`). При сборке выбирается ровно один источник через обязательный аргумент `--source demo` или `--source real`; источники не объединяются.
- `examples/knowledge/faqs.example.json` — вымышленный пример поддерживаемого JSON.

Файл FAQ — JSON-массив записей либо объект с массивом `faqs`. Каноническая запись:

```json
{
  "id": "optional-stable-id",
  "question": "Обязательная строка вопроса",
  "answer": "Обязательная строка ответа",
  "source": "Необязательное имя/ссылка на источник"
}
```

`question` ограничен 500 символами, `answer` — 10 000, `source` — 500, `id` — 128. Без `source` используется имя файла; ID принимает ASCII-буквы, цифры и `. _ : -`. Строки приводятся к Unicode NFC и пробелы сводятся к одиночным. Точный дубликат — запись с одинаковыми после нормализации question и answer без учёта регистра; source и id не участвуют в сравнении. Такие дубликаты и повторные ID отвергаются до embeddings. Если `id` отсутствует, он детерминированно генерируется из SHA-256 нормализованных question и answer.

Необязательный `provenance.json` рядом с выбранным `faqs.json` связывает полные provenance-записи с FAQ по ID и source. При наличии sidecar весь набор должен соответствовать FAQ: повторные/лишние ID, пропущенные записи, несовпадающий source, неизвестные поля или неподдерживаемый статус отклоняются до вызова embeddings. Поддерживаемые статусы: `source_verified`, `owner_approved`, `insufficient_information`, `owner_review_required`. `source_verified` означает только наличие сведений в указанном исходном тексте и не подтверждает их фактическую достоверность.

При сборке version directory хранит `index.faiss`, `metadata.json` и, если у выбранного источника есть provenance, `provenance.json`. Одна версия содержит ровно один dataset: все metadata и provenance records имеют общий `dataset_id`, а `faq_id` уникален внутри него; связь проверяется по паре `(dataset_id, faq_id)`. Для provenance `dataset_id` имеет вид `dataset_type:dataset_name`; компоненты допускают только ASCII-буквы, цифры, точку, подчёркивание и дефис, поэтому двоеточие-разделитель однозначен. Metadata и sidecar относятся к той же версии. Provenance не включается в embedding-текст. Runtime проверяет sidecar при загрузке версии и rollback; отсутствие, повреждение или несовпадение sidecar делает такую версию невалидной. Старые версии без provenance продолжают загружаться и не получают выдуманного статуса. Provenance остаётся внутренними данными: текущий `/chat` не возвращает excerpts, заметки или статусы.

Pilot-набор `knowledge/pilot/` не является источником CLI `demo` или `real` и автоматически не индексируется. Для передачи provenance в сборку sidecar должен находиться рядом с FAQ выбранного источника; не перенаправляйте demo/real пути на pilot, если не намерены собирать этот источник.

Реальные знания по умолчанию исключены из Git через `.gitignore`. Если `REAL_KNOWLEDGE_DIR` перенесён, добавьте его новый путь в `.gitignore`. Проверьте конфигурацию исключений и храните пользовательские материалы в соответствии с их правилами конфиденциальности. Чтобы проверить данные без API-запросов:

```powershell
python -m app.build_index --validate real
```

Проверка валидирует весь источник и выдаёт JSON-сводку. Сборка требует действующего embedding provider и создаёт отдельную версию, не меняя активный индекс до завершения генерации и проверок:

```powershell
python -m app.build_index --source real
```

Артефакты хранятся в `data/index_versions/<version-id>/` вместе с metadata; `data/active_index.json` атомарно указывает активную и предыдущую версии. Старые версии сохраняются. При первой миграции, если manifest и marker отсутствуют и в каталоге версий ещё нет опубликованных версий, runtime проверяет legacy `FAISS_INDEX_PATH` и `METADATA_PATH`; корректный legacy индекс можно продолжать использовать или выбрать как цель первого rollback.

Перед первой публикацией manifest builder атомарно создаёт `data/active_index.json.initialized` (путь определяется рядом с manifest), затем атомарно заменяет manifest. Marker фиксирует, что версионная активация началась/была завершена, и переживает перезапуск. Если процесс остановится между этими двумя операциями, или manifest будет удалён после активации, runtime не переключится на legacy: `/ready` завершится ошибкой, пока manifest не будет восстановлен. Отсутствие manifest также считается ошибкой, если найдены опубликованные version directories, даже когда marker отсутствует. Повреждённый manifest никогда не включает fallback. При настройке нестандартного `ACTIVE_INDEX_MANIFEST_PATH` добавьте в `.gitignore` точные пути к самому manifest и к marker с суффиксом `.initialized`.

Legacy metadata не содержит достоверного идентификатора embedding provider/model, поэтому runtime не может проверить совместимость старой embedding-модели. Перед первой миграцией он проверяет, что каждая legacy-запись является объектом с непустыми строковыми `question`, `answer` и `source`; неполная или повреждённая metadata делает legacy непригодным для readiness и rollback. Чтобы посмотреть активную версию, прочитайте `active_version` из manifest; если manifest ещё не создавался, используется проверенный legacy индекс. Откат:

```powershell
python -m app.build_index --rollback
```

Откат атомарно меняет manifest на предыдущую валидную версию; versioned-версия должна соответствовать текущим `EMBEDDING_PROVIDER` и `EMBEDDING_MODEL`. Legacy-цель проверяется по наличию непустого FAISS-индекса и обязательным полям каждой metadata-записи, но её embedding model остаётся неизвестной. После смены embedding model сначала соберите новый индекс; откат на versioned-индекс старой модели станет возможен после возврата соответствующей конфигурации. После сборки или отката перезапустите FastAPI: индекс загружается при старте и hot reload manifest не выполняется. `/health` остаётся liveness-проверкой; `/ready` возвращает ошибку, если marker указывает на завершённую миграцию без manifest, обнаружены version directories без manifest, либо manifest, индекс, metadata или embedding model несовместимы.

Каждая FAQ-запись целиком образует один embedding; автоматического chunking длинных ответов нет. Для длинных документов сначала подготовьте короткие FAQ-записи, не полагаясь на несуществующее разбиение.

Переиндексация демонстрационной базы при необходимости выполняется отдельно: `python -m app.build_index --source demo`.

## API

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
- `data/faqs.json` — вымышленный демонстрационный FAQ; `knowledge/real/` — локальные реальные материалы, исключённые из Git.

Подробности: [ARCHITECTURE.md](./ARCHITECTURE.md), [AUDIT_REPORT.md](./AUDIT_REPORT.md), [SECURITY_REPORT.md](./SECURITY_REPORT.md), [PROJECT_STATE.md](./PROJECT_STATE.md), [ROADMAP.md](./ROADMAP.md), [CHANGELOG.md](./CHANGELOG.md).
