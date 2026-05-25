from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .db import from_json, to_json, utc_now


@dataclass(frozen=True)
class StateDelta:
    entity_id: str
    attr: str
    old_value: Any
    new_value: Any
    delta: Any = None
    scope: str = "canonical"


@dataclass(frozen=True)
class EventRecord:
    id: str
    world_id: str
    turn_id: str | None
    turn_index: int
    event_order: int
    event_type: str
    actor_id: str | None
    participants: list[str]
    payload: dict[str, Any]
    state_deltas: list[StateDelta] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)


class EventLog:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def next_turn_index(self, world_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) + 1 AS next_turn FROM turns WHERE world_id = ?",
            (world_id,),
        ).fetchone()
        return int(row["next_turn"])

    def create_turn(self, world_id: str, player_input: str | None, narration: str | None = None) -> str:
        turn_id = f"turn_{uuid4().hex}"
        turn_index = self.next_turn_index(world_id)
        self.conn.execute(
            """
            INSERT INTO turns(id, world_id, turn_index, player_input, narration, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (turn_id, world_id, turn_index, player_input, narration, utc_now()),
        )
        return turn_id

    def append(
        self,
        world_id: str,
        turn_id: str | None,
        turn_index: int,
        event_type: str,
        actor_id: str | None,
        payload: dict[str, Any],
        *,
        participants: list[str] | None = None,
        state_deltas: list[StateDelta] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> EventRecord:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(event_order), -1) + 1 AS next_order FROM events WHERE world_id = ? AND turn_index = ?",
            (world_id, turn_index),
        ).fetchone()
        event_id = f"evt_{uuid4().hex}"
        event_order = int(row["next_order"])
        participants = participants or []
        evidence_refs = evidence_refs or []
        self.conn.execute(
            """
            INSERT INTO events(
                id, world_id, turn_id, turn_index, event_order, event_type, actor_id,
                participants_json, payload_json, evidence_refs_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                world_id,
                turn_id,
                turn_index,
                event_order,
                event_type,
                actor_id,
                to_json(participants),
                to_json(payload),
                to_json(evidence_refs),
                utc_now(),
            ),
        )

        stored_deltas = state_deltas or []
        for delta in stored_deltas:
            self.conn.execute(
                """
                INSERT INTO state_deltas(
                    id, event_id, entity_id, attr, old_value_json, new_value_json, delta_json, scope
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"delta_{uuid4().hex}",
                    event_id,
                    delta.entity_id,
                    delta.attr,
                    to_json(delta.old_value),
                    to_json(delta.new_value),
                    to_json(delta.delta),
                    delta.scope,
                ),
            )

        return EventRecord(
            id=event_id,
            world_id=world_id,
            turn_id=turn_id,
            turn_index=turn_index,
            event_order=event_order,
            event_type=event_type,
            actor_id=actor_id,
            participants=participants,
            payload=payload,
            state_deltas=stored_deltas,
            evidence_refs=evidence_refs,
        )

    def list(self, world_id: str, to_turn: int | None = None) -> list[EventRecord]:
        params: list[Any] = [world_id]
        where = "world_id = ?"
        if to_turn is not None:
            where += " AND turn_index <= ?"
            params.append(to_turn)
        rows = self.conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY turn_index, event_order",
            params,
        ).fetchall()
        events: list[EventRecord] = []
        for row in rows:
            delta_rows = self.conn.execute(
                "SELECT * FROM state_deltas WHERE event_id = ?",
                (row["id"],),
            ).fetchall()
            events.append(
                EventRecord(
                    id=row["id"],
                    world_id=row["world_id"],
                    turn_id=row["turn_id"],
                    turn_index=row["turn_index"],
                    event_order=row["event_order"],
                    event_type=row["event_type"],
                    actor_id=row["actor_id"],
                    participants=from_json(row["participants_json"], []),
                    payload=from_json(row["payload_json"], {}),
                    state_deltas=[
                        StateDelta(
                            entity_id=delta["entity_id"],
                            attr=delta["attr"],
                            old_value=from_json(delta["old_value_json"]),
                            new_value=from_json(delta["new_value_json"]),
                            delta=from_json(delta["delta_json"]),
                            scope=delta["scope"],
                        )
                        for delta in delta_rows
                    ],
                    evidence_refs=from_json(row["evidence_refs_json"], []),
                )
            )
        return events
