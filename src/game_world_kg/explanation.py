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
