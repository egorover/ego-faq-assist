import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.config import Settings
from app.memory import ConversationMemory
from app.providers import build_embedding_provider, build_llm_provider
from app.rag import RAGService
from app.schemas import ChatRequest, ChatResponse, Source
from app.vector_store import FAISSVectorStore

logger = logging.getLogger("ego_faq")


def create_app(settings: Settings | None = None, rag: RAGService | None = None) -> FastAPI:
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.rag = rag
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
            try:
                store = FAISSVectorStore.load(config.index_path, config.metadata_path)
                request.app.state.rag = RAGService(
                    build_embedding_provider(config),
                    build_llm_provider(config),
                    store,
                    config,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ValueError as exc:
                logger.error("RAG configuration is invalid: %s", exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return request.app.state.rag

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    def ready(request: Request) -> dict[str, str]:
        if request.app.state.rag is None:
            try:
                FAISSVectorStore.load(config.index_path, config.metadata_path)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ValueError as exc:
                logger.error("Knowledge index is invalid: %s", exc)
                raise HTTPException(status_code=503, detail="Knowledge index is invalid.") from exc
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
            logger.warning("LLM provider rejected credentials.")
            raise HTTPException(status_code=502, detail="LLM provider authentication failed.") from exc
        except RateLimitError as exc:
            logger.warning("LLM provider rate limit reached.")
            raise HTTPException(status_code=503, detail="LLM provider rate limit reached; retry later.") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            logger.warning("LLM provider request failed: %s", type(exc).__name__)
            raise HTTPException(status_code=502, detail="Unable to reach the configured LLM provider.") from exc
        except APIStatusError as exc:
            logger.warning("LLM provider returned HTTP %s.", exc.status_code)
            raise HTTPException(status_code=502, detail="The configured LLM provider returned an error.") from exc
        except (ValueError, RuntimeError) as exc:
            logger.error("RAG request failed: %s", exc)
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
