import logging

from app.config import Settings
from app.ingestion import load_knowledge
from app.providers import build_embedding_provider
from app.vector_store import FAISSVectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ego_faq.index")


def main() -> None:
    settings = Settings.from_env()
    entries = load_knowledge(settings.data_dir)
    embeddings = build_embedding_provider(settings).embed(
        [entry.embedding_text for entry in entries]
    )
    store = FAISSVectorStore.from_embeddings(entries, embeddings)
    store.save(settings.index_path, settings.metadata_path)
    logger.info("Built FAISS index with %d knowledge entries.", len(entries))


if __name__ == "__main__":
    main()

