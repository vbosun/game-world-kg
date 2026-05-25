from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from .db import from_json, to_json
from .events import EventLog, EventRecord, StateDelta


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

    def _apply_add_memory(self, event: EventRecord) -> None:
        payload = event.payload
        self.conn.execute(
            """
            INSERT INTO memories(
                id, world_id, owner_id, source_event_id, memory_text, truth_scope,
                salience, valence, confidence, last_recalled_turn, evidence_refs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                f"mem_{uuid4().hex}",
                event.world_id,
                payload["owner_id"],
                payload.get("source_event_id", event.id),
                payload["memory_text"],
                payload.get("truth_scope", "npc"),
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


def delta(entity_id: str, attr: str, old: Any, new: Any, amount: Any = None, scope: str = "canonical") -> StateDelta:
    return StateDelta(entity_id=entity_id, attr=attr, old_value=old, new_value=new, delta=amount, scope=scope)
