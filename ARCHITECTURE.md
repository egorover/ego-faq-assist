# Архитектура EgoFAQ Assist

## Поток запроса

1. FastAPI валидирует сообщение, session ID и top-k.
2. `ConversationMemory` загружает последние сообщения SQLite-диалога.
3. `RAGService` строит embedding вопроса (для короткого продолжения добавляет прошлый вопрос), выполняет поиск cosine similarity по FAISS и отбрасывает результаты ниже порога.
4. При пустом retrieval возвращается фиксированный ответ о недостатке данных без вызова LLM. Иначе найденные FAQ, история и вопрос передаются провайдеру с инструкцией отвечать только по контексту.
5. Пользовательский и assistant ответы сохраняются в рамках того же session ID; источники возвращаются клиенту.

## Компоненты

- `app/config.py`: окружение, пути, пороги и выбор провайдера.
- `app/providers.py`: единые `LLMProvider` и `EmbeddingProvider` интерфейсы; отдельные `ProxyAPILLMProvider` и `OpenAILLMProvider` используют общий OpenAI-compatible transport. Реальных автоматических fallback нет.
- `app/ingestion.py`: валидация FAQ JSON и загрузка TXT.
- `app/vector_store.py`: нормализация embeddings, FAISS inner-product индекс (cosine similarity) и JSON metadata.
- `app/rag.py`: retrieval threshold, контекст и prompt policy.
- `app/memory.py`: ограниченная SQLite-история.
- `app/api.py`: `/chat`, `/health`, `/ready`, CORS и статический интерфейс.
- `app/build_index.py`: явная переиндексация из `data/`.

Индекс строится offline командой `python -m app.build_index`. Размерность индекса определяется embedding model; при изменении модели его следует построить заново. SQLite хранит текст диалогов на диске и должен обслуживаться как пользовательские данные.

## Исходный проект

Публичный исходный репозиторий [MrGAN12009/pcef9](https://github.com/MrGAN12009/pcef9) использует простой pipeline JSON/TXT → OpenAI embeddings → FAISS → FastAPI и отдельную HTML-страницу. В MVP сохранена общая последовательность обработки, но реализация отделяет провайдеры, ingestion, retrieval и память; вместо OpenAI-only и запуска сервера с обязательным ключом доступны переключаемые adapters и проверка готовности. В исходнике также не было порога similarity, persistent session memory и ограниченного CORS.
