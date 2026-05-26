from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = PACKAGE_DIR / "schema.sql"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def from_json(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    _add_column(conn, "events", "causal_parents_json", "TEXT NOT NULL DEFAULT '[]'")
    _add_column(conn, "memories", "scope_key", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "memories", "layer", "TEXT NOT NULL DEFAULT 'episodic'")
    _add_column(conn, "memories", "memory_kind", "TEXT NOT NULL DEFAULT 'generic'")
    _add_column(conn, "memories", "valid_from_turn", "INTEGER")
    _add_column(conn, "memories", "valid_to_turn", "INTEGER")
    _add_column(conn, "memories", "supersedes_memory_id", "TEXT")
    _add_column(conn, "memories", "merged_from_json", "TEXT NOT NULL DEFAULT '[]'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_segments (
            id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            source_event_id TEXT,
            speaker_id TEXT,
            segment_index INTEGER NOT NULL,
            segment_kind TEXT NOT NULL DEFAULT 'dialogue',
            text TEXT NOT NULL,
            span_start INTEGER NOT NULL DEFAULT 0,
            span_end INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_ops (
            id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            segment_id TEXT,
            op_type TEXT NOT NULL,
            layer TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            claim_key TEXT NOT NULL,
            memory_text TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'candidate',
            applied_event_id TEXT,
            reason TEXT,
            created_at TEXT NOT NULL,
            applied_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_queue (
            id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            source_event_id TEXT,
            memory_op_id TEXT,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope_key ON memories(world_id, scope_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_segments_turn ON conversation_segments(world_id, turn_id, segment_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_ops_source ON memory_ops(world_id, source_event_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(world_id, status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS action_templates (
            id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            label TEXT NOT NULL,
            target_id TEXT,
            risk TEXT NOT NULL DEFAULT 'low',
            reason TEXT NOT NULL DEFAULT '',
            preconditions_json TEXT NOT NULL DEFAULT '[]',
            effects_json TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(world_id, action_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_action_templates_world ON action_templates(world_id, enabled)")


def _add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {row["name"] for row in rows}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    try:
        conn.execute("BEGIN")
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
