from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .action_template import ActionTemplateEngine, ActionResolver
from .db import transaction
from .events import EventLog
from .graph import WorldGraph


@dataclass(frozen=True)
class PlannerContext:
    world_id: str
    npc_id: str
    current_location: str | None
    goals: list[dict[str, Any]]
    known_memories: list[dict[str, Any]]
    visible_tensions: list[dict[str, Any]]
    available_actions: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "npc_id": self.npc_id,
            "current_location": self.current_location,
            "goals": self.goals,
            "known_memories": self.known_memories,
            "visible_tensions": self.visible_tensions,
            "available_actions": self.available_actions,
        }


class NPCPlanner:
    def __init__(self, conn: sqlite3.Connection, service: Any) -> None:
        self.conn = conn
        self.service = service

    def context(self, world_id: str, npc_id: str) -> PlannerContext:
        state = self.service.state(world_id)
        graph = self.service.graph(world_id)
        node = next((item for item in graph["nodes"] if item["id"] == npc_id), None)
        properties = node.get("properties", {}) if node else {}
        memories = self.service.recall_memory(world_id, npc_id, "目标 传闻 危险 资源", 5)
        tensions = [
            tension
            for tension in self.service.tensions(world_id)
            if npc_id in tension.get("affected_entities", []) or any(goal.get("goal_id", "") in tension.get("reason", "") for goal in properties.get("goals", []))
        ]
        actions = ActionTemplateEngine(self.conn).list_for_actor(world_id, npc_id)
        return PlannerContext(
            world_id=world_id,
            npc_id=npc_id,
            current_location=state.get(npc_id, {}).get("location"),
            goals=properties.get("goals", []),
            known_memories=memories,
            visible_tensions=tensions,
            available_actions=actions,
        )

    def tick_npc(self, world_id: str, npc_id: str) -> dict[str, Any]:
        context = self.context(world_id, npc_id)
        action = self._choose_action(context)
        if action is None:
            return {"world_id": world_id, "npc_id": npc_id, "acted": False, "reason": "no_valid_affordance", "context": context.as_dict()}
        log = EventLog(self.conn)
        with transaction(self.conn):
            turn_id = log.create_turn(world_id, f"npc_tick:{npc_id}:{action['action_id']}")
            row = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            resolution = ActionResolver(self.conn).resolve(
                world_id,
                turn_id,
                row["turn_index"],
                action["action_id"],
                [{"source_id": turn_id, "source_type": "npc_planner", "extractor": "npc_planner_v1", "confidence": action.get("score", 0.5)}],
                actor_id=npc_id,
                target_id=action.get("target_id") or None,
            )
            if resolution is None or not resolution.accepted:
                return {
                    "world_id": world_id,
                    "npc_id": npc_id,
                    "acted": False,
                    "action": action,
                    "reason": resolution.reason if resolution else "no_template",
                    "context": context.as_dict(),
                }
            marker = log.append(
                world_id,
                turn_id,
                row["turn_index"],
                "NPC_ACTION",
                npc_id,
                {"action_id": action["action_id"], "target_id": action.get("target_id"), "reason": action.get("reason", "")},
                participants=[npc_id, action.get("target_id", "")],
                causal_parents=[event.id for event in resolution.events],
                evidence_refs=[{"source_id": turn_id, "source_type": "npc_planner", "extractor": "npc_planner_v1", "confidence": action.get("score", 0.5)}],
            )
        return {
            "world_id": world_id,
            "npc_id": npc_id,
            "acted": True,
            "action": action,
            "events": [
                {"id": event.id, "event_type": event.event_type, "payload": event.payload}
                for event in [*resolution.events, marker]
            ],
            "context": context.as_dict(),
        }

    def tick_world(self, world_id: str, limit: int = 3) -> dict[str, Any]:
        npcs = self._active_npcs(world_id)[: max(1, min(limit, 3))]
        results = [self.tick_npc(world_id, npc_id) for npc_id in npcs]
        return {"world_id": world_id, "npc_count": len(npcs), "results": results}

    def _active_npcs(self, world_id: str) -> list[str]:
        graph = WorldGraph(self.conn).graph(world_id)
        return [
            node["id"]
            for node in graph["nodes"]
            if node["entity_type"] == "Character" and node["id"] != "player" and self.service.state(world_id).get(node["id"], {}).get("location")
        ]

    @staticmethod
    def _choose_action(context: PlannerContext) -> dict[str, Any] | None:
        if not context.available_actions:
            return None
        ranked: list[dict[str, Any]] = []
        for action in context.available_actions:
            score = 0.2
            if action["action_id"] in {"patrol", "move_to_location"}:
                score += 0.2
            if action["action_id"] in {"request_help", "talk_to", "report_to_faction"}:
                score += 0.15
            if context.visible_tensions:
                score += 0.25
            risk_penalty = {"low": 0, "medium": 0.15, "high": 0.35}.get(action.get("risk", "low"), 0)
            ranked.append(action | {"score": max(0, score - risk_penalty)})
        ranked.sort(key=lambda item: (-item["score"], item["action_id"], item.get("target_id") or ""))
        return ranked[0]
