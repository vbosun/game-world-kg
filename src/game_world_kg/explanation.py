from __future__ import annotations

import sqlite3
from typing import Any

from .db import from_json


class ExplanationService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def explain_state(self, world_id: str, entity_id: str, attr: str, scope: str = "canonical") -> dict[str, Any]:
        state = self.conn.execute(
            """
            SELECT * FROM states
            WHERE world_id = ? AND entity_id = ? AND attr = ? AND scope = ?
            """,
            (world_id, entity_id, attr, scope),
        ).fetchone()
        if state is None:
            raise KeyError(f"{entity_id}.{attr}.{scope}")
        event = None
        if state["source_event_id"]:
            event = self.conn.execute("SELECT * FROM events WHERE id = ?", (state["source_event_id"],)).fetchone()
        deltas = []
        if event is not None:
            deltas = [
                {
                    "entity_id": row["entity_id"],
                    "attr": row["attr"],
                    "old_value": from_json(row["old_value_json"]),
                    "new_value": from_json(row["new_value_json"]),
                    "delta": from_json(row["delta_json"]),
                    "scope": row["scope"],
                }
                for row in self.conn.execute("SELECT * FROM state_deltas WHERE event_id = ?", (event["id"],)).fetchall()
            ]
        return {
            "world_id": world_id,
            "entity_id": entity_id,
            "attr": attr,
            "scope": scope,
            "value": from_json(state["value_json"]),
            "updated_turn": state["updated_turn"],
            "source_event_id": state["source_event_id"],
            "source_event": _event_payload(event) if event is not None else None,
            "state_deltas": deltas,
            "evidence": from_json(event["evidence_refs_json"], []) if event is not None else [],
        }

    def explain_event(self, world_id: str, event_id: str) -> dict[str, Any]:
        event = self.conn.execute("SELECT * FROM events WHERE world_id = ? AND id = ?", (world_id, event_id)).fetchone()
        if event is None:
            raise KeyError(event_id)
        return {
            "world_id": world_id,
            "event": _event_payload(event),
            "state_deltas": [
                {
                    "entity_id": row["entity_id"],
                    "attr": row["attr"],
                    "old_value": from_json(row["old_value_json"]),
                    "new_value": from_json(row["new_value_json"]),
                    "delta": from_json(row["delta_json"]),
                    "scope": row["scope"],
                }
                for row in self.conn.execute("SELECT * FROM state_deltas WHERE event_id = ?", (event_id,)).fetchall()
            ],
            "evidence": from_json(event["evidence_refs_json"], []),
        }

    def explain_memory(self, world_id: str, memory_id: str) -> dict[str, Any]:
        memory = self.conn.execute("SELECT * FROM memories WHERE world_id = ? AND id = ?", (world_id, memory_id)).fetchone()
        if memory is None:
            raise KeyError(memory_id)
        event = None
        if memory["source_event_id"]:
            event = self.conn.execute("SELECT * FROM events WHERE id = ?", (memory["source_event_id"],)).fetchone()
        return {
            "world_id": world_id,
            "memory": {
                "id": memory["id"],
                "owner_id": memory["owner_id"],
                "memory_text": memory["memory_text"],
                "truth_scope": memory["truth_scope"],
                "scope_key": memory["scope_key"] or memory["truth_scope"],
                "layer": memory["layer"],
                "memory_kind": memory["memory_kind"],
                "valid_from_turn": memory["valid_from_turn"],
                "valid_to_turn": memory["valid_to_turn"],
                "salience": memory["salience"],
                "valence": memory["valence"],
                "confidence": memory["confidence"],
                "source_event_id": memory["source_event_id"],
            },
            "source_event": _event_payload(event) if event is not None else None,
            "evidence": from_json(memory["evidence_refs_json"], []),
        }

    def explain_quest(self, world_id: str, quest: dict[str, Any]) -> dict[str, Any]:
        return {
            "world_id": world_id,
            "quest_id": quest["quest_id"],
            "title": quest["title"],
            "reason": quest["reason"],
            "tension_id": quest.get("tension_id"),
            "depends_on": quest["depends_on"],
            "required_state": quest["required_state"],
            "reward": quest["reward"],
            "failure_consequence": quest["failure_consequence"],
            "evidence": quest["evidence"],
            "traceable": bool(quest["evidence"]),
        }


def _event_payload(event: sqlite3.Row | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "id": event["id"],
        "turn_id": event["turn_id"],
        "turn_index": event["turn_index"],
        "event_order": event["event_order"],
        "event_type": event["event_type"],
        "actor_id": event["actor_id"],
        "participants": from_json(event["participants_json"], []),
        "payload": from_json(event["payload_json"], {}),
        "causal_parents": from_json(event["causal_parents_json"], []),
    }
