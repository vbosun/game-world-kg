from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .db import from_json

if TYPE_CHECKING:
    from .service import GameWorldService


class SceneRenderer:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service

    def render(self, world_id: str) -> dict[str, Any]:
        state = self.service.state(world_id)
        graph = self.service.graph(world_id)
        location_id = state.get("player", {}).get("location")
        location = self._node(world_id, location_id) if location_id else None
        visible_npcs = self._visible_npcs(world_id, state, location_id)
        connections = self._connections(world_id, location_id)
        tensions = self.service.drama_foreground(world_id).get("foreground_tensions", [])
        return {
            "world_id": world_id,
            "location": location,
            "visible_npcs": visible_npcs,
            "connections": connections,
            "foreground_tensions": tensions[:2],
            "environment_risks": self._environment_risks(tensions),
            "summary": self._summary(location, visible_npcs, connections, tensions),
            "node_count": len(graph.get("nodes", [])),
        }

    def _node(self, world_id: str, entity_id: str | None) -> dict[str, Any] | None:
        if not entity_id:
            return None
        row = self.service.conn.execute(
            """
            SELECT id, name, entity_type, properties_json
            FROM nodes
            WHERE world_id = ? AND id = ? AND valid_to_turn IS NULL
            """,
            (world_id, entity_id),
        ).fetchone()
        if row is None:
            return {"id": entity_id, "name": entity_id, "entity_type": "Unknown", "properties": {}}
        return {"id": row["id"], "name": row["name"] or row["id"], "entity_type": row["entity_type"], "properties": from_json(row["properties_json"], {})}

    def _visible_npcs(self, world_id: str, state: dict[str, dict[str, Any]], location_id: str | None) -> list[dict[str, Any]]:
        if not location_id:
            return []
        rows = self.service.conn.execute(
            """
            SELECT id, name, properties_json
            FROM nodes
            WHERE world_id = ? AND entity_type = 'Character' AND valid_to_turn IS NULL
            ORDER BY name
            """,
            (world_id,),
        ).fetchall()
        npcs: list[dict[str, Any]] = []
        for row in rows:
            if row["id"] == "player" or state.get(row["id"], {}).get("location") != location_id:
                continue
            props = from_json(row["properties_json"], {})
            npcs.append({"id": row["id"], "name": row["name"] or row["id"], "role": props.get("role") or props.get("faction_id") or "", "known_attitude": _known_attitude(state.get(row["id"], {}))})
        return npcs

    def _connections(self, world_id: str, location_id: str | None) -> list[dict[str, Any]]:
        if not location_id:
            return []
        rows = self.service.conn.execute(
            """
            SELECT e.src_id, e.dst_id, e.properties_json, n.name
            FROM edges e
            JOIN nodes n
              ON n.world_id = e.world_id
             AND n.id = CASE WHEN e.src_id = ? THEN e.dst_id ELSE e.src_id END
            WHERE e.world_id = ?
              AND e.rel_type = 'CONNECTS'
              AND e.valid_to_turn IS NULL
              AND (e.src_id = ? OR e.dst_id = ?)
            ORDER BY n.name
            """,
            (location_id, world_id, location_id, location_id),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            target_id = row["dst_id"] if row["src_id"] == location_id else row["src_id"]
            props = from_json(row["properties_json"], {})
            result.append({"id": target_id, "name": row["name"] or target_id, "blocked_by": props.get("blocked_by") or props.get("requires_state")})
        return result

    @staticmethod
    def _environment_risks(tensions: list[dict[str, Any]]) -> list[str]:
        risks = []
        for tension in tensions[:2]:
            if tension.get("type") in {"hostility_rising", "resource_shortage", "locked_location", "trust_below_threshold"}:
                risks.append(tension.get("reason", tension.get("type")))
        return risks

    @staticmethod
    def _summary(location: dict[str, Any] | None, npcs: list[dict[str, Any]], connections: list[dict[str, Any]], tensions: list[dict[str, Any]]) -> str:
        location_name = location["name"] if location else "未知地点"
        npc_text = "、".join(npc["name"] for npc in npcs) if npcs else "没有显眼的 NPC"
        path_text = "、".join(item["name"] for item in connections[:3]) if connections else "暂无可见去路"
        tension_text = tensions[0].get("reason") if tensions else "局势暂时平稳"
        return f"你在{location_name}。附近有{npc_text}。可去往：{path_text}。当前最显眼的局势是：{tension_text}"


def _known_attitude(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if key.endswith(".player") and any(word in key for word in ["trust", "hostility", "suspicion", "respect", "debt", "fear"])
    }
