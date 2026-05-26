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
