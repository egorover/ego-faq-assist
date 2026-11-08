import app.providers as providers
from app.config import Settings


def test_embedding_provider_can_be_independent_of_chat_provider(monkeypatch, tmp_path):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(providers, "OpenAI", FakeClient)
    monkeypatch.setenv("LLM_PROVIDER", "proxyapi")
    monkeypatch.setenv("PROXYAPI_API_KEY", "proxy-key")
    monkeypatch.setenv("PROXYAPI_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("PROXYAPI_MODEL", "proxy-model")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")

    provider = providers.build_embedding_provider(Settings.from_env(tmp_path / "no.env"))

    assert captured["api_key"] == "openai-key"
    assert captured["base_url"] is None
    assert provider.model == "embed-model"
