from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KuzuStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, dict[str, Any]] = {}
        self._relations: list[dict[str, Any]] = []
        self._events: dict[str, dict[str, Any]] = {}
        self._memories: dict[str, dict[str, Any]] = {}
        self._kuzu_conn = None
        self._init_native()

    def _init_native(self) -> None:
        try:
            import kuzu  # type: ignore
        except Exception:
            return
        db_path = self.path / "database"
        try:
            db = kuzu.Database(str(db_path))
            self._kuzu_conn = kuzu.Connection(db)
        except Exception:
            self._kuzu_conn = None

    @property
    def backend(self) -> str:
        return "kuzu" if self._kuzu_conn is not None else "fallback"

    def init_schema(self) -> None:
        if self._kuzu_conn is None:
            return
        statements = [
            """
            CREATE NODE TABLE IF NOT EXISTS Entity(
                id STRING,
                world_id STRING,
                stable_key STRING,
                entity_type STRING,
                name STRING,
                scope STRING,
                version INT64,
                valid_from_turn INT64,
                valid_to_turn INT64,
                confidence DOUBLE,
                source_event_id STRING,
                properties_json STRING,
                PRIMARY KEY(id)
            )
            """,
            """
            CREATE NODE TABLE IF NOT EXISTS EventNode(
                id STRING,
                world_id STRING,
                event_type STRING,
                turn_index INT64,
                actor_id STRING,
                payload_json STRING,
                created_at STRING,
                PRIMARY KEY(id)
            )
            """,
            """
            CREATE NODE TABLE IF NOT EXISTS MemoryNode(
                id STRING,
                world_id STRING,
                owner_id STRING,
                truth_scope STRING,
                salience DOUBLE,
                valence DOUBLE,
                confidence DOUBLE,
                memory_text STRING,
                source_event_id STRING,
                PRIMARY KEY(id)
            )
            """,
            """
            CREATE REL TABLE IF NOT EXISTS RELATES(
                FROM Entity TO Entity,
                rel_type STRING,
                scope STRING,
                version INT64,
                valid_from_turn INT64,
                valid_to_turn INT64,
                confidence DOUBLE,
                source_event_id STRING,
                properties_json STRING
            )
            """,
            "CREATE REL TABLE IF NOT EXISTS EVENT_TARGETS(FROM EventNode TO Entity, role STRING)",
            "CREATE REL TABLE IF NOT EXISTS EVENT_CAUSED_BY(FROM EventNode TO EventNode)",
            "CREATE REL TABLE IF NOT EXISTS EVENT_CHANGED(FROM EventNode TO Entity, attr STRING, old_value_json STRING, new_value_json STRING)",
            "CREATE REL TABLE IF NOT EXISTS REMEMBERS(FROM Entity TO MemoryNode)",
            "CREATE REL TABLE IF NOT EXISTS MEMORY_ABOUT(FROM MemoryNode TO Entity)",
            "CREATE REL TABLE IF NOT EXISTS MEMORY_FROM_EVENT(FROM MemoryNode TO EventNode)",
        ]
        for statement in statements:
            self._kuzu_conn.execute(statement)

    def clear(self) -> None:
        self._entities.clear()
        self._relations.clear()
        self._events.clear()
        self._memories.clear()

    def upsert_entity(self, entity: dict[str, Any]) -> None:
        self._entities[entity["id"]] = dict(entity)

    def upsert_relation(self, relation: dict[str, Any]) -> None:
        key = (relation["src_id"], relation["rel_type"], relation["dst_id"], relation.get("source_event_id"))
        self._relations = [
            item
            for item in self._relations
            if (item["src_id"], item["rel_type"], item["dst_id"], item.get("source_event_id")) != key
        ]
        self._relations.append(dict(relation))

    def upsert_event(self, event: dict[str, Any]) -> None:
        self._events[event["id"]] = dict(event)

    def upsert_memory(self, memory: dict[str, Any]) -> None:
        self._memories[memory["id"]] = dict(memory)

    def query_neighbors(self, world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        return [
            item
            for item in self._relations
            if item.get("world_id") == world_id
            and item.get("valid_to_turn") is None
            and (item.get("src_id") == entity_id or item.get("dst_id") == entity_id)
            and (rel_type is None or item.get("rel_type") == rel_type)
        ]

    def query_current_graph(self, world_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "backend": self.backend,
            "nodes": [item for item in self._entities.values() if item.get("world_id") == world_id],
            "edges": [
                item
                for item in self._relations
                if item.get("world_id") == world_id and item.get("valid_to_turn") is None
            ],
            "events": [item for item in self._events.values() if item.get("world_id") == world_id],
            "memories": [item for item in self._memories.values() if item.get("world_id") == world_id],
        }

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
