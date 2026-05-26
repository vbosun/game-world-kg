from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db import connect, from_json, init_db, to_json, utc_now
from .events import EventLog, EventRecord, StateDelta


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:", conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or connect(path)
        init_db(self.conn)

    def append_event(
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
        return EventLog(self.conn).append(
            world_id,
            turn_id,
            turn_index,
            event_type,
            actor_id,
            payload,
            participants=participants,
            state_deltas=state_deltas,
            evidence_refs=evidence_refs,
        )

    def append_source_text(self, world_id: str, source_type: str, text: str, turn_id: str | None = None) -> str:
        source_id = f"src_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO source_texts(id, world_id, source_type, text, turn_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_id, world_id, source_type, text, turn_id, utc_now()),
        )
        return source_id

    def append_evidence_ref(
        self,
        world_id: str,
        source_id: str,
        source_type: str,
        *,
        span_start: int | None = None,
        span_end: int | None = None,
        text: str | None = None,
        extractor: str | None = None,
        confidence: float = 1.0,
    ) -> str:
        evidence_id = f"evref_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO evidence_refs(
                id, world_id, source_id, source_type, span_start, span_end, text,
                extractor, confidence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, world_id, source_id, source_type, span_start, span_end, text, extractor, confidence, utc_now()),
        )
        return evidence_id

    def append_extraction_candidate(
        self,
        world_id: str,
        source_id: str,
        candidate: dict[str, Any],
        *,
        scope: str,
        confidence: float = 0.5,
        status: str = "candidate",
        reason: str | None = None,
    ) -> str:
        candidate_id = f"cand_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO extraction_candidates(
                id, world_id, source_id, candidate_json, scope, confidence, status, reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, world_id, source_id, to_json(candidate), scope, confidence, status, reason, utc_now()),
        )
        return candidate_id

    def append_outbox(self, world_id: str, event_id: str, topic: str, payload: dict[str, Any]) -> str:
        outbox_id = f"out_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO outbox(id, world_id, event_id, topic, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (outbox_id, world_id, event_id, topic, to_json(payload), utc_now()),
        )
        return outbox_id

    def list_pending_outbox(self, topic: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = "status = 'pending'"
        if topic is not None:
            where += " AND topic = ?"
            params.append(topic)
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM outbox WHERE {where} ORDER BY created_at LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "id": row["id"],
                "world_id": row["world_id"],
                "event_id": row["event_id"],
                "topic": row["topic"],
                "payload": from_json(row["payload_json"], {}),
                "retry_count": row["retry_count"],
            }
            for row in rows
        ]

    def mark_outbox_processed(self, outbox_id: str) -> None:
        self.conn.execute(
            "UPDATE outbox SET status = 'processed', processed_at = ? WHERE id = ?",
            (utc_now(), outbox_id),
        )

    def mark_outbox_failed(self, outbox_id: str) -> None:
        self.conn.execute(
            "UPDATE outbox SET retry_count = retry_count + 1 WHERE id = ?",
            (outbox_id,),
        )

    def set_projection_status(self, world_id: str, projector: str, projected_turn: int) -> None:
        self.conn.execute(
            """
            INSERT INTO projection_status(world_id, projector, projected_turn, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(world_id, projector) DO UPDATE SET
                projected_turn = excluded.projected_turn,
                updated_at = excluded.updated_at
            """,
            (world_id, projector, projected_turn, utc_now()),
        )

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
