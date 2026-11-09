import io
import logging

import numpy as np
import pytest

from app.config import Settings
from app.ingestion import KnowledgeEntry
from app.rag import NO_ANSWER, RAGService, configure_stage_logging
from app.vector_store import FAISSVectorStore


class FakeEmbeddings:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [
            self.vectors.get(
                text,
                self.vectors["Когда открыта мастерская?"]
                if "Когда открыта мастерская?" in text
                else [0.0, 1.0],
            )
            for text in texts
        ]


class FakeLLM:
    def __init__(self):
        self.calls = []

    def generate(self, system_prompt, messages):
        self.calls.append((system_prompt, messages))
        return "Ответ из базы."


def settings(tmp_path, threshold=0.4):
    return Settings(
        app_env="test",
        llm_provider="proxyapi",
        proxyapi_api_key="",
        proxyapi_base_url="",
        proxyapi_model="test",
        openai_api_key="",
        openai_model="test",
        embedding_provider="proxyapi",
        embedding_api_key="",
        embedding_base_url="",
        embedding_model="test",
        request_timeout=1,
        similarity_threshold=threshold,
        top_k=2,
        max_message_length=4000,
        cors_origins=("http://localhost:8000",),
        data_dir=tmp_path,
        index_path=tmp_path / "index",
        metadata_path=tmp_path / "metadata.json",
        memory_db_path=tmp_path / "memory.sqlite3",
    )


def make_service(tmp_path, threshold=0.4):
    vectors = {
        "Когда открыта мастерская?": [1.0, 0.0],
        "Где проходят занятия?": [0.0, 1.0],
        "В какие часы работаете?": [0.95, 0.05],
        "Совсем другой вопрос": [-1.0, 0.0],
    }
    entries = [
        KnowledgeEntry("Часы работы", "По будням с 10 до 17.", "faq.json"),
        KnowledgeEntry("Формат", "Занятия проходят онлайн.", "guide.txt"),
    ]
    embeddings = FakeEmbeddings(vectors)
    llm = FakeLLM()
    store = FAISSVectorStore.from_embeddings(
        entries, [vectors["Когда открыта мастерская?"], vectors["Где проходят занятия?"]]
    )
    service = RAGService(embeddings, llm, store, settings(tmp_path, threshold))
    return service, embeddings, llm


def test_retrieval_returns_cosine_similarity(tmp_path):
    service, _, _ = make_service(tmp_path)

    results = service.retrieve("Когда открыта мастерская?", [])

    assert results[0]["question"] == "Часы работы"
    assert results[0]["similarity"] > 0.99
    assert results[0]["source"] == "faq.json"


def test_similarity_threshold_blocks_llm_without_relevant_result(tmp_path):
    service, _, llm = make_service(tmp_path, threshold=0.8)

    answer, sources = service.answer("Совсем другой вопрос", [])

    assert answer == NO_ANSWER
    assert sources == []
    assert llm.calls == []


def test_rephrased_question_retrieves_answer(tmp_path):
    service, _, llm = make_service(tmp_path)

    answer, sources = service.answer("В какие часы работаете?", [])

    assert answer == "Ответ из базы."
    assert sources[0]["question"] == "Часы работы"
    assert llm.calls


def test_followup_uses_previous_question_for_retrieval(tmp_path):
    service, embeddings, _ = make_service(tmp_path)

    service.retrieve("а в выходные?", [{"role": "user", "content": "Когда открыта мастерская?"}])

    assert embeddings.calls[-1] == ["Когда открыта мастерская?\nа в выходные?"]


def test_index_persists_and_loads(tmp_path):
    entries = [KnowledgeEntry("Q", "A", "test.json")]
    store = FAISSVectorStore.from_embeddings(entries, np.array([[1.0, 0.0]]))
    index_path = tmp_path / "index.faiss"
    metadata_path = tmp_path / "metadata.json"

    store.save(index_path, metadata_path)
    loaded = FAISSVectorStore.load(index_path, metadata_path)

    assert loaded.search([1.0, 0.0], 1)[0]["answer"] == "A"


def test_answer_logs_success_for_each_rag_stage(tmp_path, caplog):
    service, _, _ = make_service(tmp_path)

    with caplog.at_level("INFO", logger="ego_faq.rag"):
        service.answer("Когда открыта мастерская?", [])

    stage_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ego_faq.rag" and "RAG stage=" in record.getMessage()
    ]
    assert [message.split(" status=", 1)[0] for message in stage_logs] == [
        "RAG stage=embeddings",
        "RAG stage=vector_retrieval",
        "RAG stage=chat_completion",
    ]
    assert all("status=success" in message and "elapsed_ms=" in message for message in stage_logs)


def test_configured_stage_logger_emits_sanitized_records_once(
    tmp_path, monkeypatch
):
    service, _, llm = make_service(tmp_path)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    rag_logger = logging.getLogger("ego_faq.rag")
    uvicorn_logger = logging.getLogger("uvicorn")
    monkeypatch.setattr(rag_logger, "handlers", [])
    monkeypatch.setattr(rag_logger, "propagate", True)
    monkeypatch.setattr(rag_logger, "level", logging.NOTSET)
    monkeypatch.setattr(uvicorn_logger, "handlers", [handler])

    configure_stage_logging()
    service.answer("USER_MESSAGE_SENTINEL", [])

    def fail_with_sensitive_details(system_prompt, messages):
        raise RuntimeError(
            "PROMPT_SENTINEL Authorization: API_KEY_SENTINEL "
            "https://provider.example/private-path"
        )

    monkeypatch.setattr(llm, "generate", fail_with_sensitive_details)
    with pytest.raises(RuntimeError):
        service.answer("USER_MESSAGE_SENTINEL", [])

    records = output.getvalue().splitlines()
    assert len(records) == 6
    expected_successes = {
        "embeddings": 2,
        "vector_retrieval": 2,
        "chat_completion": 1,
    }
    for stage, count in expected_successes.items():
        assert sum(f"RAG stage={stage} status=success" in record for record in records) == count
    assert sum("RAG stage=chat_completion status=failure" in record for record in records) == 1
    assert all("elapsed_ms=" in record for record in records)
    assert all(
        sensitive not in output.getvalue()
        for sensitive in (
            "USER_MESSAGE_SENTINEL",
            "PROMPT_SENTINEL",
            "Authorization",
            "API_KEY_SENTINEL",
            "provider.example",
        )
    )


@pytest.mark.parametrize("failed_stage", ["embeddings", "vector_retrieval", "chat_completion"])
def test_answer_logs_failure_stage_without_sensitive_data(
    tmp_path, caplog, monkeypatch, failed_stage
):
    service, embeddings, _ = make_service(tmp_path)
    if failed_stage == "embeddings":
        target = embeddings
        method = "embed"
    elif failed_stage == "vector_retrieval":
        target = service.store
        method = "search"
    else:
        target = service.llm
        method = "generate"

    sensitive_values = (
        "USER_MESSAGE_SENTINEL",
        "PROMPT_SENTINEL",
        "API_KEY_SENTINEL",
        "Authorization: Bearer HEADER_SENTINEL",
        "https://provider.example/private-path",
    )
    cause = OSError(" ".join(sensitive_values))
    original_error = RuntimeError(" ".join(sensitive_values))
    original_error.__cause__ = cause

    def fail(*args, **kwargs):
        raise original_error

    monkeypatch.setattr(target, method, fail)

    with caplog.at_level("WARNING", logger="ego_faq.rag"):
        with pytest.raises(RuntimeError) as exc_info:
            service.answer("USER_MESSAGE_SENTINEL", [])

    assert exc_info.value is original_error
    stage_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ego_faq.rag" and "RAG stage=" in record.getMessage()
    ]
    assert len(stage_logs) == 1
    assert f"RAG stage={failed_stage} status=failure" in stage_logs[0]
    assert "elapsed_ms=" in stage_logs[0]
    assert "exception=RuntimeError" in stage_logs[0]
    assert "cause=OSError" in stage_logs[0]
    assert all(value not in caplog.text for value in sensitive_values)
