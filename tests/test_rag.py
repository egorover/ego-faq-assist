import numpy as np

from app.config import Settings
from app.ingestion import KnowledgeEntry
from app.rag import NO_ANSWER, RAGService
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
