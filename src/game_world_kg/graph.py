from __future__ import annotations

import sqlite3
from typing import Any

from .db import from_json


class WorldGraph:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def state(self, world_id: str, scope: str | None = None) -> dict[str, dict[str, Any]]:
        params: list[Any] = [world_id]
        where = "world_id = ?"
        if scope is not None:
            where += " AND scope = ?"
            params.append(scope)
        rows = self.conn.execute(
            f"SELECT entity_id, attr, value_json, updated_turn, scope FROM states WHERE {where} ORDER BY entity_id, attr",
            params,
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            scoped_attr = row["attr"] if row["scope"] == "canonical" else f"{row['scope']}.{row['attr']}"
            result.setdefault(row["entity_id"], {})[scoped_attr] = from_json(row["value_json"])
        return result

    def graph(self, world_id: str, scope: str | None = None) -> dict[str, list[dict[str, Any]]]:
        params: list[Any] = [world_id]
        node_where = "world_id = ?"
        edge_where = "world_id = ?"
        if scope is not None:
            node_where += " AND scope = ?"
            edge_where += " AND scope = ?"
            params.append(scope)
        nodes = [
            {
                "id": row["id"],
                "stable_key": row["stable_key"],
                "entity_type": row["entity_type"],
                "name": row["name"],
                "properties": from_json(row["properties_json"], {}),
                "scope": row["scope"],
                "valid_from_turn": row["valid_from_turn"],
                "valid_to_turn": row["valid_to_turn"],
                "confidence": row["confidence"],
                "source_event_id": row["source_event_id"],
            }
            for row in self.conn.execute(
                f"SELECT * FROM nodes WHERE {node_where} ORDER BY stable_key",
                params,
            ).fetchall()
        ]
        edge_params = params
        edges = [
            {
                "id": row["id"],
                "src_id": row["src_id"],
                "rel_type": row["rel_type"],
                "dst_id": row["dst_id"],
                "properties": from_json(row["properties_json"], {}),
                "scope": row["scope"],
                "valid_from_turn": row["valid_from_turn"],
                "valid_to_turn": row["valid_to_turn"],
                "confidence": row["confidence"],
                "source_event_id": row["source_event_id"],
            }
            for row in self.conn.execute(
                f"SELECT * FROM edges WHERE {edge_where} ORDER BY src_id, rel_type, dst_id",
                edge_params,
            ).fetchall()
        ]
        return {"nodes": nodes, "edges": edges}

    def memories(self, world_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [world_id]
        where = "world_id = ?"
        if owner_id is not None:
            where += " AND owner_id = ?"
            params.append(owner_id)
        return [
            {
                "id": row["id"],
                "owner_id": row["owner_id"],
                "source_event_id": row["source_event_id"],
                "memory_text": row["memory_text"],
                "truth_scope": row["truth_scope"],
                "salience": row["salience"],
                "valence": row["valence"],
                "confidence": row["confidence"],
                "last_recalled_turn": row["last_recalled_turn"],
            }
            for row in self.conn.execute(
                f"SELECT * FROM memories WHERE {where} ORDER BY id",
                params,
            ).fetchall()
        ]

    def events(self, world_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": row["id"],
                "turn_id": row["turn_id"],
                "turn_index": row["turn_index"],
                "event_order": row["event_order"],
                "event_type": row["event_type"],
                "actor_id": row["actor_id"],
                "participants": from_json(row["participants_json"], []),
                "payload": from_json(row["payload_json"], {}),
                "evidence_refs": from_json(row["evidence_refs_json"], []),
            }
            for row in self.conn.execute(
                "SELECT * FROM events WHERE world_id = ? ORDER BY turn_index, event_order",
                (world_id,),
            ).fetchall()
        ]

    def active_edges(self, world_id: str, src_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [world_id, src_id]
        where = "world_id = ? AND src_id = ? AND valid_to_turn IS NULL"
        if rel_type is not None:
            where += " AND rel_type = ?"
            params.append(rel_type)
        return [
            {
                "src_id": row["src_id"],
                "rel_type": row["rel_type"],
                "dst_id": row["dst_id"],
                "properties": from_json(row["properties_json"], {}),
            }
            for row in self.conn.execute(f"SELECT * FROM edges WHERE {where}", params).fetchall()
        ]

    def query_neighbors(self, world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [world_id, entity_id, entity_id]
        where = "world_id = ? AND valid_to_turn IS NULL AND (src_id = ? OR dst_id = ?)"
        if rel_type is not None:
            where += " AND rel_type = ?"
            params.append(rel_type)
        return [
            {
                "id": row["id"],
                "src_id": row["src_id"],
                "rel_type": row["rel_type"],
                "dst_id": row["dst_id"],
                "properties": from_json(row["properties_json"], {}),
                "scope": row["scope"],
                "valid_from_turn": row["valid_from_turn"],
                "source_event_id": row["source_event_id"],
            }
            for row in self.conn.execute(
                f"SELECT * FROM edges WHERE {where} ORDER BY rel_type, src_id, dst_id",
                params,
            ).fetchall()
        ]

    def query_by_scope(self, world_id: str, scope: str) -> dict[str, list[dict[str, Any]]]:
        return self.graph(world_id, scope)
