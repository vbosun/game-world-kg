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
            scored.append(tension | {"foreground_score": round(score, 3)})
        scored.sort(key=lambda item: (-item["foreground_score"], item.get("tension_id") or item.get("id") or ""))
        return {
            "world_id": world_id,
            "foreground_tensions": scored[: max(1, min(limit, 3))],
            "player_interest": {
                "recent_locations": interest.recent_locations,
                "recent_npcs": interest.recent_npcs,
                "recent_quests": interest.recent_quests,
            },
        }


def _compact(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in reversed(values):
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return list(reversed(result))
