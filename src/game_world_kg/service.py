from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .affordance import AffordanceEngine
from .chroma_store import ChromaStore
from .config import EmbeddingConfig, StorageConfig
from .db import transaction
from .dialogue_memory import DialogueMemoryPipeline
from .events import EventLog
from .explanation import ExplanationService
from .graph import WorldGraph
from .kuzu_store import KuzuStore
from .llm import ActionParser, LLMClient, Narrator
from .memory import MemoryAwareDialogue, MemoryGraph
from .projector import ChromaProjector, KuzuProjector, StateProjector
from .quest import QuestGenerator, QuestValidator
from .rules import RuleEngine
from .seed import DEMO_WORLD_ID, seed_demo_world
from .tension import TensionScanner


class GameWorldService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        llm_client: LLMClient | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self.conn = conn
        self._lock = RLock()
        self.llm_client = llm_client
        self.storage = storage or StorageConfig.from_env()
        self.storage.ensure_dirs()
        self.kuzu_store = KuzuStore(self.storage.kuzu_path)
        self.chroma_store = ChromaStore(self.storage.chroma_path, EmbeddingConfig.from_env())
        self.action_parser = ActionParser(llm_client)
        self.narrator = Narrator(llm_client)

    def create_world(self) -> dict[str, Any]:
        with self._lock:
            with transaction(self.conn):
                world_id = seed_demo_world(self.conn, DEMO_WORLD_ID)
        return self.get_world(world_id)

    def get_world(self, world_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
            if row is None:
                raise KeyError(world_id)
            return {"id": row["id"], "name": row["name"], "description": row["description"], "created_at": row["created_at"]}

    def state(self, world_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return WorldGraph(self.conn).state(world_id)

    def graph(self, world_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            self._require_world(world_id)
            return WorldGraph(self.conn).graph(world_id)

    def kuzu_graph(self, world_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            graph = self.kuzu_store.query_current_graph(world_id)
            if not graph["nodes"] and not graph["edges"]:
                with transaction(self.conn):
                    KuzuProjector(self.conn, self.kuzu_store).rebuild(world_id)
                graph = self.kuzu_store.query_current_graph(world_id)
            return graph

    def events(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return WorldGraph(self.conn).events(world_id)

    def memories(self, world_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return WorldGraph(self.conn).memories(world_id, owner_id)

    def recall_memory(self, world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return [
                {
                    "id": item.id,
                    "owner_id": item.owner_id,
                    "memory_text": item.memory_text,
                    "truth_scope": item.truth_scope,
                    "scope_key": item.scope_key,
                    "layer": item.layer,
                    "memory_kind": item.memory_kind,
                    "salience": item.salience,
                    "valence": item.valence,
                    "confidence": item.confidence,
                    "source_event_id": item.source_event_id,
                }
                for item in MemoryGraph(self.conn).recall_memory(world_id, owner_id, query, limit)
            ]

    def search_memories(self, world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            hits = self.chroma_store.search_memories(world_id, owner_id, query, limit)
            if not hits:
                with transaction(self.conn):
                    ChromaProjector(self.conn, self.chroma_store).rebuild(world_id)
                hits = self.chroma_store.search_memories(world_id, owner_id, query, limit)
            return hits

    def search_evidence(self, world_id: str, query: str, scope: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            hits = self.chroma_store.search_evidence(world_id, query, scope, limit)
            if not hits:
                with transaction(self.conn):
                    ChromaProjector(self.conn, self.chroma_store).rebuild(world_id)
                hits = self.chroma_store.search_evidence(world_id, query, scope, limit)
            return hits

    def npc_dialogue(self, world_id: str, npc_id: str, question: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            with transaction(self.conn):
                ChromaProjector(self.conn, self.chroma_store).rebuild(world_id)
                answer = MemoryAwareDialogue(self.conn, self.llm_client, self.chroma_store).answer(world_id, npc_id, question)
                log = EventLog(self.conn)
                turn_id = log.create_turn(world_id, f"npc_dialogue:{npc_id}:{question}", answer["answer"])
                turn = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                recalled_memory_ids = [memory["id"] for memory in answer["memories"]]
                dialogue_event = log.append(
                    world_id,
                    turn_id,
                    turn["turn_index"],
                    "NPC_DIALOGUE",
                    "player",
                    {
                        "npc_id": npc_id,
                        "question": question,
                        "answer": answer["answer"],
                        "recalled_memory_ids": recalled_memory_ids,
                    },
                    participants=["player", npc_id],
                    evidence_refs=[
                        {
                            "source_id": turn_id,
                            "source_type": "npc_dialogue",
                            "span": [0, len(question)],
                            "extractor": "dialogue_log_v1",
                            "confidence": 1.0,
                        }
                    ],
                )
                memory_result = DialogueMemoryPipeline(self.conn).process_npc_dialogue(
                    world_id=world_id,
                    turn_id=turn_id,
                    turn_index=turn["turn_index"],
                    dialogue_event=dialogue_event,
                    npc_id=npc_id,
                    question=question,
                    answer=answer["answer"],
                    recalled_memory_ids=recalled_memory_ids,
                )
                created_memories = [
                    memory
                    for memory in WorldGraph(self.conn).memories(world_id, npc_id)
                    if memory["source_event_id"] == dialogue_event.id
                ]
                answer["dialogue_event_id"] = dialogue_event.id
                answer["created_memory_ids"] = [memory["id"] for memory in created_memories]
                answer["segments"] = memory_result["segments"]
                answer["memory_ops"] = memory_result["memory_ops"]
                answer["review_items"] = memory_result["review_items"]
                return answer

    def neighbors(self, world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return WorldGraph(self.conn).query_neighbors(world_id, entity_id, rel_type)

    def kuzu_neighbors(self, world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            neighbors = self.kuzu_store.query_neighbors(world_id, entity_id, rel_type)
            if not neighbors:
                with transaction(self.conn):
                    KuzuProjector(self.conn, self.kuzu_store).rebuild(world_id)
                neighbors = self.kuzu_store.query_neighbors(world_id, entity_id, rel_type)
            return neighbors

    def affordances(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return AffordanceEngine(self.conn).list_for_player(world_id)

    def quests(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return QuestGenerator(self).generate(world_id)

    def tensions(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return TensionScanner(self).scan(world_id)

    def validate_quest(self, world_id: str, quest: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return QuestValidator(self).validate(quest, world_id)

    def turn(self, world_id: str, player_input: str) -> dict[str, Any]:
        self._require_world(world_id)
        with self._lock:
            with transaction(self.conn):
                log = EventLog(self.conn)
                turn_id = log.create_turn(world_id, player_input)
                turn = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                state_before = WorldGraph(self.conn).state(world_id)
                affordances_before = AffordanceEngine(self.conn).list_for_player(world_id)
                candidate = self.action_parser.parse(player_input, state_before, affordances_before)
                result = RuleEngine(self.conn).resolve_turn(
                    world_id,
                    turn_id,
                    turn["turn_index"],
                    player_input,
                    action_id=candidate.action_id if candidate else None,
                    target_id=candidate.target_id if candidate else None,
                    extractor="llm_action_parser_v1" if candidate else "rule_parser_v1",
                    confidence=candidate.confidence if candidate else 0.9,
                )
                event_payloads = [
                    {
                        "id": event.id,
                        "event_type": event.event_type,
                        "actor_id": event.actor_id,
                        "participants": event.participants,
                        "payload": event.payload,
                    }
                    for event in result.events
                ]
                affordances = AffordanceEngine(self.conn).list_for_player(world_id)
                narration = self.narrator.narrate(player_input, result, event_payloads, WorldGraph(self.conn).state(world_id), affordances)
                self.conn.execute("UPDATE turns SET narration = ? WHERE id = ?", (narration, turn_id))
        return {
            "turn_id": turn_id,
            "turn_index": turn["turn_index"],
            "accepted": result.accepted,
            "action_id": result.action_id,
            "reason": result.reason,
            "narration": narration,
            "events": event_payloads,
            "affordances": affordances,
        }

    def replay(self, world_id: str, to_turn: int | None = None) -> dict[str, Any]:
        self._require_world(world_id)
        with self._lock:
            with transaction(self.conn):
                StateProjector(self.conn).replay_to_turn(world_id, to_turn)
            return {
                "world_id": world_id,
                "to_turn": to_turn,
                "state": WorldGraph(self.conn).state(world_id),
                "graph": WorldGraph(self.conn).graph(world_id),
                "memories": WorldGraph(self.conn).memories(world_id),
            }

    def run_projectors(self, world_id: str) -> dict[str, Any]:
        self._require_world(world_id)
        with self._lock:
            with transaction(self.conn):
                kuzu = KuzuProjector(self.conn, self.kuzu_store).run_pending(world_id)
                chroma = ChromaProjector(self.conn, self.chroma_store).run_pending(world_id)
            return {
                "world_id": world_id,
                "projectors": [kuzu, chroma],
                "projection_status": self.projection_status(world_id),
            }

    def rebuild_projectors(self, world_id: str) -> dict[str, Any]:
        self._require_world(world_id)
        with self._lock:
            with transaction(self.conn):
                kuzu = KuzuProjector(self.conn, self.kuzu_store).rebuild(world_id)
                chroma = ChromaProjector(self.conn, self.chroma_store).rebuild(world_id)
            return {
                "world_id": world_id,
                "projectors": [kuzu, chroma],
                "projection_status": self.projection_status(world_id),
            }

    def projection_status(self, world_id: str) -> list[dict[str, Any]]:
        return [
            {
                "projector": row["projector"],
                "projected_turn": row["projected_turn"],
                "updated_at": row["updated_at"],
            }
            for row in self.conn.execute(
                "SELECT * FROM projection_status WHERE world_id = ? ORDER BY projector",
                (world_id,),
            ).fetchall()
        ]

    def memory_ops(self, world_id: str, source_event_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return DialogueMemoryPipeline(self.conn).memory_ops(world_id, source_event_id)

    def review_queue(self, world_id: str, status: str = "open") -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return DialogueMemoryPipeline(self.conn).review_items(world_id, status)

    def memory_query(self, world_id: str, npc_id: str, query: str, mode: str = "roleplay", limit: int = 5) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            hits = MemoryAwareDialogue(self.conn, self.llm_client, self.chroma_store)._recall(world_id, npc_id, query)[:limit]
            payload = [
                {
                    "id": item.id,
                    "owner_id": item.owner_id,
                    "memory_text": item.memory_text,
                    "truth_scope": item.truth_scope,
                    "scope_key": item.scope_key,
                    "layer": item.layer,
                    "memory_kind": item.memory_kind,
                    "salience": item.salience,
                    "confidence": item.confidence,
                    "source_event_id": item.source_event_id,
                }
                for item in hits
            ]
            if mode == "dev":
                return {"world_id": world_id, "npc_id": npc_id, "query": query, "mode": mode, "memories": payload}
            return {"npc_id": npc_id, "query": query, "memories": payload}

    def explain_state(self, world_id: str, entity_id: str, attr: str, scope: str = "canonical") -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return ExplanationService(self.conn).explain_state(world_id, entity_id, attr, scope)

    def explain_event(self, world_id: str, event_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return ExplanationService(self.conn).explain_event(world_id, event_id)

    def explain_memory(self, world_id: str, memory_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return ExplanationService(self.conn).explain_memory(world_id, memory_id)

    def explain_quest(self, world_id: str, quest_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            quest = next((item for item in QuestGenerator(self).generate(world_id) if item["quest_id"] == quest_id), None)
            if quest is None:
                raise KeyError(quest_id)
            return ExplanationService(self.conn).explain_quest(world_id, quest)

    def _require_world(self, world_id: str) -> None:
        if self.conn.execute("SELECT 1 FROM worlds WHERE id = ?", (world_id,)).fetchone() is None:
            raise KeyError(world_id)


def _dialogue_memory_text(question: str, supporting_memory_ids: list[str], limit: int = 240) -> str:
    text = f"玩家曾向我询问：{question}"
    if supporting_memory_ids:
        text += "；我当时依据已有记忆作答。"
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
