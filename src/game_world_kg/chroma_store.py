from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .config import EmbeddingConfig


COLLECTIONS = ["world_sources", "world_memories", "world_events", "world_rules", "world_quests"]


class ChromaStore:
    def __init__(self, path: str | Path, embedding: EmbeddingConfig | None = None) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.embedding = embedding or EmbeddingConfig.from_env()
        self._collections: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in COLLECTIONS}
        self._client = None
        self._native_collections: dict[str, Any] = {}
        self._init_native()

    def _init_native(self) -> None:
        try:
            import chromadb  # type: ignore
        except BaseException:
            return
        try:
            self._client = chromadb.PersistentClient(path=str(self.path))
        except BaseException:
            self._client = None

    @property
    def backend(self) -> str:
        return "chroma" if self._client is not None else "fallback"

    def init_collections(self) -> None:
        if self._client is None:
            return
        for name in COLLECTIONS:
            try:
                self._native_collections[name] = self._client.get_or_create_collection(name)
            except BaseException:
                self._client = None
                self._native_collections.clear()
                return

    def clear(self) -> None:
        for collection in self._collections.values():
            collection.clear()
        if self._client is not None:
            for name in COLLECTIONS:
                try:
                    self._client.delete_collection(name)
                except Exception:
                    pass
            self._native_collections.clear()
            self.init_collections()

    def upsert_source(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._upsert("world_sources", doc_id, text, metadata)

    def upsert_memory(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._upsert("world_memories", doc_id, text, metadata)

    def upsert_event_summary(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._upsert("world_events", doc_id, text, metadata)

    def search_memories(self, world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._search("world_memories", query, limit, {"world_id": world_id, "owner_id": owner_id})

    def search_evidence(self, world_id: str, query: str, scope: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        filters = {"world_id": world_id}
        if scope is not None:
            filters["scope"] = scope
        return self._search("world_sources", query, limit, filters)

    def _upsert(self, collection: str, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._collections[collection][doc_id] = {"id": doc_id, "text": text, "metadata": dict(metadata)}
        native = self._native_collections.get(collection)
        if native is not None:
            try:
                native.upsert(ids=[doc_id], documents=[text], metadatas=[metadata], embeddings=[_mock_embedding(text)])
            except BaseException:
                self._client = None
                self._native_collections.clear()

    def _search(self, collection: str, query: str, limit: int, filters: dict[str, Any]) -> list[dict[str, Any]]:
        native = self._native_collections.get(collection)
        if native is not None:
            try:
                result = native.query(query_embeddings=[_mock_embedding(query)], n_results=limit, where=_chroma_where(filters))
                ids = result.get("ids", [[]])[0]
                docs = result.get("documents", [[]])[0]
                metadatas = result.get("metadatas", [[]])[0]
                return [{"id": doc_id, "text": doc, "metadata": metadata} for doc_id, doc, metadata in zip(ids, docs, metadatas)]
            except BaseException:
                self._client = None
                self._native_collections.clear()
        candidates = [
            item
            for item in self._collections[collection].values()
            if all(item["metadata"].get(key) == value for key, value in filters.items())
        ]
        candidates.sort(key=lambda item: _keyword_score(query, item["text"]), reverse=True)
        return candidates[:limit]


def _mock_embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [byte / 255 for byte in digest[:32]]


def _keyword_score(query: str, text: str) -> float:
    if not query:
        return 0.0
    score = 0.0
    for token in query.split():
        if token and token in text:
            score += 1.0
    for char in query:
        if "\u4e00" <= char <= "\u9fff" and char in text:
            score += 0.1
    return score


def _chroma_where(filters: dict[str, Any]) -> dict[str, Any]:
    if len(filters) <= 1:
        return filters
    return {"$and": [{key: value} for key, value in filters.items()]}
