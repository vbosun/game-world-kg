from __future__ import annotations

import sqlite3
from typing import Any

from .action_template import ActionTemplate, ActionTemplateStore
from .db import utc_now
from .events import EventLog
from .projector import StateProjector, delta


DEMO_WORLD_ID = "demo_gate"


def seed_demo_world(conn: sqlite3.Connection, world_id: str = DEMO_WORLD_ID) -> str:
    row = conn.execute("SELECT id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if row:
        seed_action_templates(conn, world_id)
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

    seed_action_templates(conn, world_id)

    return world_id


def seed_action_templates(conn: sqlite3.Connection, world_id: str = DEMO_WORLD_ID) -> None:
    store = ActionTemplateStore(conn)
    for template in _action_templates():
        store.upsert(world_id, template)


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


def _action_templates() -> list[ActionTemplate]:
    return [
        ActionTemplate(
            action_id="talk_to_guard",
            label="和守卫交谈",
            target_id="guard_alos",
            risk="low",
            reason="守卫位于当前地点",
            preconditions=[{"type": "same_location", "a": "$actor", "b": "guard_alos", "reason": "守卫不在当前位置，不能交谈。"}],
            effects=[],
        ),
        ActionTemplate(
            action_id="show_pass_token",
            label="向守卫出示通行令",
            target_id="guard_alos",
            risk="low",
            reason="玩家持有通行令且守卫在场。",
            preconditions=[
                {"type": "same_location", "a": "$actor", "b": "guard_alos", "reason": "守卫不在当前位置，不能出示通行令。"},
                {"type": "has_item", "actor": "$actor", "item": "pass_token", "reason": "玩家没有通行令，规则拒绝该行动。"},
            ],
            effects=[
                {"type": "transfer_item", "item": "pass_token", "from": "$actor", "to": "guard_alos", "actor": "$actor"},
                {"type": "change_relation", "src": "guard_alos", "rel": "TRUSTS", "dst": "$actor", "state_attr": "trust.player", "delta": 2, "actor": "system"},
                {
                    "type": "add_memory",
                    "owner": "guard_alos",
                    "memory_text": "玩家主动出示了合法通行令。",
                    "truth_scope": "npc",
                    "salience": 0.8,
                    "valence": 0.2,
                    "actor": "system",
                },
            ],
        ),
        ActionTemplate(
            action_id="ask_guard_open_gate",
            label="请求守卫放行",
            target_id="guard_alos",
            risk="low",
            reason="守卫信任达到 5。",
            preconditions=[
                {"type": "relation_at_least", "entity": "guard_alos", "attr": "trust.player", "value": 5, "reason": "守卫信任不足 5，不会主动放行。"},
                {"type": "state_not_equals", "entity": "iron_gate", "attr": "open", "value": True, "reason": "铁门已经打开。"},
            ],
            effects=[
                {"type": "set_state", "entity": "iron_gate", "attr": "locked", "value": False, "actor": "guard_alos"},
                {"type": "set_state", "entity": "iron_gate", "attr": "open", "value": True, "actor": "guard_alos"},
            ],
        ),
        ActionTemplate(
            action_id="unlock_gate_with_key",
            label="用银钥匙打开铁门",
            target_id="iron_gate",
            risk="low",
            reason="玩家持有银钥匙。",
            preconditions=[
                {"type": "has_item", "actor": "$actor", "item": "silver_key", "reason": "玩家没有银钥匙，不能用钥匙打开铁门。"},
                {"type": "state_not_equals", "entity": "iron_gate", "attr": "open", "value": True, "reason": "铁门已经打开。"},
            ],
            effects=[
                {"type": "set_state", "entity": "iron_gate", "attr": "locked", "value": False, "actor": "$actor"},
                {"type": "set_state", "entity": "iron_gate", "attr": "open", "value": True, "actor": "$actor"},
            ],
        ),
        ActionTemplate(
            action_id="bribe_guard",
            label="贿赂守卫",
            target_id="guard_alos",
            risk="medium",
            reason="玩家有钱袋且守卫在场。",
            preconditions=[
                {"type": "same_location", "a": "$actor", "b": "guard_alos", "reason": "守卫不在当前位置，不能贿赂。"},
                {"type": "resource_at_least", "entity": "$actor", "attr": "gold", "value": 1, "reason": "玩家没有钱袋，不能贿赂。"},
            ],
            effects=[
                {"type": "delta_resource", "entity": "$actor", "attr": "gold", "delta": -1, "actor": "$actor"},
                {"type": "delta_resource", "entity": "$actor", "attr": "reputation", "delta": -1, "actor": "system"},
                {"type": "change_relation", "src": "guard_alos", "rel": "TRUSTS", "dst": "$actor", "state_attr": "trust.player", "delta": 1, "actor": "system"},
            ],
        ),
        ActionTemplate(
            action_id="steal_silver_key",
            label="偷取银钥匙",
            target_id="guard_alos",
            risk="high",
            reason="MVP 固定结算：偷钥匙失败并触发敌意。",
            preconditions=[{"type": "same_location", "a": "$actor", "b": "guard_alos", "reason": "守卫不在当前位置，不能偷钥匙。"}],
            effects=[
                {"type": "change_relation", "src": "guard_alos", "rel": "OPPOSES", "dst": "$actor", "state_attr": "hostility.player", "delta": 2, "actor": "system"},
                {
                    "type": "add_memory",
                    "owner": "guard_alos",
                    "memory_text": "玩家试图偷取银钥匙。",
                    "truth_scope": "npc",
                    "salience": 0.9,
                    "valence": -0.8,
                    "actor": "system",
                },
            ],
            cost_effects=[
                {"type": "delta_resource", "entity": "$actor", "attr": "gold", "delta": -1, "actor": "system"},
            ],
            fail_effects=[
                {
                    "type": "add_memory",
                    "owner": "guard_alos",
                    "memory_text": "玩家在附近行迹可疑，试图摸我的钥匙。",
                    "truth_scope": "npc",
                    "salience": 0.7,
                    "valence": -0.5,
                    "actor": "system",
                },
            ],
            catastrophic_effects=[
                {"type": "change_relation", "src": "guard_alos", "rel": "OPPOSES", "dst": "$actor", "state_attr": "hostility.player", "delta": 5, "actor": "system"},
                {"type": "delta_resource", "entity": "$actor", "attr": "gold", "delta": -3, "actor": "system"},
                {
                    "type": "add_memory",
                    "owner": "guard_alos",
                    "memory_text": "玩家公然试图偷取银钥匙，完全不可信！",
                    "truth_scope": "npc",
                    "salience": 1.0,
                    "valence": -1.0,
                    "actor": "system",
                },
                {
                    "type": "add_memory",
                    "owner": "$actor",
                    "memory_text": "偷钥匙被守卫当场抓获，名声扫地。",
                    "truth_scope": "player",
                    "salience": 1.0,
                    "valence": -1.0,
                    "actor": "system",
                },
            ],
        ),
        ActionTemplate(
            action_id="enter_inner_city",
            label="进入内城",
            target_id="inner_city",
            risk="low",
            reason="铁门已经打开",
            preconditions=[
                {"type": "state_equals", "entity": "iron_gate", "attr": "open", "value": True, "reason": "铁门尚未打开，不能进入内城。"},
                {"type": "state_equals", "entity": "$actor", "attr": "location", "value": "village_gate", "reason": "玩家不在村口。"},
            ],
            effects=[{"type": "move_entity", "entity": "$actor", "to": "inner_city", "actor": "$actor"}],
        ),
    ]
