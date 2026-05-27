from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .db import from_json, to_json, utc_now
from .events import EventLog, EventRecord
from .projector import StateProjector, delta


@dataclass(frozen=True)
class ActionTemplate:
    action_id: str
    label: str
    target_id: str | None
    risk: str
    reason: str
    preconditions: list[dict[str, Any]]
    effects: list[dict[str, Any]]
    target_selector: dict[str, Any] = field(default_factory=dict)
    arg_schema: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResolution:
    action_id: str
    accepted: bool
    reason: str
    narration: str
    events: list[EventRecord]


class ActionTemplateStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, world_id: str, template: ActionTemplate) -> None:
        self.conn.execute(
            """
            INSERT INTO action_templates(
                id, world_id, action_id, label, target_id, target_selector_json, arg_schema_json, risk, reason,
                preconditions_json, effects_json, enabled, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(world_id, action_id) DO UPDATE SET
                label = excluded.label,
                target_id = excluded.target_id,
                target_selector_json = excluded.target_selector_json,
                arg_schema_json = excluded.arg_schema_json,
                risk = excluded.risk,
                reason = excluded.reason,
                preconditions_json = excluded.preconditions_json,
                effects_json = excluded.effects_json,
                enabled = 1
            """,
            (
                f"tmpl_{uuid4().hex}",
                world_id,
                template.action_id,
                template.label,
                template.target_id,
                to_json(template.target_selector),
                to_json(template.arg_schema),
                template.risk,
                template.reason,
                to_json(template.preconditions),
                to_json(template.effects),
                utc_now(),
            ),
        )

    def get(self, world_id: str, action_id: str) -> ActionTemplate | None:
        row = self.conn.execute(
            """
            SELECT * FROM action_templates
            WHERE world_id = ? AND action_id = ? AND enabled = 1
            """,
            (world_id, action_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_template(row)

    def list_enabled(self, world_id: str) -> list[ActionTemplate]:
        return [
            _row_to_template(row)
            for row in self.conn.execute(
                """
                SELECT * FROM action_templates
                WHERE world_id = ? AND enabled = 1
                ORDER BY action_id
                """,
                (world_id,),
            ).fetchall()
        ]


class PredicateEvaluator:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.state = StateProjector(conn)

    def evaluate(self, world_id: str, predicate: dict[str, Any], bindings: dict[str, str]) -> bool:
        kind = predicate["type"]
        if kind == "same_location":
            return self._state(world_id, predicate["a"], "location", bindings) == self._state(world_id, predicate["b"], "location", bindings)
        if kind == "has_item":
            return self._state(world_id, predicate["item"], "holder", bindings) == self._bind(predicate["actor"], bindings)
        if kind == "state_equals":
            return self._state(world_id, predicate["entity"], predicate["attr"], bindings, predicate.get("scope", "canonical")) == predicate["value"]
        if kind == "state_not_equals":
            return self._state(world_id, predicate["entity"], predicate["attr"], bindings, predicate.get("scope", "canonical")) != predicate["value"]
        if kind == "relation_at_least":
            value = self._state(world_id, predicate["entity"], predicate["attr"], bindings, predicate.get("scope", "canonical")) or 0
            return value >= predicate["value"]
        if kind == "resource_at_least":
            value = self._state(world_id, predicate["entity"], predicate["attr"], bindings, predicate.get("scope", "canonical")) or 0
            return value >= predicate["value"]
        if kind == "connected_location":
            actor = self._bind(predicate["actor"], bindings)
            target = self._bind(predicate["target"], bindings)
            if not target:
                return False
            current = self.state.get_state(world_id, actor, "location")
            return self._locations_connected(world_id, current, target)
        if kind == "edge_unblocked":
            actor = self._bind(predicate["actor"], bindings)
            target = self._bind(predicate["target"], bindings)
            current = self.state.get_state(world_id, actor, "location")
            return self._edge_unblocked(world_id, current, target)
        if kind == "scope_allowed":
            return predicate.get("scope", "canonical") in {"canonical", "player", "npc", "faction", "rumor", "candidate", "rejected"}
        raise ValueError(f"unknown predicate type: {kind}")

    def failure_reason(self, predicate: dict[str, Any]) -> str:
        return predicate.get("reason") or f"前置条件未满足: {predicate['type']}"

    def _state(self, world_id: str, entity: str, attr: str, bindings: dict[str, str], scope: str = "canonical") -> Any:
        return self.state.get_state(world_id, self._bind(entity, bindings), attr, scope)

    @staticmethod
    def _bind(value: str, bindings: dict[str, str]) -> str:
        if value.startswith("$"):
            return bindings.get(value[1:], "")
        return value

    def _locations_connected(self, world_id: str, current: str | None, target: str) -> bool:
        if current is None:
            return False
        row = self.conn.execute(
            """
            SELECT 1 FROM edges
            WHERE world_id = ?
              AND rel_type = 'CONNECTS'
              AND valid_to_turn IS NULL
              AND ((src_id = ? AND dst_id = ?) OR (src_id = ? AND dst_id = ?))
            """,
            (world_id, current, target, target, current),
        ).fetchone()
        return row is not None

    def _edge_unblocked(self, world_id: str, current: str | None, target: str) -> bool:
        if current is None or not target:
            return False
        row = self.conn.execute(
            """
            SELECT properties_json FROM edges
            WHERE world_id = ?
              AND rel_type = 'CONNECTS'
              AND valid_to_turn IS NULL
              AND ((src_id = ? AND dst_id = ?) OR (src_id = ? AND dst_id = ?))
            """,
            (world_id, current, target, target, current),
        ).fetchone()
        if row is None:
            return False
        properties = from_json(row["properties_json"], {})
        requirement = properties.get("requires_state") or properties.get("blocked_by")
        if not requirement:
            return True
        entity = requirement.get("entity")
        attr = requirement.get("attr")
        expected = requirement.get("value", requirement.get("required"))
        if not entity or not attr:
            return True
        return self.state.get_state(world_id, entity, attr, requirement.get("scope", "canonical")) == expected


class EffectExecutor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.state = StateProjector(conn)

    def execute(
        self,
        world_id: str,
        turn_id: str,
        turn_index: int,
        actor_id: str,
        effects: list[dict[str, Any]],
        bindings: dict[str, str],
        evidence: list[dict[str, Any]],
    ) -> list[EventRecord]:
        log = EventLog(self.conn)
        events: list[EventRecord] = []
        for effect in effects:
            event_type, payload, participants, deltas = self._build_effect(world_id, effect, bindings)
            event = log.append(
                world_id,
                turn_id,
                turn_index,
                event_type,
                actor_id if effect.get("actor") == "$actor" else effect.get("actor", actor_id),
                payload,
                participants=participants,
                state_deltas=deltas,
                evidence_refs=evidence,
            )
            self.state.apply_event(event)
            events.append(event)
        return events

    def _build_effect(
        self,
        world_id: str,
        effect: dict[str, Any],
        bindings: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[str], list[Any]]:
        kind = effect["type"]
        if kind == "transfer_item":
            item_id = self._bind(effect["item"], bindings)
            from_id = self._bind(effect["from"], bindings) if effect.get("from") else None
            to_id = self._bind(effect["to"], bindings)
            old = self.state.get_state(world_id, item_id, "holder")
            return "TRANSFER_ITEM", {"item_id": item_id, "from": from_id, "to": to_id}, [item_id, to_id], [delta(item_id, "holder", old, to_id)]
        if kind == "move_entity":
            entity_id = self._bind(effect["entity"], bindings)
            to_location = self._bind(effect["to"], bindings)
            old = self.state.get_state(world_id, entity_id, "location")
            return "MOVE_ENTITY", {"entity_id": entity_id, "from": old, "to": to_location}, [entity_id, to_location], [delta(entity_id, "location", old, to_location)]
        if kind == "change_relation":
            src = self._bind(effect["src"], bindings)
            dst = self._bind(effect["dst"], bindings)
            attr = effect.get("state_attr", f"{effect['rel'].lower()}.{dst}")
            old = self.state.get_state(world_id, src, attr) or 0
            amount = effect.get("delta", 0)
            new = old + amount
            return (
                "CHANGE_RELATION",
                {"src": src, "rel": effect["rel"], "dst": dst, "delta": amount, "value": new},
                [src, dst],
                [delta(src, attr, old, new, amount)],
            )
        if kind == "set_state":
            entity_id = self._bind(effect["entity"], bindings)
            attr = effect["attr"]
            scope = effect.get("scope", "canonical")
            old = self.state.get_state(world_id, entity_id, attr, scope)
            value = effect["value"]
            return "SET_STATE", {"entity_id": entity_id, "attr": attr, "value": value, "scope": scope}, [entity_id], [delta(entity_id, attr, old, value, scope=scope)]
        if kind == "grant_permission":
            entity_id = self._bind(effect.get("entity", "$actor"), bindings)
            scope = effect.get("scope", "canonical")
            old = self.state.get_state(world_id, entity_id, "permissions", scope) or []
            value = _append_unique(old, effect["permission"])
            return "SET_STATE", {"entity_id": entity_id, "attr": "permissions", "value": value, "scope": scope}, [entity_id], [delta(entity_id, "permissions", old, value, scope=scope)]
        if kind == "add_identity_tag":
            entity_id = self._bind(effect.get("entity", "$actor"), bindings)
            scope = effect.get("scope", "canonical")
            old = self.state.get_state(world_id, entity_id, "identity_tags", scope) or []
            value = _append_unique(old, effect["tag"])
            return "SET_STATE", {"entity_id": entity_id, "attr": "identity_tags", "value": value, "scope": scope}, [entity_id], [delta(entity_id, "identity_tags", old, value, scope=scope)]
        if kind == "add_knowledge":
            entity_id = self._bind(effect.get("entity", "$actor"), bindings)
            scope = effect.get("scope", "canonical")
            old = self.state.get_state(world_id, entity_id, "known_clues", scope) or []
            value = _append_unique(old, effect["clue"])
            return "SET_STATE", {"entity_id": entity_id, "attr": "known_clues", "value": value, "scope": scope}, [entity_id], [delta(entity_id, "known_clues", old, value, scope=scope)]
        if kind == "delta_resource":
            entity_id = self._bind(effect["entity"], bindings)
            attr = effect["attr"]
            amount = effect["delta"]
            scope = effect.get("scope", "canonical")
            old = self.state.get_state(world_id, entity_id, attr, scope) or 0
            return "DELTA_RESOURCE", {"entity_id": entity_id, "attr": attr, "delta": amount, "scope": scope}, [entity_id], [delta(entity_id, attr, old, old + amount, amount, scope)]
        if kind == "add_memory":
            owner_id = self._bind(effect["owner"], bindings)
            payload = {
                "owner_id": owner_id,
                "memory_text": effect["memory_text"],
                "truth_scope": effect.get("truth_scope", "npc"),
                "salience": effect.get("salience", 0.5),
                "valence": effect.get("valence", 0),
                "confidence": effect.get("confidence", 1.0),
            }
            return "ADD_MEMORY", payload, [owner_id], []
        if kind == "add_conversation_event":
            actor = self._bind(effect.get("actor", "$actor"), bindings)
            target = self._bind(effect.get("target", "$target"), bindings)
            topic = effect.get("topic", bindings.get("topic", ""))
            return "CONVERSATION_EVENT", {"actor": actor, "target": target, "topic": topic}, [actor, target], []
        raise ValueError(f"unknown effect type: {kind}")

    @staticmethod
    def _bind(value: str, bindings: dict[str, str]) -> str:
        if value.startswith("$"):
            return bindings.get(value[1:], "")
        return value


class ActionResolver:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.templates = ActionTemplateStore(conn)
        self.predicates = PredicateEvaluator(conn)
        self.effects = EffectExecutor(conn)

    def resolve(
        self,
        world_id: str,
        turn_id: str,
        turn_index: int,
        action_id: str,
        evidence: list[dict[str, Any]],
        actor_id: str = "player",
        target_id: str | None = None,
    ) -> ActionResolution | None:
        template = self.templates.get(world_id, action_id)
        if template is None:
            return None
        bindings = {"actor": actor_id, "target": target_id or template.target_id or ""}
        for predicate in template.preconditions:
            if not self.predicates.evaluate(world_id, predicate, bindings):
                reason = self.predicates.failure_reason(predicate)
                return ActionResolution(action_id, False, reason, reason, [])
        events = self.effects.execute(world_id, turn_id, turn_index, actor_id, template.effects, bindings, evidence)
        return ActionResolution(action_id, True, template.reason, template.reason, events)


class ActionTemplateEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.templates = ActionTemplateStore(conn)
        self.predicates = PredicateEvaluator(conn)

    def list_for_actor(self, world_id: str, actor_id: str = "player") -> list[dict[str, Any]]:
        bindings = {"actor": actor_id}
        affordances: list[dict[str, Any]] = []
        for template in self.templates.list_enabled(world_id):
            if template.action_id == "move_to_location":
                affordances.extend(self._movement_affordances(world_id, actor_id, template))
                continue
            if actor_id == "player" and template.action_id in {"patrol", "report_to_faction"}:
                continue
            if self._uses_target(template):
                affordances.extend(self._targeted_affordances(world_id, actor_id, template))
                continue
            if all(self.predicates.evaluate(world_id, item, bindings) for item in template.preconditions):
                affordances.append(
                    {
                        "action_id": template.action_id,
                        "label": template.label,
                        "target_id": template.target_id or "",
                        "risk": template.risk,
                        "reason": template.reason,
                    }
                )
        return affordances

    @staticmethod
    def _uses_target(template: ActionTemplate) -> bool:
        serialized = to_json({"preconditions": template.preconditions, "effects": template.effects, "target_id": template.target_id})
        return "$target" in serialized

    def _targeted_affordances(self, world_id: str, actor_id: str, template: ActionTemplate) -> list[dict[str, Any]]:
        current = self.predicates.state.get_state(world_id, actor_id, "location")
        if current is None:
            return []
        selector_type = template.target_selector.get("entity_type")
        target_rows = self.predicates.conn.execute(
            """
            SELECT n.id, n.name, n.entity_type
            FROM nodes n
            WHERE n.world_id = ?
              AND n.valid_to_turn IS NULL
              AND n.entity_type IN ('Character', 'Item', 'Location', 'Faction')
            ORDER BY n.entity_type, n.name
            """,
            (world_id,),
        ).fetchall()
        affordances: list[dict[str, Any]] = []
        for row in target_rows:
            target_id = row["id"]
            bindings = {"actor": actor_id, "target": target_id}
            if target_id == actor_id:
                continue
            if selector_type and row["entity_type"] != selector_type:
                continue
            if row["entity_type"] == "Location" and target_id == current and template.action_id == "inspect":
                label = template.label.replace("{target}", row["name"] or target_id)
                affordances.append({"action_id": template.action_id, "label": label, "target_id": target_id, "risk": template.risk, "reason": template.reason})
                continue
            if all(self.predicates.evaluate(world_id, item, bindings) for item in template.preconditions):
                label = template.label.replace("{target}", row["name"] or target_id)
                affordances.append(
                    {
                        "action_id": template.action_id,
                        "label": label,
                        "target_id": target_id,
                        "risk": template.risk,
                        "reason": template.reason,
                    }
                )
        return affordances

    def _movement_affordances(self, world_id: str, actor_id: str, template: ActionTemplate) -> list[dict[str, Any]]:
        current = self.predicates.state.get_state(world_id, actor_id, "location")
        if current is None:
            return []
        rows = self.predicates.conn.execute(
            """
            SELECT e.src_id, e.dst_id, n.name
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
            (current, world_id, current, current),
        ).fetchall()
        affordances: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            target_id = row["dst_id"] if row["src_id"] == current else row["src_id"]
            if target_id in seen:
                continue
            seen.add(target_id)
            bindings = {"actor": actor_id, "target": target_id}
            if all(self.predicates.evaluate(world_id, item, bindings) for item in template.preconditions):
                affordances.append(
                    {
                        "action_id": template.action_id,
                        "label": f"前往{row['name']}",
                        "target_id": target_id,
                        "risk": template.risk,
                        "reason": template.reason,
                    }
                )
        return affordances


def _row_to_template(row: sqlite3.Row) -> ActionTemplate:
    return ActionTemplate(
        action_id=row["action_id"],
        label=row["label"],
        target_id=row["target_id"],
        target_selector=from_json(row["target_selector_json"], {}),
        arg_schema=from_json(row["arg_schema_json"], {}),
        risk=row["risk"],
        reason=row["reason"],
        preconditions=from_json(row["preconditions_json"], []),
        effects=from_json(row["effects_json"], []),
    )


def _append_unique(value: Any, item: Any) -> list[Any]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    return [*items, item] if item not in items else items
