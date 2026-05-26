from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .chroma_store import ChromaStore
from .graph import WorldGraph
from .llm import LLMClient, LLMError


@dataclass(frozen=True)
class MemoryHit:
    id: str
    owner_id: str
    memory_text: str
    truth_scope: str
    scope_key: str
    layer: str
    memory_kind: str
    salience: float
    valence: float
    confidence: float
    source_event_id: str | None


class MemoryGraph:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def recall_memory(self, world_id: str, owner_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        memories = WorldGraph(self.conn).memories(world_id, owner_id)
        scored: list[tuple[float, dict[str, Any]]] = []
        for memory in memories:
            if memory["truth_scope"] not in {"npc", "rumor", "faction"}:
                continue
            score = float(memory["salience"]) + _keyword_score(query, memory["memory_text"])
            scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            MemoryHit(
                id=memory["id"],
                owner_id=memory["owner_id"],
                memory_text=memory["memory_text"],
                truth_scope=memory["truth_scope"],
                scope_key=memory.get("scope_key") or memory["truth_scope"],
                layer=memory.get("layer", "episodic"),
                memory_kind=memory.get("memory_kind", "generic"),
                salience=memory["salience"],
                valence=memory["valence"],
                confidence=memory["confidence"],
                source_event_id=memory["source_event_id"],
            )
            for _, memory in scored[:limit]
        ]


class MemoryAwareDialogue:
    def __init__(self, conn: sqlite3.Connection, llm_client: LLMClient | None = None, chroma_store: ChromaStore | None = None) -> None:
        self.conn = conn
        self.memory = MemoryGraph(conn)
        self.llm_client = llm_client
        self.chroma_store = chroma_store

    def answer(self, world_id: str, npc_id: str, question: str) -> dict[str, Any]:
        recalled = self._recall(world_id, npc_id, question)
        memory_payload = [
            {
                "id": item.id,
                "memory_text": item.memory_text,
                "truth_scope": item.truth_scope,
                "scope_key": item.scope_key,
                "layer": item.layer,
                "memory_kind": item.memory_kind,
                "salience": item.salience,
                "confidence": item.confidence,
                "source_event_id": item.source_event_id,
            }
            for item in recalled
        ]
        if not recalled or self.llm_client is None:
            answer_text = self._fallback_answer(question, recalled)
        else:
            answer_text = self._llm_answer(npc_id, question, memory_payload, self._fallback_answer(question, recalled))
        return {
            "npc_id": npc_id,
            "question": question,
            "answer": answer_text,
            "memories": memory_payload,
        }

    def _recall(self, world_id: str, npc_id: str, question: str) -> list[MemoryHit]:
        if self.chroma_store is not None:
            chroma_hits = self.chroma_store.search_memories(world_id, npc_id, question, 5)
            scoped_hits = [
                hit
                for hit in chroma_hits
                if hit["metadata"].get("owner_id") == npc_id and _is_dialogue_scope(hit["metadata"], npc_id)
            ]
            if scoped_hits:
                return [
                    MemoryHit(
                        id=hit["id"],
                        owner_id=npc_id,
                        memory_text=hit["text"],
                        truth_scope=hit["metadata"].get("scope", "npc"),
                        scope_key=hit["metadata"].get("scope_key") or hit["metadata"].get("scope", "npc"),
                        layer=hit["metadata"].get("layer", "episodic"),
                        memory_kind=hit["metadata"].get("memory_kind", "generic"),
                        salience=float(hit["metadata"].get("salience", 0.5)),
                        valence=float(hit["metadata"].get("valence", 0)),
                        confidence=float(hit["metadata"].get("confidence", 1.0)),
                        source_event_id=hit["metadata"].get("source_event_id"),
                    )
                    for hit in scoped_hits
                ]
        return self.memory.recall_memory(world_id, npc_id, question)

    def _llm_answer(self, npc_id: str, question: str, memories: list[dict[str, Any]], fallback: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 NPC 对话器。只能使用给定 memories 作答。"
                    "不要读取或猜测 canonical 世界真相。"
                    "如果 memories 里没有答案，就明确说不知道。"
                    "输出一小段中文对话。"
                ),
            },
            {
                "role": "user",
                "content": f"npc_id={npc_id}\nquestion={question}\nmemories={memories}",
            },
        ]
        try:
            answer = self.llm_client.complete_text(messages, temperature=0.2).strip()
        except LLMError:
            return fallback
        return answer or fallback

    @staticmethod
    def _fallback_answer(question: str, memories: list[MemoryHit]) -> str:
        if not memories:
            return "我不知道这件事。"
        strongest = memories[0]
        if strongest.truth_scope == "rumor":
            return f"我只是听说：{strongest.memory_text}"
        return f"我记得：{strongest.memory_text}"


def _keyword_score(query: str, text: str) -> float:
    if not query:
        return 0
    score = 0.0
    for token in {"钥匙", "通行令", "玩家", "偷", "放行", "钱袋", "守卫", "铁门"}:
        if token in query and token in text:
            score += 1.0
    return score


def _is_dialogue_scope(metadata: dict[str, Any], npc_id: str) -> bool:
    scope = metadata.get("scope")
    scope_key = metadata.get("scope_key") or scope
    return scope in {"npc", "rumor", "faction"} or scope_key in {f"npc_belief:{npc_id}", "semantic_shared"} or str(scope_key).startswith("rumor:")
