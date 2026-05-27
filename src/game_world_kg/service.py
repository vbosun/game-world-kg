from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .affordance import AffordanceEngine
from .bootstrap import WorldBootstrapper, WorldSpecRepository
from .chroma_store import ChromaStore
from .config import EmbeddingConfig, StorageConfig
from .db import transaction, utc_now
from .drama import DramaManager
from .dialogue_memory import DialogueMemoryPipeline
from .events import EventLog
from .explanation import ExplanationService
from .graph import WorldGraph
from .kuzu_store import KuzuStore
from .llm import ActionParser, LLMClient, Narrator
from .memory import MemoryAwareDialogue, MemoryGraph
from .npc_planner import NPCPlanner
from .playable_turn import PlayableTurnKernel
from .projector import ChromaProjector, KuzuProjector, StateProjector
from .quest import QuestGenerator, QuestValidator
from .rules import RuleEngine
from .seed import DEMO_WORLD_ID, seed_demo_world
from .tension import TensionScanner
from .worldspec import WorldSpec, WorldSpecGenerator, WorldSpecRepairer, WorldSpecValidator


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
            return {"id": row["id"], "name": row["name"], "description": row["description"], "runtime_mode": row["runtime_mode"], "created_at": row["created_at"]}

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

    def play_state(self, world_id: str, mode: str = "roleplay") -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).play_state(world_id, mode)

    def play_scene(self, world_id: str, mode: str = "roleplay") -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).play_state(world_id, mode)["scene"]

    def play_affordances(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).play_affordances(world_id)

    def play_turn(self, world_id: str, player_input: str, selected_action_id: str | None = None, selected_target_id: str | None = None, mode: str = "roleplay") -> dict[str, Any]:
        return PlayableTurnKernel(self).play_turn(world_id, player_input, selected_action_id=selected_action_id, selected_target_id=selected_target_id, mode=mode)

    def play_quests(self, world_id: str, mode: str = "roleplay") -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).quest_journal(world_id, mode)

    def play_tensions(self, world_id: str, mode: str = "roleplay") -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).tension_journal(world_id, mode)

    def play_timeline(self, world_id: str, limit: int = 20, mode: str = "roleplay") -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return PlayableTurnKernel(self).timeline(world_id, limit, mode)

    def play_npc_tick(self, world_id: str, limit: int = 3) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return self.tick_world(world_id, limit)

    def play_npc_activity(self, world_id: str, limit: int = 20, mode: str = "roleplay") -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            events = [event for event in self.events(world_id)[-limit:] if event["event_type"] == "NPC_ACTION"]
            if mode == "dev":
                return events
            return [
                {
                    "turn_index": event["turn_index"],
                    "npc_id": event["actor_id"],
                    "action_id": event.get("payload", {}).get("action_id"),
                    "target_id": event.get("payload", {}).get("target_id"),
                    "summary": f"{event['actor_id']} took a foreground action.",
                }
                for event in events
            ]

    def play_explain_state(self, world_id: str, entity_id: str, attr: str, scope: str = "canonical", mode: str = "roleplay") -> dict[str, Any]:
        explanation = self.explain_state(world_id, entity_id, attr, scope)
        if mode == "dev":
            return explanation
        return _public_explanation(explanation)

    def play_explain_quest(self, world_id: str, quest_id: str, mode: str = "roleplay") -> dict[str, Any]:
        explanation = self.explain_quest(world_id, quest_id)
        if mode == "dev":
            return explanation
        return _public_explanation(explanation)

    def quests(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return QuestGenerator(self).generate(world_id)

    def tensions(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_world(world_id)
            return TensionScanner(self).scan(world_id)

    def turn_bound(
        self,
        world_id: str,
        player_input: str,
        action_id: str,
        target_id: str | None = None,
        extractor: str = "play_input_binder",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        self._require_world(world_id)
        with self._lock:
            with transaction(self.conn):
                log = EventLog(self.conn)
                turn_id = log.create_turn(world_id, player_input)
                turn = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                result = RuleEngine(self.conn).resolve_turn(
                    world_id,
                    turn_id,
                    turn["turn_index"],
                    player_input,
                    action_id=action_id,
                    target_id=target_id,
                    extractor=extractor,
                    confidence=confidence,
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
            "extractor": extractor,
        }

    def generate_worldspec(self, idea: str, repair_attempts: int = 2) -> dict[str, Any]:
        with self._lock:
            generator = WorldSpecGenerator(self.llm_client)
            spec = generator.generate(idea)
            validator = WorldSpecValidator()
            report = validator.validate(spec)
            attempts: list[dict[str, Any]] = [report]
            candidate_payload = spec.model_dump(mode="json")
            adopted_spec = spec.model_dump(mode="json")
            repairer = WorldSpecRepairer()
            for _ in range(max(0, repair_attempts)):
                if report["valid"]:
                    break
                candidate_payload = repairer.repair(candidate_payload, report)
                spec = WorldSpec.model_validate(candidate_payload)
                report = validator.validate(spec)
                attempts.append(report)
            adopted_spec = spec.model_dump(mode="json")
            created_at = utc_now()
            trace_id = f"trace_worldspec_{hashlib.sha256((idea + created_at).encode('utf-8')).hexdigest()[:16]}"
            raw_llm_response = generator.last_raw_response
            if raw_llm_response is None and generator.last_candidate_payload is not None:
                raw_llm_response = json.dumps(generator.last_candidate_payload, ensure_ascii=False, sort_keys=True)
            trace_payload = {
                "trace_id": trace_id,
                "created_at": created_at,
                "requested_idea": idea,
                "requested_genre": getattr(generator, "requested_genre", None),
                "source": generator.last_source,
                "raw_llm_response": raw_llm_response,
                "parsed_candidate": generator.last_candidate_payload,
                "normalized_candidate": getattr(generator, "last_normalized_candidate", None),
                "validation_report": getattr(generator, "last_validation_report", None) or report,
                "repair_attempts": getattr(generator, "last_repair_attempts", None) or attempts,
                "adopted_spec": adopted_spec,
                "adopted_spec_genre": adopted_spec.get("genre"),
                "fallback_reason": generator.last_error if generator.last_source == "sample_fallback" else None,
                "warnings": getattr(generator, "last_warnings", []),
                "adopted_validation_report": report,
            }
            with transaction(self.conn):
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO source_texts(id, world_id, source_type, text, turn_id, created_at)
                    VALUES (?, ?, 'world_idea', ?, NULL, ?)
                    """,
                    (f"src_worldidea_{spec.spec_hash()[:16]}", spec.world_id, idea, utc_now()),
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO source_texts(id, world_id, source_type, text, turn_id, created_at)
                    VALUES (?, ?, 'worldspec_candidate', ?, NULL, ?)
                    """,
                    (
                        f"src_worldspec_{spec.spec_hash()[:16]}",
                        spec.world_id,
                        json.dumps(
                            {
                                "source": generator.last_source,
                                "llm_candidate": generator.last_candidate_payload,
                                "generation_error": generator.last_error,
                                "adopted_spec": adopted_spec,
                                "candidate": generator.last_candidate_payload or adopted_spec,
                                "validation_report": report,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        utc_now(),
                    ),
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO source_texts(id, world_id, source_type, text, turn_id, created_at)
                    VALUES (?, ?, 'worldspec_generation_trace', ?, NULL, ?)
                    """,
                    (
                        trace_id,
                        spec.world_id,
                        json.dumps(trace_payload, ensure_ascii=False, sort_keys=True),
                        created_at,
                    ),
                )
                status = "validated" if report["valid"] else "rejected"
                spec_id = WorldSpecRepository(self.conn).save(spec, status, report)
            return {
                "world_spec_id": spec_id,
                "world_id": spec.world_id,
                "trace_id": trace_id,
                "source": generator.last_source,
                "spec": spec.model_dump(mode="json"),
                "llm_candidate": generator.last_candidate_payload,
                "normalized_candidate": getattr(generator, "last_normalized_candidate", None),
                "generation_error": generator.last_error,
                "validation_report": report,
                "repair_attempts": attempts,
            }

    def latest_worldspec_generation_trace(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT id, text FROM source_texts
            WHERE source_type = 'worldspec_generation_trace'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise KeyError("worldspec_generation_trace")
        payload = json.loads(row["text"])
        payload.setdefault("trace_id", row["id"])
        return payload

    def worldspec_generation_trace(self, trace_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT text FROM source_texts WHERE id = ? AND source_type = 'worldspec_generation_trace'",
            (trace_id,),
        ).fetchone()
        if row is None:
            raise KeyError(trace_id)
        payload = json.loads(row["text"])
        payload.setdefault("trace_id", trace_id)
        return payload

    def validate_worldspec(self, payload: dict[str, Any]) -> dict[str, Any]:
        return WorldSpecValidator().validate(payload)

    def repair_worldspec(self, payload: dict[str, Any]) -> dict[str, Any]:
        report = WorldSpecValidator().validate(payload)
        repaired = WorldSpecRepairer().repair(payload, report)
        repaired_report = WorldSpecValidator().validate(repaired)
        return {"spec": repaired, "validation_report": repaired_report, "previous_report": report}

    def bootstrap_worldspec(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = WorldSpec.model_validate(payload)
        report = WorldSpecValidator().validate(spec)
        if not report["valid"]:
            return {"accepted": False, "validation_report": report}
        with self._lock:
            with transaction(self.conn):
                repo = WorldSpecRepository(self.conn)
                spec_id = repo.save(spec, "validated", report)
                result = WorldBootstrapper(self.conn).bootstrap(spec, spec_id)
            return {"accepted": True, **result.as_dict()}

    def worldspec(self, world_id: str) -> dict[str, Any]:
        with self._lock:
            row = WorldSpecRepository(self.conn).latest(world_id)
            if row is None:
                raise KeyError(world_id)
            return row

    def tick_world(self, world_id: str, limit: int = 3) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return NPCPlanner(self.conn, self).tick_world(world_id, limit)

    def tick_npc(self, world_id: str, npc_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return NPCPlanner(self.conn, self).tick_npc(world_id, npc_id)

    def planner_context(self, world_id: str, npc_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return NPCPlanner(self.conn, self).context(world_id, npc_id).as_dict()

    def drama_foreground(self, world_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            return DramaManager(self).foreground(world_id)

    def worldgen_evaluation(self, world_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_world(world_id)
            spec = self.worldspec(world_id)
            validation = spec["validation_report"]
            quests = self.quests(world_id)
            quest_traceability = [bool(quest.get("tension_id") and quest.get("evidence")) for quest in quests]
            before_replay_hash = _world_state_hash(self.conn, world_id)
            replay = self.replay(world_id)
            after_replay_hash = _world_state_hash(self.conn, world_id)
            rebuild = self.rebuild_projectors(world_id)
            kuzu_graph = self.kuzu_graph(world_id)
            sqlite_graph = self.graph(world_id)
            active_sqlite_edges = [edge for edge in sqlite_graph["edges"] if edge["valid_to_turn"] is None]
            sqlite_node_ids = {node["id"] for node in sqlite_graph["nodes"]}
            kuzu_node_ids = {node["id"] for node in kuzu_graph["nodes"]}
            kuzu_consistency_checks = [
                len(kuzu_graph["nodes"]) == len(sqlite_graph["nodes"]),
                len(kuzu_graph["edges"]) == len(active_sqlite_edges),
                sqlite_node_ids.issubset(kuzu_node_ids),
            ]
            invalid_action_rate = _measure_invalid_action_rejection_rate(self.conn, world_id)
            chroma_scope_accuracy, chroma_scope_details = _measure_chroma_scope_accuracy(self, world_id)
            turns_playable = _measure_turns_playable(self, world_id, 30)
            canonical_contamination_rate = _measure_canonical_contamination_rate(self.conn, world_id)
            return {
                "world_id": world_id,
                "mode": "dev_destructive_evaluation",
                "warning": "worldgen_evaluation replays state and rebuilds projectors; use play APIs for player-facing checks.",
                "worldspec_valid_rate": 1.0 if validation.get("valid") else 0.0,
                "repair_success_rate": 1.0 if validation.get("valid") else 0.0,
                "bootstrap_replay_equivalence": 1.0 if before_replay_hash == after_replay_hash and bool(replay["state"]) else 0.0,
                "kuzu_rebuild_consistency": sum(1 for item in kuzu_consistency_checks if item) / len(kuzu_consistency_checks),
                "chroma_scoped_retrieval_accuracy": chroma_scope_accuracy,
                "turns_playable": turns_playable,
                "invalid_action_rate": 1.0 - invalid_action_rate,
                "npc_privileged_knowledge_rate": 1.0 - chroma_scope_accuracy,
                "quest_traceability_rate": sum(1 for item in quest_traceability if item) / len(quest_traceability) if quest_traceability else 0.0,
                "canonical_contamination_rate": canonical_contamination_rate,
                "affordance_count": len(self.affordances(world_id)),
                "details": {
                    "state_hash_before_replay": before_replay_hash,
                    "state_hash_after_replay": after_replay_hash,
                    "kuzu_projectors": rebuild["projectors"],
                    "chroma_scope": chroma_scope_details,
                },
            }

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
                runtime_mode = _runtime_mode(self.conn, world_id)
                candidate = self.action_parser.parse(player_input, state_before, affordances_before, require_current_affordance=runtime_mode == "template_only")
                if candidate is None and runtime_mode == "template_only":
                    candidate = _match_current_affordance(player_input, affordances_before)
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


def _world_state_hash(conn: sqlite3.Connection, world_id: str) -> str:
    graph = WorldGraph(conn).graph(world_id)
    normalized_graph = {
        "nodes": [
            {key: value for key, value in node.items() if key not in {"source_event_id"}}
            for node in graph["nodes"]
        ],
        "edges": [
            {key: value for key, value in edge.items() if key not in {"id", "source_event_id"}}
            for edge in graph["edges"]
        ],
    }
    memories = sorted(
        [
        {key: value for key, value in memory.items() if key not in {"id", "source_event_id", "last_recalled_turn"}}
        for memory in WorldGraph(conn).memories(world_id)
        ],
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    )
    payload = {
        "state": WorldGraph(conn).state(world_id),
        "graph": normalized_graph,
        "memories": memories,
        "action_templates": [
            {
                "action_id": row["action_id"],
                "target_id": row["target_id"],
                "target_selector": json.loads(row["target_selector_json"]),
                "arg_schema": json.loads(row["arg_schema_json"]),
                "preconditions": json.loads(row["preconditions_json"]),
                "effects": json.loads(row["effects_json"]),
                "enabled": row["enabled"],
            }
            for row in conn.execute(
                "SELECT * FROM action_templates WHERE world_id = ? ORDER BY action_id",
                (world_id,),
            ).fetchall()
        ],
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _measure_invalid_action_rejection_rate(conn: sqlite3.Connection, world_id: str) -> float:
    log = EventLog(conn)
    checks: list[bool] = []
    invalid_cases = [
        ("invalid_missing_template", "nonexistent_worldspec_action", None),
        ("invalid_same_location", "talk_to", "herb_master"),
        ("invalid_resource_or_location", "trade", "herb_master"),
    ]
    with transaction(conn):
        for label, action_id, target_id in invalid_cases:
            turn_id = log.create_turn(world_id, f"evaluation:{label}")
            turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            result = RuleEngine(conn).resolve_turn(
                world_id,
                turn_id,
                turn["turn_index"],
                label,
                action_id=action_id,
                target_id=target_id,
                extractor="worldgen_evaluation",
                confidence=1.0,
            )
            checks.append(not result.accepted)
    return sum(1 for item in checks if item) / len(checks) if checks else 0.0


def _measure_chroma_scope_accuracy(service: GameWorldService, world_id: str) -> tuple[float, dict[str, Any]]:
    graph = service.graph(world_id)
    characters = [node["id"] for node in graph["nodes"] if node["entity_type"] == "Character" and node["id"] != "player"]
    if len(characters) < 2:
        return 0.0, {"reason": "not_enough_npcs"}
    owner_a, owner_b = characters[:2]
    nonce_a = f"scope_probe_alpha_{world_id}"
    nonce_b = f"scope_probe_beta_{world_id}"
    log = EventLog(service.conn)
    projector = StateProjector(service.conn)
    with transaction(service.conn):
        turn_id = log.create_turn(world_id, "evaluation:chroma_scope_probe")
        turn = service.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        for owner_id, text in [(owner_a, nonce_a), (owner_b, nonce_b)]:
            event = log.append(
                world_id,
                turn_id,
                turn["turn_index"],
                "ADD_MEMORY",
                "system",
                {"owner_id": owner_id, "memory_text": text, "truth_scope": "npc", "scope_key": owner_id, "salience": 0.5, "confidence": 1.0},
                participants=[owner_id],
                evidence_refs=[{"source_id": turn_id, "source_type": "worldgen_evaluation", "extractor": "scope_probe", "confidence": 1.0}],
            )
            projector.apply_event(event)
    service.rebuild_projectors(world_id)
    hits_a_for_a = service.search_memories(world_id, owner_a, nonce_a, 5)
    hits_a_for_b = service.search_memories(world_id, owner_a, nonce_b, 5)
    own_hit = any(nonce_a in hit["text"] for hit in hits_a_for_a)
    leak_blocked = not any(nonce_b in hit["text"] or hit["metadata"].get("owner_id") == owner_b for hit in hits_a_for_b)
    return (
        (1.0 if own_hit else 0.0) * 0.5 + (1.0 if leak_blocked else 0.0) * 0.5,
        {"owner_a": owner_a, "owner_b": owner_b, "own_hit": own_hit, "leak_blocked": leak_blocked},
    )


def _measure_canonical_contamination_rate(conn: sqlite3.Connection, world_id: str) -> float:
    contaminated = 0
    checked = 0
    for event in EventLog(conn).list(world_id):
        if event.event_type != "ADD_MEMORY":
            continue
        truth_scope = event.payload.get("truth_scope", "npc")
        if truth_scope not in {"rumor", "candidate", "npc", "faction"}:
            continue
        checked += 1
        if any(delta.scope == "canonical" for delta in event.state_deltas):
            contaminated += 1
    return contaminated / checked if checked else 0.0


def _measure_turns_playable(service: GameWorldService, world_id: str, max_ticks: int) -> int:
    playable = 0
    for _ in range(max_ticks):
        affordances = service.affordances(world_id)
        result = service.tick_world(world_id)
        if affordances or any(item.get("acted") for item in result.get("results", [])):
            playable += 1
            continue
        break
    return playable


def _runtime_mode(conn: sqlite3.Connection, world_id: str) -> str:
    row = conn.execute("SELECT runtime_mode FROM worlds WHERE id = ?", (world_id,)).fetchone()
    return row["runtime_mode"] if row and row["runtime_mode"] else "legacy_demo"


def _match_current_affordance(player_input: str, affordances: list[dict[str, Any]]) -> Any | None:
    from .llm import ActionCandidate

    normalized = player_input.strip()
    for affordance in affordances:
        label = affordance.get("label", "")
        if normalized == label or (label and label in normalized):
            return ActionCandidate(action_id=affordance["action_id"], target_id=affordance.get("target_id") or None, confidence=0.8, reason="matched_current_affordance")
    return None


def _public_explanation(explanation: dict[str, Any]) -> dict[str, Any]:
    private = {"source_event_id", "source_event", "evidence", "payload", "causal_parents"}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if key not in private}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    cleaned = scrub(explanation)
    if "state_deltas" in cleaned:
        cleaned["causal_chain"] = [
            {
                "entity_id": item.get("entity_id"),
                "attr": item.get("attr"),
                "from": item.get("old_value"),
                "to": item.get("new_value"),
                "scope": item.get("scope"),
            }
            for item in cleaned.pop("state_deltas", [])
        ]
    if "required_state" in cleaned:
        cleaned["current_objectives"] = cleaned.pop("required_state")
    return cleaned
