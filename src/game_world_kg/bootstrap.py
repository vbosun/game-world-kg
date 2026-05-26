from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .action_template import ActionTemplate, ActionTemplateStore
from .db import from_json, to_json, utc_now
from .events import EventLog, EventRecord
from .projector import StateProjector, delta
from .worldspec import WorldSpec, WorldSpecValidator


@dataclass(frozen=True)
class BootstrapResult:
    world_id: str
    world_spec_id: str
    spec_hash: str
    bootstrap_run_id: str
    idempotent: bool
    event_ids: list[str]
    validation_report: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "world_spec_id": self.world_spec_id,
            "spec_hash": self.spec_hash,
            "bootstrap_run_id": self.bootstrap_run_id,
            "idempotent": self.idempotent,
            "event_ids": self.event_ids,
            "validation_report": self.validation_report,
        }


class WorldSpecRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, spec: WorldSpec, status: str, validation_report: dict[str, Any]) -> str:
        spec_hash = spec.spec_hash()
        existing = self.conn.execute(
            "SELECT id FROM world_specs WHERE world_id = ? AND spec_hash = ?",
            (spec.world_id, spec_hash),
        ).fetchone()
        if existing is not None:
            self.conn.execute(
                "UPDATE world_specs SET status = ?, validation_report_json = ? WHERE id = ?",
                (status, to_json(validation_report), existing["id"]),
            )
            return existing["id"]
        spec_id = f"wspec_{uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO world_specs(id, world_id, spec_json, spec_hash, status, validation_report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (spec_id, spec.world_id, spec.canonical_json(), spec_hash, status, to_json(validation_report), utc_now()),
        )
        return spec_id

    def latest(self, world_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM world_specs WHERE world_id = ? ORDER BY created_at DESC LIMIT 1",
            (world_id,),
        ).fetchone()
        if row is None:
            return None
        return _world_spec_row(row)


class BootstrapCompiler:
    def compile(self, spec: WorldSpec) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [
            {
                "event_type": "WORLD_CREATED",
                "actor_id": "system",
                "payload": {
                    "world_id": spec.world_id,
                    "title": spec.title,
                    "genre": spec.genre,
                    "theme": spec.theme,
                    "scale": spec.scale,
                    "spec_hash": spec.spec_hash(),
                },
                "participants": [spec.world_id],
            }
        ]
        for faction in spec.factions:
            events.append(
                {
                    "event_type": "CREATE_FACTION",
                    "actor_id": "system",
                    "payload": {
                        "stable_key": faction.stable_key,
                        "entity_type": "Faction",
                        "name": faction.name,
                        "properties": faction.model_dump(mode="json"),
                    },
                    "participants": [faction.id],
                }
            )
        for location in spec.locations:
            events.append(
                {
                    "event_type": "CREATE_LOCATION",
                    "actor_id": "system",
                    "payload": {
                        "stable_key": location.stable_key,
                        "entity_type": "Location",
                        "name": location.name,
                        "properties": location.model_dump(mode="json"),
                    },
                    "participants": [location.id],
                }
            )
        seen_edges: set[tuple[str, str]] = set()
        for location in spec.locations:
            for target in location.connects_to:
                key = tuple(sorted([location.id, target]))
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                events.append({"event_type": "CONNECT_LOCATION", "actor_id": "system", "payload": {"from": location.id, "to": target}, "participants": [location.id, target]})
        events.append(
            {
                "event_type": "CREATE_CHARACTER",
                "actor_id": "system",
                "payload": {
                    "stable_key": "player",
                    "entity_type": "Character",
                    "name": "玩家",
                    "properties": {"id": "player", "role": "player", "start_location": spec.player_start.location_id},
                },
                "participants": ["player"],
            }
        )
        for character in spec.characters:
            events.append(
                {
                    "event_type": "CREATE_CHARACTER",
                    "actor_id": "system",
                    "payload": {
                        "stable_key": character.stable_key,
                        "entity_type": "Character",
                        "name": character.name,
                        "properties": character.model_dump(mode="json"),
                    },
                    "participants": [character.id],
                }
            )
        for item in spec.items:
            events.append(
                {
                    "event_type": "CREATE_ITEM",
                    "actor_id": "system",
                    "payload": {
                        "stable_key": item.stable_key,
                        "entity_type": "Item",
                        "name": item.name,
                        "properties": item.model_dump(mode="json"),
                    },
                    "participants": [item.id],
                }
            )
        for rule in spec.rules:
            events.append({"event_type": "CREATE_RULE", "actor_id": "system", "payload": rule, "participants": [rule.get("rule_id", "rule")]})
        for template in spec.action_templates:
            events.append({"event_type": "CREATE_ACTION_TEMPLATE", "actor_id": "system", "payload": template.model_dump(mode="json"), "participants": [template.action_id]})
        for state in spec.initial_states:
            events.append(
                {
                    "event_type": "SET_STATE",
                    "actor_id": "system",
                    "payload": {"entity_id": state.entity, "attr": state.attr, "value": state.value, "scope": state.scope},
                    "participants": [state.entity],
                    "state_delta": delta(state.entity, state.attr, None, state.value, scope=state.scope),
                }
            )
        for character in spec.characters:
            events.append(
                {
                    "event_type": "MOVE_ENTITY",
                    "actor_id": "system",
                    "payload": {"entity_id": character.id, "from": None, "to": character.start_location},
                    "participants": [character.id, character.start_location],
                    "state_delta": delta(character.id, "location", None, character.start_location),
                }
            )
        for item in spec.items:
            if item.owner_id:
                events.append(
                    {
                        "event_type": "TRANSFER_ITEM",
                        "actor_id": "system",
                        "payload": {"item_id": item.id, "from": None, "to": item.owner_id},
                        "participants": [item.id, item.owner_id],
                        "state_delta": delta(item.id, "holder", None, item.owner_id),
                    }
                )
            if item.location_id:
                events.append(
                    {
                        "event_type": "MOVE_ENTITY",
                        "actor_id": "system",
                        "payload": {"entity_id": item.id, "from": None, "to": item.location_id},
                        "participants": [item.id, item.location_id],
                        "state_delta": delta(item.id, "location", None, item.location_id),
                    }
                )
        for faction in spec.factions:
            for relation in faction.relations:
                events.append(
                    {
                        "event_type": "CHANGE_RELATION",
                        "actor_id": "system",
                        "payload": {"src": faction.id, "rel": relation.relation.upper(), "dst": relation.target, "value": relation.value},
                        "participants": [faction.id, relation.target],
                        "state_delta": delta(faction.id, f"{relation.relation}.{relation.target}", None, relation.value),
                    }
                )
        for memory in spec.initial_memories:
            events.append({"event_type": "ADD_MEMORY", "actor_id": "system", "payload": memory.model_dump(mode="json"), "participants": [memory.owner_id]})
        for tension in spec.initial_tensions:
            events.append({"event_type": "ADD_TENSION", "actor_id": "system", "payload": tension.model_dump(mode="json"), "participants": [tension.id, *tension.affected_entities]})
        for quest in spec.initial_quests:
            events.append({"event_type": "START_QUEST", "actor_id": "system", "payload": quest.model_dump(mode="json"), "participants": [quest.id, quest.issuer_id, quest.tension_id]})
        events.append({"event_type": "WORLD_BOOTSTRAP_COMPLETED", "actor_id": "system", "payload": {"world_id": spec.world_id, "spec_hash": spec.spec_hash()}, "participants": [spec.world_id]})
        return events


class WorldBootstrapper:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def bootstrap(self, spec: WorldSpec, world_spec_id: str | None = None) -> BootstrapResult:
        report = WorldSpecValidator().validate(spec)
        if not report["valid"]:
            raise ValueError(to_json(report))
        repo = WorldSpecRepository(self.conn)
        world_spec_id = world_spec_id or repo.save(spec, "validated", report)
        spec_hash = spec.spec_hash()
        existing = self.conn.execute(
            "SELECT * FROM bootstrap_runs WHERE world_id = ? AND spec_hash = ? AND status = 'completed'",
            (spec.world_id, spec_hash),
        ).fetchone()
        if existing is not None:
            return BootstrapResult(spec.world_id, world_spec_id, spec_hash, existing["id"], True, from_json(existing["event_ids_json"], []), report)

        self.conn.execute(
            """
            INSERT INTO worlds(id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name, description = excluded.description
            """,
            (spec.world_id, spec.title, spec.theme, utc_now()),
        )
        run_id = f"boot_{uuid4().hex}"
        log = EventLog(self.conn)
        projector = StateProjector(self.conn)
        action_store = ActionTemplateStore(self.conn)
        event_ids: list[str] = []
        for draft in BootstrapCompiler().compile(spec):
            state_delta = draft.get("state_delta")
            event = log.append(
                spec.world_id,
                None,
                0,
                draft["event_type"],
                draft.get("actor_id"),
                draft["payload"],
                participants=draft.get("participants", []),
                state_deltas=[state_delta] if state_delta is not None else [],
                evidence_refs=[{"source_id": world_spec_id, "source_type": "world_spec", "extractor": "bootstrap_compiler_v1", "confidence": 1.0}],
            )
            _apply_bootstrap_side_effect(projector, action_store, event)
            event_ids.append(event.id)
        self.conn.execute(
            """
            INSERT INTO bootstrap_runs(id, world_id, world_spec_id, spec_hash, status, event_ids_json, created_at)
            VALUES (?, ?, ?, ?, 'completed', ?, ?)
            """,
            (run_id, spec.world_id, world_spec_id, spec_hash, to_json(event_ids), utc_now()),
        )
        return BootstrapResult(spec.world_id, world_spec_id, spec_hash, run_id, False, event_ids, report)


def _apply_bootstrap_side_effect(projector: StateProjector, action_store: ActionTemplateStore, event: EventRecord) -> None:
    if event.event_type == "CREATE_ACTION_TEMPLATE":
        payload = event.payload
        action_store.upsert(
            event.world_id,
            ActionTemplate(
                action_id=payload["action_id"],
                label=payload["label_template"],
                target_id=None,
                risk=payload.get("risk", "low"),
                reason=payload.get("reason", ""),
                preconditions=payload.get("preconditions", []),
                effects=payload.get("effects", []),
                target_selector=payload.get("target_selector", {}),
                arg_schema=payload.get("arg_schema", {}),
            ),
        )
    projector.apply_event(event)


def _world_spec_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "world_id": row["world_id"],
        "spec": from_json(row["spec_json"], {}),
        "spec_hash": row["spec_hash"],
        "status": row["status"],
        "validation_report": from_json(row["validation_report_json"], {}),
        "created_at": row["created_at"],
    }
