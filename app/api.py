import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.config import Settings
from app.index_manager import load_active_index
from app.memory import ConversationMemory
from app.providers import build_embedding_provider, build_llm_provider
from app.rag import RAGService, configure_stage_logging
from app.schemas import ChatRequest, ChatResponse, Source

logger = logging.getLogger("ego_faq")


def create_app(settings: Settings | None = None, rag: RAGService | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    configure_stage_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.rag = rag
        application.state.vector_store = rag.store if rag is not None else None
        application.state.index_error = None
        application.state.active_index_version = None
        if application.state.vector_store is None:
            try:
                application.state.vector_store, application.state.active_index_version = (
                    load_active_index(config)
                )
            except (FileNotFoundError, OSError, ValueError) as exc:
                application.state.index_error = type(exc).__name__
                application.state.active_index_version = None
        application.state.memory = ConversationMemory(config.memory_db_path)
        yield

    application = FastAPI(title="EgoFAQ Assist", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def get_rag(request: Request) -> RAGService:
        if request.app.state.rag is None:
            store = request.app.state.vector_store
            if store is None:
                raise HTTPException(
                    status_code=503, detail="Knowledge index is unavailable."
                )
            try:
                request.app.state.rag = RAGService(
                    build_embedding_provider(config),
                    build_llm_provider(config),
                    store,
                    config,
                )
            except ValueError as exc:
                logger.error("RAG configuration is invalid: %s", exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return request.app.state.rag

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    def ready(request: Request) -> dict[str, str]:
        if request.app.state.vector_store is None:
            logger.error(
                "Knowledge index is unavailable at startup: %s",
                request.app.state.index_error or "unknown",
            )
            raise HTTPException(status_code=503, detail="Knowledge index is invalid or missing.")
        return {"status": "ready"}

    @application.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request) -> ChatResponse:
        if len(body.message) > config.max_message_length:
            raise HTTPException(
                status_code=413,
                detail=f"Message exceeds {config.max_message_length} characters.",
            )
        session_id = body.session_id or uuid.uuid4().hex
        memory: ConversationMemory = request.app.state.memory
        history = memory.get_history(session_id)
        service = get_rag(request)
        try:
            answer, retrieved = service.answer(body.message, history, body.top_k)
        except AuthenticationError as exc:
            raise HTTPException(status_code=502, detail="LLM provider authentication failed.") from exc
        except RateLimitError as exc:
            raise HTTPException(status_code=503, detail="LLM provider rate limit reached; retry later.") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise HTTPException(status_code=502, detail="Unable to reach the configured LLM provider.") from exc
        except APIStatusError as exc:
            raise HTTPException(status_code=502, detail="The configured LLM provider returned an error.") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail="Unable to process the assistant request.") from exc

        memory.add_exchange(session_id, body.message, answer)
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            sources=[
                Source(
                    question=str(item["question"]),
                    source=str(item["source"]),
                    similarity=float(item["similarity"]),
                )
                for item in retrieved
            ],
        )

    frontend = Path(__file__).resolve().parent.parent / "frontend"
    application.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return application


app = create_app()
