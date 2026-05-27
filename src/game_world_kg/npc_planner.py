from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .action_template import ActionTemplateEngine, ActionResolver, ActionTemplateStore
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
        store = ActionTemplateStore(self.conn)
        actions = []
        for action in ActionTemplateEngine(self.conn).list_for_actor(world_id, npc_id):
            template = store.get(world_id, action["action_id"])
            actions.append(
                action
                | {
                    "preconditions": template.preconditions if template else [],
                    "effects": template.effects if template else [],
                }
            )
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
        state = self.service.state(world_id)
        player_location = state.get("player", {}).get("location")
        tension_entities = {entity for tension in self.service.tensions(world_id)[:3] for entity in tension.get("affected_entities", [])}
        scored: list[tuple[int, int, str]] = []
        for index, node in enumerate(graph["nodes"]):
            npc_id = node["id"]
            if node["entity_type"] != "Character" or npc_id == "player" or not state.get(npc_id, {}).get("location"):
                continue
            score = 0
            if state.get(npc_id, {}).get("location") == player_location:
                score += 100
            if npc_id in tension_entities:
                score += 30
            scored.append((-score, index, npc_id))
        scored.sort()
        return [npc_id for _, _, npc_id in scored]

    @staticmethod
    def _choose_action(context: PlannerContext) -> dict[str, Any] | None:
        if not context.available_actions:
            return None
        ranked: list[dict[str, Any]] = []
        for action in context.available_actions:
            goal_relevance = EffectToGoalMatcher.score(action, context.goals)
            tension_relevance = TensionRelevanceScorer.score(action, context.visible_tensions)
            memory_relevance = MemoryRelevanceScorer.score(action, context.known_memories)
            benefit = RelationResourceBenefitScorer.score(action)
            risk_penalty = RiskToleranceScorer.penalty(action, context.goals)
            resource_cost = ResourceCostScorer.cost(action)
            score = (
                0.30 * goal_relevance
                + 0.25 * tension_relevance
                + 0.15 * memory_relevance
                + 0.15 * benefit
                - 0.20 * risk_penalty
                - 0.10 * resource_cost
            )
            ranked.append(action | {"score": round(max(0, score), 4)})
        ranked.sort(key=lambda item: (-item["score"], item["action_id"], item.get("target_id") or ""))
        return ranked[0]


class EffectToGoalMatcher:
    @staticmethod
    def score(action: dict[str, Any], goals: list[dict[str, Any]]) -> float:
        if not goals:
            return 0.2
        effects = action.get("effects", [])
        best = 0.0
        for goal in goals:
            priority = float(goal.get("priority", 0.5))
            desired = goal.get("desired_state") or {}
            goal_id = goal.get("goal_id", "")
            matched = 0.0
            if goal_id and goal_id in f"{action.get('action_id', '')} {action.get('reason', '')}":
                matched = max(matched, 0.5)
            for effect in effects:
                if desired and effect.get("entity") == desired.get("entity") and effect.get("attr") == desired.get("attr"):
                    matched = max(matched, 1.0 if effect.get("value", desired.get("value")) == desired.get("value") else 0.7)
                if effect.get("type") in {"change_relation", "add_memory"} and any(word in goal_id for word in ["help", "report", "trust", "collect", "news"]):
                    matched = max(matched, 0.6)
            best = max(best, priority * (matched or 0.25))
        return min(1.0, best)


class RiskToleranceScorer:
    @staticmethod
    def penalty(action: dict[str, Any], goals: list[dict[str, Any]]) -> float:
        risk = {"low": 0.1, "medium": 0.5, "high": 1.0}.get(action.get("risk", "low"), 0.1)
        tolerance = max((float(goal.get("risk_tolerance", 0.3)) for goal in goals), default=0.3)
        return max(0.0, risk - tolerance)


class TensionRelevanceScorer:
    @staticmethod
    def score(action: dict[str, Any], tensions: list[dict[str, Any]]) -> float:
        if not tensions:
            return 0.0
        action_id = action.get("action_id")
        target_id = action.get("target_id")
        best = 0.0
        for tension in tensions:
            priority = float(tension.get("priority", 0.5))
            if action_id in tension.get("suggested_actions", []):
                best = max(best, priority)
            if target_id and target_id in tension.get("affected_entities", []):
                best = max(best, priority * 0.8)
        return min(1.0, best)


class MemoryRelevanceScorer:
    @staticmethod
    def score(action: dict[str, Any], memories: list[dict[str, Any]]) -> float:
        text = f"{action.get('action_id', '')} {action.get('reason', '')} {action.get('target_id', '')}"
        if not memories:
            return 0.0
        hits = 0.0
        for memory in memories:
            memory_text = memory.get("memory_text", "")
            if any(token and token in memory_text for token in text.split("_")):
                hits += float(memory.get("salience", 0.5))
        return min(1.0, hits / max(1, len(memories)))


class RelationResourceBenefitScorer:
    @staticmethod
    def score(action: dict[str, Any]) -> float:
        score = 0.0
        for effect in action.get("effects", []):
            if effect.get("type") == "change_relation" and effect.get("delta", 0) > 0:
                score = max(score, 0.8)
            if effect.get("type") == "delta_resource" and effect.get("delta", 0) > 0:
                score = max(score, 0.8)
            if effect.get("type") == "add_memory":
                score = max(score, 0.4)
        return score


class ResourceCostScorer:
    @staticmethod
    def cost(action: dict[str, Any]) -> float:
        cost = 0.0
        for effect in action.get("effects", []):
            if effect.get("type") == "delta_resource" and effect.get("delta", 0) < 0:
                cost += min(1.0, abs(float(effect["delta"])) / 5)
        return min(1.0, cost)
