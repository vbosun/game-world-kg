from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from .chroma_store import ChromaStore
from .db import from_json, to_json
from .events import EventLog, EventRecord, StateDelta
from .kuzu_store import KuzuStore
from .sqlite_store import SQLiteStore


class StateProjector:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_state(self, world_id: str, entity_id: str, attr: str, scope: str = "canonical") -> Any:
        row = self.conn.execute(
            """
            SELECT value_json FROM states
            WHERE world_id = ? AND entity_id = ? AND attr = ? AND scope = ?
            """,
            (world_id, entity_id, attr, scope),
        ).fetchone()
        return from_json(row["value_json"]) if row else None

    def set_state(
        self,
        world_id: str,
        entity_id: str,
        attr: str,
        value: Any,
        turn_index: int,
        event_id: str,
        scope: str = "canonical",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO states(world_id, entity_id, attr, value_json, updated_turn, scope, source_event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(world_id, entity_id, attr, scope) DO UPDATE SET
                value_json = excluded.value_json,
                updated_turn = excluded.updated_turn,
                source_event_id = excluded.source_event_id
            """,
            (world_id, entity_id, attr, to_json(value), turn_index, scope, event_id),
        )

    def apply_event(self, event: EventRecord) -> None:
        handler = getattr(self, f"_apply_{event.event_type.lower()}", None)
        if handler is not None:
            handler(event)
        for delta in event.state_deltas:
            self.set_state(
                event.world_id,
                delta.entity_id,
                delta.attr,
                delta.new_value,
                event.turn_index,
                event.id,
                delta.scope,
            )

    def replay_to_turn(self, world_id: str, to_turn: int | None = None) -> None:
        self.conn.execute("DELETE FROM states WHERE world_id = ?", (world_id,))
        self.conn.execute("DELETE FROM nodes WHERE world_id = ?", (world_id,))
        self.conn.execute("DELETE FROM edges WHERE world_id = ?", (world_id,))
        self.conn.execute("DELETE FROM memories WHERE world_id = ?", (world_id,))
        for event in EventLog(self.conn).list(world_id, to_turn):
            self.apply_event(event)

    def _apply_create_entity(self, event: EventRecord) -> None:
        payload = event.payload
        stable_key = payload["stable_key"]
        properties = dict(payload.get("properties", {}))
        if "version" not in properties:
            properties["version"] = 1
        self.conn.execute(
            """
            INSERT INTO nodes(
                id, world_id, stable_key, entity_type, name, properties_json,
                scope, valid_from_turn, valid_to_turn, confidence, source_event_id, evidence_refs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                stable_key,
                event.world_id,
                stable_key,
                payload["entity_type"],
                payload.get("name"),
                to_json(properties),
                payload.get("scope", "canonical"),
                event.turn_index,
                payload.get("confidence", 1.0),
                event.id,
                to_json(event.evidence_refs),
            ),
        )

    def _apply_create_location(self, event: EventRecord) -> None:
        self._apply_create_entity(event)

    def _apply_create_character(self, event: EventRecord) -> None:
        self._apply_create_entity(event)

    def _apply_create_item(self, event: EventRecord) -> None:
        self._apply_create_entity(event)

    def _apply_create_faction(self, event: EventRecord) -> None:
        self._apply_create_entity(event)

    def _apply_create_rule(self, event: EventRecord) -> None:
        payload = event.payload
        rule_id = payload.get("rule_id") or payload.get("id") or event.id
        self._insert_bootstrap_node(event, rule_id, "Rule", payload.get("name") or rule_id, payload)

    def _apply_create_action_template(self, event: EventRecord) -> None:
        payload = event.payload
        action_id = payload["action_id"]
        self._insert_bootstrap_node(event, action_id, "ActionTemplate", payload.get("label_template") or action_id, payload)

    def _apply_add_tension(self, event: EventRecord) -> None:
        payload = event.payload
        tension_id = payload["id"]
        self._insert_bootstrap_node(event, tension_id, "Tension", payload.get("description") or tension_id, payload)
        for entity_id in payload.get("affected_entities", []):
            self._insert_edge(event, tension_id, "AFFECTS", entity_id, {})

    def _apply_start_quest(self, event: EventRecord) -> None:
        payload = event.payload
        quest_id = payload["id"]
        self._insert_bootstrap_node(event, quest_id, "Quest", payload.get("title") or quest_id, payload)
        self._insert_edge(event, quest_id, "ISSUED_BY", payload["issuer_id"], {})
        self._insert_edge(event, quest_id, "FROM_TENSION", payload["tension_id"], {})

    def _apply_move_entity(self, event: EventRecord) -> None:
        entity_id = event.payload["entity_id"]
        to_location = event.payload["to"]
        self._close_edges(event.world_id, entity_id, "LOCATED_AT", event.turn_index)
        self._insert_edge(event, entity_id, "LOCATED_AT", to_location, {})

    def _apply_transfer_item(self, event: EventRecord) -> None:
        item_id = event.payload["item_id"]
        new_holder = event.payload["to"]
        old_holder = event.payload.get("from")
        if old_holder:
            self._close_edges(event.world_id, old_holder, "OWNS", event.turn_index, dst_id=item_id)
        self._insert_edge(event, new_holder, "OWNS", item_id, {})

    def _apply_change_relation(self, event: EventRecord) -> None:
        src = event.payload["src"]
        rel = event.payload["rel"]
        dst = event.payload["dst"]
        value = event.payload.get("value")
        if value is None:
            current = self.get_state(event.world_id, src, f"{rel.lower()}.{dst}", "canonical") or 0
            value = current + event.payload.get("delta", 0)
        self._close_edges(event.world_id, src, rel, event.turn_index, dst_id=dst)
        self._insert_edge(event, src, rel, dst, {"value": value})

    def _apply_connect_location(self, event: EventRecord) -> None:
        payload = event.payload
        self._insert_edge(event, payload["from"], "CONNECTS", payload["to"], payload.get("properties", {}))

    def _apply_add_memory(self, event: EventRecord) -> None:
        payload = event.payload
        self.conn.execute(
            """
            INSERT INTO memories(
                id, world_id, owner_id, source_event_id, memory_text, truth_scope,
                scope_key, layer, memory_kind, valid_from_turn, valid_to_turn,
                supersedes_memory_id, merged_from_json, salience, valence, confidence,
                last_recalled_turn, evidence_refs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                f"mem_{uuid4().hex}",
                event.world_id,
                payload["owner_id"],
                payload.get("source_event_id", event.id),
                payload["memory_text"],
                payload.get("truth_scope", "npc"),
                payload.get("scope_key") or payload.get("truth_scope", "npc"),
                payload.get("layer", "episodic"),
                payload.get("memory_kind", "generic"),
                payload.get("valid_from_turn", event.turn_index),
                payload.get("valid_to_turn"),
                payload.get("supersedes_memory_id"),
                to_json(payload.get("merged_from", [])),
                payload.get("salience", 0.5),
                payload.get("valence", 0),
                payload.get("confidence", 1.0),
                to_json(event.evidence_refs),
            ),
        )

    def _apply_set_state(self, event: EventRecord) -> None:
        payload = event.payload
        self.set_state(
            event.world_id,
            payload["entity_id"],
            payload["attr"],
            payload["value"],
            event.turn_index,
            event.id,
            payload.get("scope", "canonical"),
        )

    def _apply_delta_resource(self, event: EventRecord) -> None:
        payload = event.payload
        entity_id = payload["entity_id"]
        attr = payload["attr"]
        current = self.get_state(event.world_id, entity_id, attr, payload.get("scope", "canonical")) or 0
        self.set_state(
            event.world_id,
            entity_id,
            attr,
            current + payload["delta"],
            event.turn_index,
            event.id,
            payload.get("scope", "canonical"),
        )

    def _close_edges(
        self,
        world_id: str,
        src_id: str,
        rel_type: str,
        turn_index: int,
        dst_id: str | None = None,
    ) -> None:
        params: list[Any] = [turn_index, world_id, src_id, rel_type]
        where = "world_id = ? AND src_id = ? AND rel_type = ? AND valid_to_turn IS NULL"
        if dst_id is not None:
            where += " AND dst_id = ?"
            params.append(dst_id)
        self.conn.execute(f"UPDATE edges SET valid_to_turn = ? WHERE {where}", params)

    def _insert_edge(self, event: EventRecord, src_id: str, rel_type: str, dst_id: str, properties: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO edges(
                id, world_id, src_id, rel_type, dst_id, properties_json,
                scope, valid_from_turn, valid_to_turn, confidence, source_event_id, evidence_refs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'canonical', ?, NULL, 1.0, ?, ?)
            """,
            (
                f"edge_{uuid4().hex}",
                event.world_id,
                src_id,
                rel_type,
                dst_id,
                to_json(properties),
                event.turn_index,
                event.id,
                to_json(event.evidence_refs),
            ),
        )

    def _insert_bootstrap_node(self, event: EventRecord, stable_key: str, entity_type: str, name: str | None, properties: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO nodes(
                id, world_id, stable_key, entity_type, name, properties_json,
                scope, valid_from_turn, valid_to_turn, confidence, source_event_id, evidence_refs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'canonical', ?, NULL, 1.0, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                stable_key,
                event.world_id,
                stable_key,
                entity_type,
                name,
                to_json(properties),
                event.turn_index,
                event.id,
                to_json(event.evidence_refs),
            ),
        )


def delta(entity_id: str, attr: str, old: Any, new: Any, amount: Any = None, scope: str = "canonical") -> StateDelta:
    return StateDelta(entity_id=entity_id, attr=attr, old_value=old, new_value=new, delta=amount, scope=scope)


class KuzuProjector:
    projector_name = "kuzu_graph"
    topics = {"kuzu_graph_update"}

    def __init__(self, conn: sqlite3.Connection, store: KuzuStore) -> None:
        self.conn = conn
        self.store = store
        self.store.init_schema()

    def run_pending(self, world_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        sqlite_store = SQLiteStore(conn=self.conn)
        items = sqlite_store.list_pending_outbox("kuzu_graph_update", limit)
        processed = 0
        for item in items:
            if world_id is not None and item["world_id"] != world_id:
                continue
            self._project_event_payload(item["world_id"], item["payload"])
            sqlite_store.mark_outbox_processed(item["id"])
            sqlite_store.set_projection_status(item["world_id"], self.projector_name, item["payload"].get("turn_index", 0))
            processed += 1
        return {"projector": self.projector_name, "processed": processed, "backend": self.store.backend}

    def rebuild(self, world_id: str) -> dict[str, Any]:
        self.store.clear()
        for row in self.conn.execute("SELECT * FROM nodes WHERE world_id = ?", (world_id,)).fetchall():
            self.store.upsert_entity(
                {
                    "id": row["id"],
                    "world_id": row["world_id"],
                    "stable_key": row["stable_key"],
                    "entity_type": row["entity_type"],
                    "name": row["name"],
                    "scope": row["scope"],
                    "version": from_json(row["properties_json"], {}).get("version", 1),
                    "valid_from_turn": row["valid_from_turn"],
                    "valid_to_turn": row["valid_to_turn"],
                    "confidence": row["confidence"],
                    "source_event_id": row["source_event_id"],
                    "properties": from_json(row["properties_json"], {}),
                }
            )
        for row in self.conn.execute("SELECT * FROM edges WHERE world_id = ?", (world_id,)).fetchall():
            self.store.upsert_relation(
                {
                    "world_id": row["world_id"],
                    "src_id": row["src_id"],
                    "rel_type": row["rel_type"],
                    "dst_id": row["dst_id"],
                    "scope": row["scope"],
                    "version": 1,
                    "valid_from_turn": row["valid_from_turn"],
                    "valid_to_turn": row["valid_to_turn"],
                    "confidence": row["confidence"],
                    "source_event_id": row["source_event_id"],
                    "properties": from_json(row["properties_json"], {}),
                }
            )
        for row in self.conn.execute("SELECT * FROM memories WHERE world_id = ?", (world_id,)).fetchall():
            self.store.upsert_memory(_memory_node_payload(row))
        for event in EventLog(self.conn).list(world_id):
            self.store.upsert_event(_event_node_payload(event))
        max_turn = _max_event_turn(self.conn, world_id)
        SQLiteStore(conn=self.conn).set_projection_status(world_id, self.projector_name, max_turn)
        return {"projector": self.projector_name, "rebuilt": True, "backend": self.store.backend, "projected_turn": max_turn}

    def _project_event_payload(self, world_id: str, payload: dict[str, Any]) -> None:
        event_type = payload["event_type"]
        event_id = payload["event_id"]
        event_node = {
            "id": event_id,
            "world_id": world_id,
            "event_type": event_type,
            "turn_index": payload.get("turn_index", 0),
            "actor_id": payload.get("actor_id"),
            "payload": payload.get("payload", {}),
        }
        self.store.upsert_event(event_node)
        if event_type in {"CREATE_ENTITY", "CREATE_LOCATION", "CREATE_CHARACTER", "CREATE_ITEM", "CREATE_FACTION"}:
            entity = payload["payload"]
            self.store.upsert_entity(
                {
                    "id": entity["stable_key"],
                    "world_id": world_id,
                    "stable_key": entity["stable_key"],
                    "entity_type": entity["entity_type"],
                    "name": entity.get("name"),
                    "scope": entity.get("scope", "canonical"),
                    "version": entity.get("properties", {}).get("version", 1),
                    "valid_from_turn": payload.get("turn_index", 0),
                    "valid_to_turn": None,
                    "confidence": entity.get("confidence", 1.0),
                    "source_event_id": event_id,
                    "properties": entity.get("properties", {}),
                }
            )
        elif event_type == "MOVE_ENTITY":
            data = payload["payload"]
            self.store.upsert_relation(_relation_payload(world_id, data["entity_id"], "LOCATED_AT", data["to"], event_id, payload.get("turn_index", 0)))
        elif event_type == "TRANSFER_ITEM":
            data = payload["payload"]
            self.store.upsert_relation(_relation_payload(world_id, data["to"], "OWNS", data["item_id"], event_id, payload.get("turn_index", 0)))
        elif event_type == "CHANGE_RELATION":
            data = payload["payload"]
            self.store.upsert_relation(
                _relation_payload(world_id, data["src"], data["rel"], data["dst"], event_id, payload.get("turn_index", 0), {"value": data.get("value")})
            )
        elif event_type == "CONNECT_LOCATION":
            data = payload["payload"]
            self.store.upsert_relation(
                _relation_payload(world_id, data["from"], "CONNECTS", data["to"], event_id, payload.get("turn_index", 0), data.get("properties", {}))
            )
        elif event_type == "ADD_MEMORY":
            data = payload["payload"]
            self.store.upsert_memory(
                {
                    "id": event_id,
                    "world_id": world_id,
                    "owner_id": data.get("owner_id"),
                    "truth_scope": data.get("truth_scope", "npc"),
                    "scope_key": data.get("scope_key") or data.get("truth_scope", "npc"),
                    "layer": data.get("layer", "episodic"),
                    "memory_kind": data.get("memory_kind", "generic"),
                    "salience": data.get("salience", 0.5),
                    "valence": data.get("valence", 0),
                    "confidence": data.get("confidence", 1.0),
                    "memory_text": data.get("memory_text", ""),
                    "source_event_id": data.get("source_event_id", event_id),
                }
            )
        elif event_type in {"CREATE_ACTION_TEMPLATE", "CREATE_RULE", "ADD_TENSION", "START_QUEST"}:
            data = payload["payload"]
            if event_type == "CREATE_ACTION_TEMPLATE":
                entity_id = data["action_id"]
                entity_type = "ActionTemplate"
                name = data.get("label_template") or entity_id
            elif event_type == "CREATE_RULE":
                entity_id = data.get("rule_id") or data.get("id") or event_id
                entity_type = "Rule"
                name = data.get("name") or entity_id
            elif event_type == "ADD_TENSION":
                entity_id = data["id"]
                entity_type = "Tension"
                name = data.get("description") or entity_id
            else:
                entity_id = data["id"]
                entity_type = "Quest"
                name = data.get("title") or entity_id
            self.store.upsert_entity(
                {
                    "id": entity_id,
                    "world_id": world_id,
                    "stable_key": entity_id,
                    "entity_type": entity_type,
                    "name": name,
                    "scope": "canonical",
                    "version": 1,
                    "valid_from_turn": payload.get("turn_index", 0),
                    "valid_to_turn": None,
                    "confidence": 1.0,
                    "source_event_id": event_id,
                    "properties": data,
                }
            )
            if event_type == "ADD_TENSION":
                for affected in data.get("affected_entities", []):
                    self.store.upsert_relation(_relation_payload(world_id, entity_id, "AFFECTS", affected, event_id, payload.get("turn_index", 0)))
            if event_type == "START_QUEST":
                self.store.upsert_relation(_relation_payload(world_id, entity_id, "ISSUED_BY", data["issuer_id"], event_id, payload.get("turn_index", 0)))
                self.store.upsert_relation(_relation_payload(world_id, entity_id, "FROM_TENSION", data["tension_id"], event_id, payload.get("turn_index", 0)))


class ChromaProjector:
    projector_name = "chroma_vector"

    def __init__(self, conn: sqlite3.Connection, store: ChromaStore) -> None:
        self.conn = conn
        self.store = store
        self.store.init_collections()

    def run_pending(self, world_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        sqlite_store = SQLiteStore(conn=self.conn)
        processed = 0
        for topic in ["chroma_event_upsert", "chroma_evidence_upsert", "chroma_memory_upsert"]:
            for item in sqlite_store.list_pending_outbox(topic, limit):
                if world_id is not None and item["world_id"] != world_id:
                    continue
                self._project(item["topic"], item["world_id"], item["payload"])
                sqlite_store.mark_outbox_processed(item["id"])
                sqlite_store.set_projection_status(item["world_id"], self.projector_name, item["payload"].get("turn_index", 0))
                processed += 1
        return {"projector": self.projector_name, "processed": processed, "backend": self.store.backend}

    def rebuild(self, world_id: str) -> dict[str, Any]:
        self.store.clear()
        for event in EventLog(self.conn).list(world_id):
            payload = {
                "event_id": event.id,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "participants": event.participants,
                "payload": event.payload,
                "evidence_refs": event.evidence_refs,
                "turn_index": event.turn_index,
            }
            self._project("chroma_event_upsert", world_id, payload)
            if event.evidence_refs:
                self._project("chroma_evidence_upsert", world_id, payload)
        for row in self.conn.execute("SELECT * FROM memories WHERE world_id = ?", (world_id,)).fetchall():
            self.store.upsert_memory(
                row["id"],
                row["memory_text"],
                {
                    "world_id": row["world_id"],
                    "owner_id": row["owner_id"],
                    "scope": row["truth_scope"],
                    "scope_key": row["scope_key"] or row["truth_scope"],
                    "layer": row["layer"],
                    "memory_kind": row["memory_kind"],
                    "source_event_id": row["source_event_id"],
                    "salience": row["salience"],
                    "valence": row["valence"],
                    "confidence": row["confidence"],
                },
            )
        max_turn = _max_event_turn(self.conn, world_id)
        SQLiteStore(conn=self.conn).set_projection_status(world_id, self.projector_name, max_turn)
        return {"projector": self.projector_name, "rebuilt": True, "backend": self.store.backend, "projected_turn": max_turn}

    def _project(self, topic: str, world_id: str, payload: dict[str, Any]) -> None:
        metadata = {
            "world_id": world_id,
            "source_event_id": payload["event_id"],
            "event_type": payload["event_type"],
            "turn_index": payload.get("turn_index", 0),
            "scope": "canonical",
            "confidence": 1.0,
        }
        if topic == "chroma_event_upsert":
            self.store.upsert_event_summary(
                payload["event_id"],
                f"{payload['event_type']} {payload.get('actor_id') or ''} {payload.get('participants', [])} {payload.get('payload', {})}",
                metadata,
            )
        elif topic == "chroma_evidence_upsert":
            for index, evidence in enumerate(payload.get("evidence_refs", [])):
                text = evidence.get("text") or f"{payload['event_type']} evidence from {evidence.get('source_id')}"
                self.store.upsert_source(
                    f"{payload['event_id']}_evidence_{index}",
                    text,
                    metadata | {
                        "source_id": evidence.get("source_id"),
                        "source_type": evidence.get("source_type", "event_evidence"),
                        "confidence": evidence.get("confidence", 1.0),
                    },
                )
        elif topic == "chroma_memory_upsert":
            data = payload.get("payload", {})
            self.store.upsert_memory(
                payload["event_id"],
                data.get("memory_text", ""),
                metadata | {
                    "owner_id": data.get("owner_id"),
                    "scope": data.get("truth_scope", "npc"),
                    "scope_key": data.get("scope_key") or data.get("truth_scope", "npc"),
                    "layer": data.get("layer", "episodic"),
                    "memory_kind": data.get("memory_kind", "generic"),
                    "salience": data.get("salience", 0.5),
                    "valence": data.get("valence", 0),
                    "confidence": data.get("confidence", 1.0),
                },
            )


def _relation_payload(
    world_id: str,
    src_id: str,
    rel_type: str,
    dst_id: str,
    event_id: str,
    turn_index: int,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "world_id": world_id,
        "src_id": src_id,
        "rel_type": rel_type,
        "dst_id": dst_id,
        "scope": "canonical",
        "version": 1,
        "valid_from_turn": turn_index,
        "valid_to_turn": None,
        "confidence": 1.0,
        "source_event_id": event_id,
        "properties": properties or {},
    }


def _event_node_payload(event: EventRecord) -> dict[str, Any]:
    return {
        "id": event.id,
        "world_id": event.world_id,
        "event_type": event.event_type,
        "turn_index": event.turn_index,
        "actor_id": event.actor_id,
        "payload": event.payload,
    }


def _memory_node_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "world_id": row["world_id"],
        "owner_id": row["owner_id"],
        "truth_scope": row["truth_scope"],
        "scope_key": row["scope_key"] or row["truth_scope"],
        "layer": row["layer"],
        "memory_kind": row["memory_kind"],
        "salience": row["salience"],
        "valence": row["valence"],
        "confidence": row["confidence"],
        "memory_text": row["memory_text"],
        "source_event_id": row["source_event_id"],
    }


def _max_event_turn(conn: sqlite3.Connection, world_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(turn_index), 0) AS turn_index FROM events WHERE world_id = ?", (world_id,)).fetchone()
    return int(row["turn_index"])
