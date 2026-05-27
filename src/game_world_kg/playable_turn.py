from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .affordance import AffordanceEngine
from .db import transaction
from .events import EventLog
from .feedback_renderer import FeedbackRenderer
from .input_binder import BoundAction, InputBinder
from .projector import StateProjector
from .scene_renderer import SceneRenderer

if TYPE_CHECKING:
    from .service import GameWorldService


class PlayableTurnKernel:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service
        self.binder = InputBinder()
        self.feedback = FeedbackRenderer()

    def play_state(self, world_id: str) -> dict[str, Any]:
        self.service._require_world(world_id)
        return {
            "world": self.service.get_world(world_id),
            "scene": SceneRenderer(self.service).render(world_id),
            "affordances": self.play_affordances(world_id),
            "player": self.player_panel(world_id),
            "quests": self.quest_journal(world_id),
            "tensions": self.tension_journal(world_id),
            "relationships": self.relationship_panel(world_id),
            "foreground": self.service.drama_foreground(world_id),
            "timeline": self.timeline(world_id, limit=8),
        }

    def play_affordances(self, world_id: str) -> list[dict[str, Any]]:
        items = self.service.affordances(world_id)
        risk_order = {"low": 0, "medium": 1, "high": 2}
        return sorted(items, key=lambda item: (risk_order.get(item.get("risk", "low"), 9), item.get("label", "")))[:7]

    def play_turn(self, world_id: str, player_input: str, *, selected_action_id: str | None = None, selected_target_id: str | None = None) -> dict[str, Any]:
        self.service._require_world(world_id)
        before = self.service.state(world_id)
        affordances = self.play_affordances(world_id)
        bound = self.binder.bind(player_input, affordances, selected_action_id=selected_action_id, selected_target_id=selected_target_id)
        if bound is None:
            turn_result = self._reject(world_id, player_input, affordances)
        else:
            turn_result = self._run_bound_turn(world_id, player_input, bound)
        after = self.service.state(world_id)
        feedback = self.feedback.render(turn_result, before, after) if turn_result.get("accepted") or turn_result.get("events") else turn_result["feedback"]
        return {
            "turn": {key: turn_result[key] for key in ["turn_id", "turn_index", "accepted", "action_id", "reason"] if key in turn_result},
            "bound_action": _bound_payload(bound),
            "scene": SceneRenderer(self.service).render(world_id),
            "affordances": self.play_affordances(world_id),
            "feedback": feedback,
            "changes": feedback["changes"],
            "next_hooks": feedback["next_hooks"],
            "player": self.player_panel(world_id),
            "quests": self.quest_journal(world_id),
            "tensions": self.tension_journal(world_id),
            "relationships": self.relationship_panel(world_id),
        }

    def _run_bound_turn(self, world_id: str, player_input: str, bound: BoundAction) -> dict[str, Any]:
        command = bound.label
        if player_input.strip() and bound.label not in player_input:
            command = f"{bound.label}。玩家意图：{player_input.strip()}"
        return self.service.turn(world_id, command)

    def _reject(self, world_id: str, player_input: str, affordances: list[dict[str, Any]]) -> dict[str, Any]:
        reason = "自由输入没有绑定到当前任何合法行动"
        with self.service._lock:
            with transaction(self.service.conn):
                log = EventLog(self.service.conn)
                turn_id = log.create_turn(world_id, player_input, reason)
                turn = self.service.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                event = log.append(
                    world_id,
                    turn_id,
                    turn["turn_index"],
                    "ACTION_REJECTED",
                    "player",
                    {"reason": reason, "player_input": player_input, "available_actions": [item["action_id"] for item in affordances]},
                    participants=["player"],
                )
                StateProjector(self.service.conn).apply_event(event)
        event_payload = {"id": event.id, "event_type": event.event_type, "actor_id": event.actor_id, "participants": event.participants, "payload": event.payload}
        feedback = self.feedback.rejection(player_input, affordances, reason)
        return {
            "turn_id": turn_id,
            "turn_index": turn["turn_index"],
            "accepted": False,
            "action_id": "__unparsed__",
            "reason": reason,
            "narration": feedback["narration"],
            "events": [event_payload],
            "affordances": affordances,
            "feedback": feedback,
        }

    def player_panel(self, world_id: str) -> dict[str, Any]:
        state = self.service.state(world_id)
        player = state.get("player", {})
        return {
            "location": player.get("location"),
            "identity_tags": _list_value(player.get("identity_tags")),
            "permissions": _list_value(player.get("permissions")),
            "known_clues": self._known_clues(world_id),
            "resources": {key: value for key, value in player.items() if key in {"gold", "food", "stamina"} or key.startswith("resource.")},
            "skills": {key.removeprefix("skill."): value for key, value in player.items() if key.startswith("skill.")},
        }

    def relationship_panel(self, world_id: str) -> list[dict[str, Any]]:
        state = self.service.state(world_id)
        rows = self.service.conn.execute(
            """
            SELECT id, name, entity_type
            FROM nodes
            WHERE world_id = ? AND entity_type IN ('Character', 'Faction') AND valid_to_turn IS NULL
            ORDER BY entity_type, name
            """,
            (world_id,),
        ).fetchall()
        result = []
        for row in rows:
            if row["id"] == "player":
                continue
            values = state.get(row["id"], {})
            visible = {
                key: value
                for key, value in values.items()
                if key.endswith(".player") and any(word in key for word in ["trust", "hostility", "suspicion", "respect", "fear", "debt", "reputation"])
            }
            if visible:
                result.append({"id": row["id"], "name": row["name"] or row["id"], "type": row["entity_type"], "attitudes": visible})
        return result

    def quest_journal(self, world_id: str) -> list[dict[str, Any]]:
        tensions = {item["tension_id"]: item for item in self.service.tensions(world_id)}
        affordance_ids = {item["action_id"] for item in self.service.affordances(world_id)}
        journal = []
        for quest in self.service.quests(world_id):
            tension_id = quest.get("tension_id") or quest.get("source_tension_id")
            objectives = quest.get("objectives") or quest.get("required_state", [])
            routes = [action for action in tensions.get(tension_id, {}).get("suggested_actions", []) if action in affordance_ids]
            journal.append(
                {
                    "quest_id": quest["quest_id"],
                    "title": quest["title"],
                    "status": quest.get("status", "active"),
                    "source_tension_id": tension_id,
                    "tension_reason": tensions.get(tension_id, {}).get("reason", quest.get("reason", "")),
                    "objectives": objectives,
                    "known_clues": [item for item in self._known_clues(world_id) if tension_id and tension_id in str(item)],
                    "available_approaches": routes or tensions.get(tension_id, {}).get("suggested_actions", [])[:3],
                    "rewards": quest.get("rewards") or [quest.get("reward", {})],
                    "risks": [quest.get("failure_consequence", {})] if quest.get("failure_consequence") else quest.get("failure_consequences", []),
                    "evidence_refs": quest.get("evidence", []),
                }
            )
        return journal

    def tension_journal(self, world_id: str) -> list[dict[str, Any]]:
        affordance_ids = {item["action_id"] for item in self.service.affordances(world_id)}
        return [
            tension
            | {
                "foreground": index < 2,
                "available_actions": [action for action in tension.get("suggested_actions", []) if action in affordance_ids],
            }
            for index, tension in enumerate(self.service.tensions(world_id))
        ]

    def timeline(self, world_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.service.events(world_id)[-limit:]

    def _known_clues(self, world_id: str) -> list[dict[str, Any]]:
        return [
            {"id": item["id"], "owner_id": item["owner_id"], "truth_scope": item["truth_scope"], "text": item["memory_text"], "source_event_id": item["source_event_id"]}
            for item in self.service.memories(world_id)
            if item["truth_scope"] in {"player", "rumor"} or item["owner_id"] in {"player", "village"}
        ][:12]


def _bound_payload(bound: BoundAction | None) -> dict[str, Any] | None:
    if bound is None:
        return None
    return {"action_id": bound.action_id, "target_id": bound.target_id, "label": bound.label, "confidence": bound.confidence, "reason": bound.reason}


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
