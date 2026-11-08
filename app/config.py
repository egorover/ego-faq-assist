import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_env: str
    llm_provider: str
    proxyapi_api_key: str
    proxyapi_base_url: str
    proxyapi_model: str
    openai_api_key: str
    openai_model: str
    embedding_provider: str
    embedding_api_key: str
    embedding_base_url: str
    embedding_model: str
    request_timeout: float
    similarity_threshold: float
    top_k: int
    max_message_length: int
    cors_origins: tuple[str, ...]
    data_dir: Path
    index_path: Path
    metadata_path: Path
    memory_db_path: Path

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        environment = {
            **{
                key: value
                for key, value in dotenv_values(env_file or PROJECT_ROOT / ".env").items()
                if value is not None
            },
            **os.environ,
        }

        def value(name: str, default: str = "") -> str:
            return str(environment.get(name, default)).strip()

        llm_provider = value("LLM_PROVIDER", "proxyapi").lower()
        embedding_provider = value("EMBEDDING_PROVIDER", "proxyapi").lower()
        if llm_provider not in {"proxyapi", "openai"}:
            raise ValueError("LLM_PROVIDER must be 'proxyapi' or 'openai'.")
        if embedding_provider not in {"proxyapi", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be 'proxyapi' or 'openai'.")

        threshold = float(value("SIMILARITY_THRESHOLD", "0.45"))
        if not 0 <= threshold <= 1:
            raise ValueError("SIMILARITY_THRESHOLD must be between 0 and 1.")
        request_timeout = float(value("REQUEST_TIMEOUT", "30"))
        top_k = int(value("TOP_K", "3"))
        max_message_length = int(value("MAX_MESSAGE_LENGTH", "4000"))
        if request_timeout <= 0:
            raise ValueError("REQUEST_TIMEOUT must be greater than zero.")
        if not 1 <= top_k <= 10:
            raise ValueError("TOP_K must be between 1 and 10.")
        if not 1 <= max_message_length <= 4000:
            raise ValueError("MAX_MESSAGE_LENGTH must be between 1 and 4000.")

        data_dir = Path(value("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
        memory_db_path = Path(
            value("MEMORY_DB_PATH", str(PROJECT_ROOT / "data" / "conversations.sqlite3"))
        ).resolve()

        return cls(
            app_env=value("APP_ENV", "development"),
            llm_provider=llm_provider,
            proxyapi_api_key=value("PROXYAPI_API_KEY"),
            proxyapi_base_url=value("PROXYAPI_BASE_URL"),
            proxyapi_model=value("PROXYAPI_MODEL"),
            openai_api_key=value("OPENAI_API_KEY"),
            openai_model=value("OPENAI_MODEL", "gpt-4o-mini"),
            embedding_provider=embedding_provider,
            embedding_api_key=value("EMBEDDING_API_KEY"),
            embedding_base_url=value("EMBEDDING_BASE_URL"),
            embedding_model=value("EMBEDDING_MODEL", "text-embedding-3-small"),
            request_timeout=request_timeout,
            similarity_threshold=threshold,
            top_k=top_k,
            max_message_length=max_message_length,
            cors_origins=tuple(
                origin.strip()
                for origin in value("CORS_ORIGINS", "http://localhost:8000").split(",")
                if origin.strip()
            ),
            data_dir=data_dir,
            index_path=Path(value("FAISS_INDEX_PATH", str(data_dir / "faiss.index"))).resolve(),
            metadata_path=Path(value("METADATA_PATH", str(data_dir / "metadata.json"))).resolve(),
            memory_db_path=memory_db_path,
        )

    def provider_credentials(self, provider: str) -> tuple[str, str | None]:
        if provider == "proxyapi":
            return self.proxyapi_api_key, self.proxyapi_base_url or None
        return self.openai_api_key, None
