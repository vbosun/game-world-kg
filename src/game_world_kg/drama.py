from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlayerInterestTracker:
    recent_locations: list[str]
    recent_npcs: list[str]
    recent_quests: list[str]

    @classmethod
    def from_events(cls, events: list[dict[str, Any]], limit: int = 12) -> "PlayerInterestTracker":
        locations: list[str] = []
        npcs: list[str] = []
        quests: list[str] = []
        for event in events[-limit:]:
            payload = event.get("payload", {})
            if event.get("event_type") == "MOVE_ENTITY" and payload.get("entity_id") == "player":
                locations.append(payload.get("to"))
            if event.get("event_type") in {"CONVERSATION_EVENT", "NPC_DIALOGUE"}:
                target = payload.get("target") or payload.get("npc_id")
                if target:
                    npcs.append(target)
            if event.get("event_type") == "START_QUEST":
                quests.append(payload.get("id"))
        return cls(_compact(locations), _compact(npcs), _compact(quests))


class DramaManager:
    def __init__(self, service: Any) -> None:
        self.service = service

    def foreground(self, world_id: str, limit: int = 3) -> dict[str, Any]:
        events = self.service.events(world_id)
        interest = PlayerInterestTracker.from_events(events)
        tensions = self.service.tensions(world_id)
        current_turn = self._current_turn_index(world_id)
        scored = []
        for tension in tensions:
            score = float(tension.get("priority", 0.5))
            affected = set(tension.get("affected_entities", []))
            if affected.intersection(interest.recent_locations):
                score += 0.25
            if affected.intersection(interest.recent_npcs):
                score += 0.25
            if tension.get("type") in {"hostility_rising", "resource_shortage"}:
                score += 0.1
            # Deadline urgency: closer deadline = higher score
            deadline = tension.get("deadline_turn")
            if deadline is not None and isinstance(deadline, (int, float)):
                turns_remaining = max(1, int(deadline) - current_turn)
                score += min(0.3, 3.0 / turns_remaining)
            # Stake importance
            if tension.get("stake"):
                score += 0.05
            scored.append(tension | {"foreground_score": round(score, 3)})
        scored.sort(key=lambda item: (-item["foreground_score"], item.get("tension_id") or item.get("id") or ""))
        foreground = scored[: max(1, min(limit, 3))]
        return {
            "world_id": world_id,
            "main_tension": scored[0] if scored else None,
            "side_tension": scored[1] if len(scored) > 1 else None,
            "ambient_noise": _build_ambient(scored[2:], current_turn),
            "foreground_tensions": foreground,
            "player_interest": {
                "recent_locations": interest.recent_locations,
                "recent_npcs": interest.recent_npcs,
                "recent_quests": interest.recent_quests,
            },
            "recommended_opportunity": _recommended_opportunity(foreground),
            "npc_should_approach_player": _npc_should_approach_player(foreground),
            "ambient_event": _ambient_event(foreground, current_turn),
        }

    def _current_turn_index(self, world_id: str) -> int:
        conn = getattr(self.service, "conn", None)
        if conn is not None:
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_index), 0) AS turn_index FROM turns WHERE world_id = ?",
                (world_id,),
            ).fetchone()
            return int(row["turn_index"]) if row else 0
        return 0


def _compact(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in reversed(values):
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return list(reversed(result))


def _recommended_opportunity(tensions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not tensions:
        return None
    tension = tensions[0]
    actions = tension.get("suggested_actions", [])
    result: dict[str, Any] = {
        "tension_id": tension.get("tension_id") or tension.get("id"),
        "label": tension.get("reason") or tension.get("description") or "局势正在变化。",
        "action_id": actions[0] if actions else None,
    }
    if tension.get("stake"):
        result["stake"] = tension["stake"]
    if tension.get("deadline_turn") is not None:
        result["deadline_turn"] = tension["deadline_turn"]
    if tension.get("player_touchpoints"):
        result["player_touchpoints"] = tension["player_touchpoints"]
    return result


def _npc_should_approach_player(tensions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for tension in tensions:
        sponsors = tension.get("sponsors", [])
        if sponsors:
            for sponsor in sponsors:
                if sponsor != "player":
                    return {"npc_id": sponsor, "tension_id": tension.get("tension_id") or tension.get("id"), "reason": tension.get("reason") or tension.get("description", ""), "role": "sponsor"}
        for entity_id in tension.get("affected_entities", []):
            if entity_id != "player" and not entity_id.endswith(("gate", "shop", "field", "temple", "warehouse")):
                return {"npc_id": entity_id, "tension_id": tension.get("tension_id") or tension.get("id"), "reason": tension.get("reason") or tension.get("description", "")}
    return None


def _ambient_event(tensions: list[dict[str, Any]], current_turn: int = 0) -> dict[str, Any]:
    if not tensions:
        return {"type": "quiet", "summary": "周围暂时没有新的压力浮上来。"}
    tension = tensions[0]
    deadline = tension.get("deadline_turn")
    urgency = ""
    if deadline is not None and isinstance(deadline, (int, float)) and current_turn > 0:
        remaining = max(0, int(deadline) - current_turn)
        if remaining <= 3:
            urgency = f" 仅剩 {remaining} 回合！"
        elif remaining <= 7:
            urgency = f" 还剩 {remaining} 回合。"
    return {
        "type": "pressure",
        "tension_id": tension.get("tension_id") or tension.get("id"),
        "summary": (tension.get("reason") or tension.get("description", "有人低声谈起当前局势。")) + urgency,
        "urgency": urgency.strip() if urgency else None,
    }


def _build_ambient(tensions: list[dict[str, Any]], current_turn: int = 0) -> list[dict[str, Any]]:
    """Build ambient noise from remaining tensions (beyond main + side)."""
    ambient: list[dict[str, Any]] = []
    for tension in tensions:
        item: dict[str, Any] = {
            "tension_id": tension.get("tension_id") or tension.get("id"),
            "summary": tension.get("description", ""),
            "priority": tension.get("priority", 0),
        }
        deadline = tension.get("deadline_turn")
        if deadline is not None and isinstance(deadline, (int, float)):
            remaining = max(0, int(deadline) - current_turn)
            item["turns_remaining"] = remaining
        ambient.append(item)
    return ambient
