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

    def play_state(self, world_id: str, mode: str = "roleplay") -> dict[str, Any]:
        self.service._require_world(world_id)
        return {
            "world": self.service.get_world(world_id),
            "scene": _scene_for_mode(SceneRenderer(self.service).render(world_id), mode),
            "affordances": self.play_affordances(world_id),
            "player": self.player_panel(world_id),
            "quests": self.quest_journal(world_id, mode),
            "tensions": self.tension_journal(world_id, mode),
            "relationships": self.relationship_panel(world_id),
            "foreground": self._foreground(world_id, mode),
            "timeline": self.timeline(world_id, limit=8, mode=mode),
        }

    def play_affordances(self, world_id: str) -> list[dict[str, Any]]:
        items = self.service.affordances(world_id)
        risk_order = {"low": 0, "medium": 1, "high": 2}
        return sorted(items, key=lambda item: (risk_order.get(item.get("risk", "low"), 9), item.get("label", "")))[:7]

    def play_turn(self, world_id: str, player_input: str, *, selected_action_id: str | None = None, selected_target_id: str | None = None, mode: str = "roleplay") -> dict[str, Any]:
        self.service._require_world(world_id)
        before = self.service.state(world_id)
        affordances = self.play_affordances(world_id)
        bound = self.binder.bind(player_input, affordances, selected_action_id=selected_action_id, selected_target_id=selected_target_id)
        if bound is None:
            turn_result = self._reject(world_id, player_input, affordances)
        else:
            turn_result = self._run_bound_turn(world_id, player_input, bound)
            if turn_result.get("accepted"):
                npc_activity = self._tick_foreground_npcs(world_id)
                turn_result["npc_activity"] = npc_activity
                turn_result["events"] = [*turn_result.get("events", []), *_npc_events(npc_activity)]
        after = self.service.state(world_id)
        feedback = self.feedback.render(turn_result, before, after) if turn_result.get("accepted") or turn_result.get("events") else turn_result["feedback"]
        feedback = _feedback_for_mode(feedback, mode)
        return {
            "turn": {key: turn_result[key] for key in ["turn_id", "turn_index", "accepted", "action_id", "reason"] if key in turn_result},
            "bound_action": _bound_payload(bound),
            "scene": _scene_for_mode(SceneRenderer(self.service).render(world_id), mode),
            "affordances": self.play_affordances(world_id),
            "feedback": feedback,
            "changes": feedback["changes"],
            "next_hooks": feedback["next_hooks"],
            "npc_activity": _npc_activity_summary(turn_result.get("npc_activity", {"results": []}), mode),
            "world_reactions": _world_reactions(turn_result.get("npc_activity", {"results": []})),
            "player": self.player_panel(world_id),
            "quests": self.quest_journal(world_id, mode),
            "tensions": self.tension_journal(world_id, mode),
            "relationships": self.relationship_panel(world_id),
        }

    def _run_bound_turn(self, world_id: str, player_input: str, bound: BoundAction) -> dict[str, Any]:
        command = player_input.strip() or bound.label
        return self.service.turn_bound(
            world_id,
            command,
            bound.action_id,
            bound.target_id,
            extractor="play_input_binder",
            confidence=bound.confidence,
        )

    def _tick_foreground_npcs(self, world_id: str) -> dict[str, Any]:
        npc_activity = self.service.tick_world(world_id, 3)
        if _npc_events(npc_activity) or not npc_activity.get("results"):
            return npc_activity
        first = npc_activity["results"][0]
        npc_id = first.get("npc_id")
        if not npc_id:
            return npc_activity
        with self.service._lock:
            with transaction(self.service.conn):
                log = EventLog(self.service.conn)
                turn_id = log.create_turn(world_id, f"foreground_npc_observe:{npc_id}", "Foreground NPC observes the player's move.")
                turn = self.service.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
                event = log.append(
                    world_id,
                    turn_id,
                    turn["turn_index"],
                    "NPC_ACTION",
                    npc_id,
                    {"action_id": "observe", "target_id": "player", "reason": first.get("reason") or "foreground_reaction"},
                    participants=[npc_id, "player"],
                    evidence_refs=[{"source_id": turn_id, "source_type": "foreground_npc_scheduler", "extractor": "foreground_npc_scheduler_v0", "confidence": 0.6}],
                )
        marker = {"id": event.id, "event_type": event.event_type, "payload": event.payload}
        updated = dict(first)
        updated.update({"acted": True, "action": {"action_id": "observe", "target_id": "player"}, "events": [marker]})
        return npc_activity | {"results": [updated, *npc_activity.get("results", [])[1:]]}

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
            "known_clues": [*_list_value(player.get("known_clues")), *self._known_clues(world_id)],
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

    def quest_journal(self, world_id: str, mode: str = "roleplay") -> list[dict[str, Any]]:
        tensions = {item["tension_id"]: item for item in self.service.tensions(world_id)}
        affordance_ids = {item["action_id"] for item in self.service.affordances(world_id)}
        journal = []
        for quest in self.service.quests(world_id):
            tension_id = quest.get("tension_id") or quest.get("source_tension_id")
            objectives = quest.get("objectives") or quest.get("required_state", [])
            routes = [action for action in tensions.get(tension_id, {}).get("suggested_actions", []) if action in affordance_ids]
            entry = {
                "quest_id": quest["quest_id"],
                "title": quest["title"],
                "status": quest.get("status", "active"),
                "source_tension_id": tension_id,
                "tension_reason": tensions.get(tension_id, {}).get("reason", quest.get("reason", "")),
                "objectives": _visible_objectives(objectives, mode),
                "known_clues": [item for item in self._known_clues(world_id) if tension_id and tension_id in str(item)],
                "available_approaches": routes or tensions.get(tension_id, {}).get("suggested_actions", [])[:3],
                "rewards": _public_list(quest.get("rewards") or [quest.get("reward", {})]),
                "risks": _public_list([quest.get("failure_consequence", {})] if quest.get("failure_consequence") else quest.get("failure_consequences", [])),
            }
            if mode == "dev":
                entry["evidence_refs"] = quest.get("evidence", [])
            journal.append(entry)
        return journal

    def tension_journal(self, world_id: str, mode: str = "roleplay") -> list[dict[str, Any]]:
        affordance_ids = {item["action_id"] for item in self.service.affordances(world_id)}
        result = []
        for index, tension in enumerate(self.service.tensions(world_id)):
            entry = {
                "tension_id": tension["tension_id"],
                "type": tension.get("type"),
                "reason": tension.get("reason"),
                "foreground": index < 2,
                "available_actions": [action for action in tension.get("suggested_actions", []) if action in affordance_ids],
            }
            if mode == "dev":
                entry.update(
                    {
                        "evidence": tension.get("evidence", []),
                        "affected_entities": tension.get("affected_entities", []),
                        "suggested_actions": tension.get("suggested_actions", []),
                    }
                )
            result.append(entry)
        return result

    def timeline(self, world_id: str, limit: int = 20, mode: str = "roleplay") -> list[dict[str, Any]]:
        events = self.service.events(world_id)[-limit:]
        if mode == "dev":
            return events
        return [_event_summary(event) for event in events]

    def _known_clues(self, world_id: str) -> list[dict[str, Any]]:
        return [
            {"text": item["memory_text"], "kind": "rumor" if item["truth_scope"] == "rumor" else "known"}
            for item in self.service.memories(world_id)
            if item["truth_scope"] in {"player", "rumor"} or item["owner_id"] in {"player", "village"}
        ][:12]

    def _foreground(self, world_id: str, mode: str) -> dict[str, Any]:
        foreground = self.service.drama_foreground(world_id)
        if mode == "dev":
            return foreground
        return {
            "foreground_tensions": [
                {"tension_id": item.get("tension_id") or item.get("id"), "type": item.get("type"), "reason": item.get("reason")}
                for item in foreground.get("foreground_tensions", [])
            ],
            "player_interest": foreground.get("player_interest", {}),
            "recommended_opportunity": foreground.get("recommended_opportunity"),
            "npc_should_approach_player": foreground.get("npc_should_approach_player"),
            "ambient_event": foreground.get("ambient_event"),
        }


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


def _visible_objectives(objectives: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    visible = []
    for objective in objectives:
        if mode != "dev" and objective.get("status") == "hidden":
            continue
        visible.append({key: value for key, value in objective.items() if mode == "dev" or key not in {"evidence", "hidden", "source_event_id"}})
    return visible


def _scene_for_mode(scene: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "dev":
        return scene
    return scene | {
        "foreground_tensions": [
            {"tension_id": item.get("tension_id") or item.get("id"), "type": item.get("type"), "reason": item.get("reason")}
            for item in scene.get("foreground_tensions", [])
        ]
    }


def _feedback_for_mode(feedback: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "dev":
        return feedback
    return _drop_private_keys(feedback)


def _drop_private_keys(value: Any) -> Any:
    private = {"truth_scope", "source_event_id", "evidence_refs", "payload", "scope_key", "raw"}
    if isinstance(value, dict):
        return {key: _drop_private_keys(item) for key, item in value.items() if key not in private}
    if isinstance(value, list):
        return [_drop_private_keys(item) for item in value]
    return value


def _public_list(items: list[Any]) -> list[Any]:
    return [item for item in items if item]


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})
    summary = {"turn_index": event.get("turn_index"), "type": event_type, "actor": event.get("actor_id") or "world"}
    if event_type == "MOVE_ENTITY":
        summary["text"] = f"{payload.get('entity_id')} moved to {payload.get('to')}."
    elif event_type == "TRANSFER_ITEM":
        summary["text"] = f"{payload.get('item_id')} changed hands."
    elif event_type == "CHANGE_RELATION":
        summary["text"] = f"{payload.get('src')} changed {payload.get('rel')} toward {payload.get('dst')}."
    elif event_type == "ADD_MEMORY":
        summary["text"] = "Someone learned or repeated something."
    elif event_type == "ACTION_REJECTED":
        summary["text"] = "An attempted action was blocked by the rules."
    elif event_type == "NPC_ACTION":
        summary["text"] = f"{event.get('actor_id')} acted in the foreground."
    else:
        summary["text"] = "The world state changed."
    return summary


def _npc_events(npc_activity: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for result in npc_activity.get("results", []):
        for event in result.get("events", []):
            events.append({"id": event.get("id"), "event_type": event.get("event_type"), "actor_id": result.get("npc_id"), "participants": [result.get("npc_id")], "payload": event.get("payload", {})})
    return events


def _npc_activity_summary(npc_activity: dict[str, Any], mode: str) -> dict[str, Any]:
    results = []
    for result in npc_activity.get("results", []):
        entry = {"npc_id": result.get("npc_id"), "acted": result.get("acted", False), "action": result.get("action", {}).get("action_id") if result.get("action") else None}
        if mode == "dev":
            entry["raw"] = result
        elif result.get("reason"):
            entry["reason"] = result["reason"]
        results.append(entry)
    return {"npc_count": npc_activity.get("npc_count", 0), "results": results}


def _world_reactions(npc_activity: dict[str, Any]) -> list[dict[str, Any]]:
    reactions = []
    for result in npc_activity.get("results", []):
        if result.get("acted"):
            action = result.get("action", {})
            reactions.append({"type": "npc_action", "npc_id": result.get("npc_id"), "action_id": action.get("action_id"), "target_id": action.get("target_id")})
    return reactions
