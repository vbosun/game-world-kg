from __future__ import annotations

import sqlite3
from typing import Any

from .db import utc_now
from .events import EventLog
from .projector import StateProjector, delta


DEMO_WORLD_ID = "demo_gate"


def seed_demo_world(conn: sqlite3.Connection, world_id: str = DEMO_WORLD_ID) -> str:
    row = conn.execute("SELECT id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if row:
        return world_id

    conn.execute(
        "INSERT INTO worlds(id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (world_id, "城门 Demo", "用于验证事件日志、状态投影、规则、记忆和 affordance 的极简城门场景。", utc_now()),
    )
    log = EventLog(conn)
    turn_id = log.create_turn(world_id, "seed_demo_world", "初始化城门 Demo。")
    turn_index = 0
    projector = StateProjector(conn)

    for spec in _entity_specs():
        event = log.append(
            world_id,
            turn_id,
            turn_index,
            "CREATE_ENTITY",
            "system",
            spec,
            participants=[spec["stable_key"]],
            evidence_refs=[{"source_id": "seed_demo_world", "span": [0, 0], "extractor": "seed_v1", "confidence": 1.0}],
        )
        projector.apply_event(event)

    for entity_id, attr, value in _initial_states():
        event = log.append(
            world_id,
            turn_id,
            turn_index,
            "SET_STATE",
            "system",
            {"entity_id": entity_id, "attr": attr, "value": value},
            participants=[entity_id],
            state_deltas=[delta(entity_id, attr, None, value)],
            evidence_refs=[{"source_id": "seed_demo_world", "span": [0, 0], "extractor": "seed_v1", "confidence": 1.0}],
        )
        projector.apply_event(event)

    for entity_id, location_id in [("player", "village_gate"), ("guard_alos", "village_gate"), ("mayor", "inner_city")]:
        event = log.append(
            world_id,
            turn_id,
            turn_index,
            "MOVE_ENTITY",
            "system",
            {"entity_id": entity_id, "from": None, "to": location_id},
            participants=[entity_id, location_id],
            state_deltas=[delta(entity_id, "location", None, location_id)],
            evidence_refs=[{"source_id": "seed_demo_world", "span": [0, 0], "extractor": "seed_v1", "confidence": 1.0}],
        )
        projector.apply_event(event)

    for item_id, holder_id in [("pass_token", "player"), ("coin_purse", "player"), ("silver_key", "guard_alos")]:
        event = log.append(
            world_id,
            turn_id,
            turn_index,
            "TRANSFER_ITEM",
            "system",
            {"item_id": item_id, "from": None, "to": holder_id},
            participants=[item_id, holder_id],
            state_deltas=[delta(item_id, "holder", None, holder_id)],
            evidence_refs=[{"source_id": "seed_demo_world", "span": [0, 0], "extractor": "seed_v1", "confidence": 1.0}],
        )
        projector.apply_event(event)

    return world_id


def _entity_specs() -> list[dict[str, Any]]:
    return [
        {"stable_key": "village_gate", "entity_type": "Location", "name": "村口", "properties": {"loc_type": "outdoor_gate"}},
        {"stable_key": "iron_gate", "entity_type": "Location", "name": "铁门", "properties": {"loc_type": "gate"}},
        {"stable_key": "guard_room", "entity_type": "Location", "name": "守卫室", "properties": {"loc_type": "room"}},
        {"stable_key": "inner_city", "entity_type": "Location", "name": "内城", "properties": {"loc_type": "district"}},
        {"stable_key": "player", "entity_type": "Character", "name": "玩家", "properties": {"archetype": "player"}},
        {"stable_key": "guard_alos", "entity_type": "Character", "name": "守卫阿洛斯", "properties": {"archetype": "gate_guard"}},
        {"stable_key": "mayor", "entity_type": "Character", "name": "村长", "properties": {"archetype": "village_mayor"}},
        {"stable_key": "pass_token", "entity_type": "Item", "name": "通行令", "properties": {"item_type": "permit", "stackable": False}},
        {"stable_key": "silver_key", "entity_type": "Item", "name": "银钥匙", "properties": {"item_type": "key", "stackable": False}},
        {"stable_key": "coin_purse", "entity_type": "Item", "name": "钱袋", "properties": {"item_type": "money", "stackable": False}},
        {"stable_key": "gate_access", "entity_type": "Rule", "name": "城门通行规则", "properties": {"rule_type": "access_control", "enabled": True}},
    ]


def _initial_states() -> list[tuple[str, str, Any]]:
    return [
        ("iron_gate", "locked", True),
        ("iron_gate", "open", False),
        ("guard_alos", "trust.player", 3),
        ("guard_alos", "hostility.player", 0),
        ("player", "gold", 3),
        ("player", "reputation", 0),
    ]
