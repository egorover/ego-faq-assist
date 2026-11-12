from typing import Protocol

from openai import OpenAI

from app.config import Settings


class LLMProvider(Protocol):
    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, base_url: str | None, model: str, timeout: float):
        if not api_key:
            raise ValueError("The selected LLM provider has no API key configured.")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
        self.model = model

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("The LLM provider returned an empty response.")
        return content.strip()


class ProxyAPILLMProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float):
        super().__init__(api_key, base_url, model, timeout)


class OpenAILLMProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str, timeout: float):
        super().__init__(api_key, None, model, timeout)


class OpenAICompatibleEmbeddings:
    def __init__(self, api_key: str, base_url: str | None, model: str, timeout: float):
        if not api_key:
            raise ValueError("The selected embedding provider has no API key configured.")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


def build_llm_provider(settings: Settings) -> LLMProvider:
    api_key, base_url = settings.provider_credentials(settings.llm_provider)
    model = settings.proxyapi_model if settings.llm_provider == "proxyapi" else settings.openai_model
    if not model:
        model_name = "PROXYAPI_MODEL" if settings.llm_provider == "proxyapi" else "OPENAI_MODEL"
        raise ValueError(f"{model_name} must be configured.")
    if settings.llm_provider == "proxyapi":
        if not base_url:
            raise ValueError("PROXYAPI_BASE_URL must be configured when LLM_PROVIDER=proxyapi.")
        return ProxyAPILLMProvider(api_key, base_url, model, settings.request_timeout)
    return OpenAILLMProvider(api_key, model, settings.request_timeout)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embedding_provider
    default_key, default_base_url = settings.provider_credentials(provider)
    base_url = settings.embedding_base_url or default_base_url
    if provider == "proxyapi" and not base_url:
        raise ValueError(
            "Set EMBEDDING_BASE_URL or PROXYAPI_BASE_URL when EMBEDDING_PROVIDER=proxyapi."
        )
    return OpenAICompatibleEmbeddings(
        settings.embedding_api_key or default_key,
        base_url,
        settings.embedding_model,
        settings.request_timeout,
    )
