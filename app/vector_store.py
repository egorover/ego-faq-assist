import json
import os
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.ingestion import KnowledgeEntry


def _normalized_vectors(vectors: list[list[float]] | np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise ValueError("Embeddings must be a non-empty 2D array.")
    if not np.isfinite(array).all():
        raise ValueError("Embeddings contain non-finite values.")
    faiss.normalize_L2(array)
    return array


class FAISSVectorStore:
    def __init__(self, index: faiss.Index, metadata: list[dict[str, Any]]):
        if index.ntotal != len(metadata):
            raise ValueError("FAISS index and metadata have different item counts.")
        self.index = index
        self.metadata = metadata

    @classmethod
    def from_embeddings(
        cls, entries: list[KnowledgeEntry], vectors: list[list[float]] | np.ndarray
    ) -> "FAISSVectorStore":
        if len(entries) != len(vectors):
            raise ValueError("Every knowledge entry must have exactly one embedding.")
        normalized = _normalized_vectors(vectors)
        index = faiss.IndexFlatIP(normalized.shape[1])
        index.add(normalized)
        metadata: list[dict[str, Any]] = [
            {"question": item.question, "answer": item.answer, "source": item.source}
            for item in entries
        ]
        return cls(index, metadata)

    @classmethod
    def load(cls, index_path: Path, metadata_path: Path) -> "FAISSVectorStore":
        if not index_path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError("FAISS index or metadata is missing; build the knowledge index first.")
        try:
            index = faiss.read_index(str(index_path))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to load knowledge index: {exc}") from exc
        if isinstance(metadata, dict):
            metadata = metadata.get("records")
        if not isinstance(metadata, list) or not all(isinstance(item, dict) for item in metadata):
            raise ValueError("Knowledge metadata must contain a list of record objects.")
        return cls(index, metadata)

    def save(
        self,
        index_path: Path,
        metadata_path: Path,
        metadata_document: dict[str, object] | None = None,
    ) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        index_temp = index_path.with_suffix(index_path.suffix + ".tmp")
        metadata_temp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        try:
            faiss.write_index(self.index, str(index_temp))
            metadata_temp.write_text(
                json.dumps(
                    metadata_document if metadata_document is not None else self.metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(index_temp, index_path)
            os.replace(metadata_temp, metadata_path)
        finally:
            index_temp.unlink(missing_ok=True)
            metadata_temp.unlink(missing_ok=True)

    def search(self, vector: list[float] | np.ndarray, top_k: int) -> list[dict[str, object]]:
        query = _normalized_vectors([vector])
        if query.shape[1] != self.index.d:
            raise ValueError("Query embedding dimension does not match the saved index.")
        distances, indices = self.index.search(query, min(top_k, self.index.ntotal))
        results = []
        for score, index in zip(distances[0], indices[0]):
            if index < 0:
                continue
            results.append({**self.metadata[int(index)], "similarity": float(score)})
        return results
