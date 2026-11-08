from fastapi.testclient import TestClient
from openai import APIConnectionError

from app.api import create_app
from app.config import Settings
from app.ingestion import KnowledgeEntry
from app.rag import RAGService
from app.vector_store import FAISSVectorStore


class FakeEmbeddings:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class FakeLLM:
    def __init__(self):
        self.calls = []

    def generate(self, system_prompt, messages):
        self.calls.append(messages)
        return "В мастерской занятия проходят по будням."


class FailingLLM:
    def generate(self, system_prompt, messages):
        raise APIConnectionError(request=None)


def make_settings(tmp_path):
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
        similarity_threshold=0.4,
        top_k=3,
        max_message_length=40,
        cors_origins=("http://localhost:8000",),
        data_dir=tmp_path,
        index_path=tmp_path / "index",
        metadata_path=tmp_path / "metadata.json",
        memory_db_path=tmp_path / "messages.sqlite3",
    )


def test_chat_health_readiness_and_session_history(tmp_path):
    settings = make_settings(tmp_path)
    llm = FakeLLM()
    store = FAISSVectorStore.from_embeddings(
        [KnowledgeEntry("Часы работы", "По будням.", "faq.json")], [[1.0, 0.0]]
    )
    service = RAGService(FakeEmbeddings(), llm, store, settings)
    application = create_app(settings, service)
    with TestClient(application) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 200
        assert "EgoFAQ Assist" in client.get("/").text
        first = client.post("/chat", json={"message": "Когда открыто?"})
        assert first.status_code == 200
        session_id = first.json()["session_id"]
        second = client.post(
            "/chat", json={"message": "А в выходные?", "session_id": session_id}
        )
        assert second.status_code == 200
        assert second.json()["session_id"] == session_id
        assert "sources" in second.json()
        assert len(llm.calls[1]) == 3


def test_chat_validates_empty_and_long_messages(tmp_path):
    application = create_app(make_settings(tmp_path), rag=None)
    with TestClient(application) as client:
        assert client.post("/chat", json={"message": "  "}).status_code == 422
        assert client.post("/chat", json={"message": "x" * 41}).status_code == 413


def test_chat_reports_missing_index(tmp_path):
    application = create_app(make_settings(tmp_path), rag=None)
    with TestClient(application) as client:
        assert client.get("/ready").status_code == 503
        response = client.post("/chat", json={"message": "Привет"})

    assert response.status_code == 503
    assert "index" in response.json()["detail"].lower()


def test_chat_sanitizes_llm_connection_errors(tmp_path):
    settings = make_settings(tmp_path)
    store = FAISSVectorStore.from_embeddings(
        [KnowledgeEntry("Часы работы", "По будням.", "faq.json")], [[1.0, 0.0]]
    )
    service = RAGService(FakeEmbeddings(), FailingLLM(), store, settings)
    with TestClient(create_app(settings, service)) as client:
        response = client.post("/chat", json={"message": "Когда открыто?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to reach the configured LLM provider."


def test_proxy_and_openai_configuration_selection(tmp_path, monkeypatch):
    from app.config import Settings
    from app.providers import ProxyAPILLMProvider, build_llm_provider, OpenAILLMProvider

    monkeypatch.setenv("LLM_PROVIDER", "proxyapi")
    monkeypatch.setenv("PROXYAPI_API_KEY", "proxy-secret")
    monkeypatch.setenv("PROXYAPI_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("PROXYAPI_MODEL", "proxy-model")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("OPENAI_MODEL", "openai-model")
    proxy = build_llm_provider(Settings.from_env(tmp_path / "missing.env"))
    assert isinstance(proxy, ProxyAPILLMProvider)
    assert proxy.model == "proxy-model"
    assert str(proxy.client.base_url) == "https://proxy.example/v1/"

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    direct = build_llm_provider(Settings.from_env(tmp_path / "missing.env"))
    assert isinstance(direct, OpenAILLMProvider)
    assert direct.model == "openai-model"
    assert str(direct.client.base_url) == "https://api.openai.com/v1/"


def test_provider_can_be_switched_through_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=openai\nOPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    from app.config import Settings
    from app.providers import build_llm_provider

    provider = build_llm_provider(Settings.from_env(env_file))

    assert provider.model == "file-model"
    assert provider.client.api_key == "file-key"
