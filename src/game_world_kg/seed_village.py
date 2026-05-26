from __future__ import annotations

import sqlite3
from typing import Any

from .action_template import ActionTemplate, ActionTemplateStore
from .db import utc_now
from .events import EventLog
from .projector import StateProjector, delta


DEMO_VILLAGE_WORLD_ID = "demo_village"


def seed_village_world(conn: sqlite3.Connection, world_id: str = DEMO_VILLAGE_WORLD_ID) -> str:
    row = conn.execute("SELECT id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if row:
        seed_village_action_templates(conn, world_id)
        return world_id

    conn.execute(
        "INSERT INTO worlds(id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (world_id, "小村庄 Demo", "SQLite + Kuzu + Chroma 完整本地 Demo 的小村庄世界。", utc_now()),
    )
    log = EventLog(conn)
    turn_id = log.create_turn(world_id, "seed_village_world", "初始化小村庄 Demo。")
    projector = StateProjector(conn)

    for spec in _entity_specs():
        event = log.append(
            world_id,
            turn_id,
            0,
            "CREATE_ENTITY",
            "system",
            spec,
            participants=[spec["stable_key"]],
            evidence_refs=[_seed_evidence()],
        )
        projector.apply_event(event)

    for entity_id, attr, value, scope in _initial_states():
        event = log.append(
            world_id,
            turn_id,
            0,
            "SET_STATE",
            "system",
            {"entity_id": entity_id, "attr": attr, "value": value, "scope": scope},
            participants=[entity_id],
            state_deltas=[delta(entity_id, attr, None, value, scope=scope)],
            evidence_refs=[_seed_evidence()],
        )
        projector.apply_event(event)

    for entity_id, location_id in _initial_locations():
        event = log.append(
            world_id,
            turn_id,
            0,
            "MOVE_ENTITY",
            "system",
            {"entity_id": entity_id, "from": None, "to": location_id},
            participants=[entity_id, location_id],
            state_deltas=[delta(entity_id, "location", None, location_id)],
            evidence_refs=[_seed_evidence()],
        )
        projector.apply_event(event)

    for item_id, holder_id in _initial_holders():
        event = log.append(
            world_id,
            turn_id,
            0,
            "TRANSFER_ITEM",
            "system",
            {"item_id": item_id, "from": None, "to": holder_id},
            participants=[item_id, holder_id],
            state_deltas=[delta(item_id, "holder", None, holder_id)],
            evidence_refs=[_seed_evidence()],
        )
        projector.apply_event(event)

    for memory in _initial_memories():
        event = log.append(
            world_id,
            turn_id,
            0,
            "ADD_MEMORY",
            "system",
            memory,
            participants=[memory["owner_id"]],
            evidence_refs=[_seed_evidence()],
        )
        projector.apply_event(event)

    seed_village_action_templates(conn, world_id)
    return world_id


def seed_village_action_templates(conn: sqlite3.Connection, world_id: str = DEMO_VILLAGE_WORLD_ID) -> None:
    store = ActionTemplateStore(conn)
    for template in _action_templates():
        store.upsert(world_id, template)


def _entity_specs() -> list[dict[str, Any]]:
    locations = [
        ("village_gate", "村口", "outdoor_gate"),
        ("iron_gate", "铁门", "gate"),
        ("guard_room", "守卫室", "room"),
        ("village_square", "村广场", "square"),
        ("tavern", "酒馆", "building"),
        ("warehouse", "仓库", "building"),
        ("well", "井边", "landmark"),
        ("inner_city", "内城入口", "district_gate"),
        ("market_stall", "市集摊位", "market"),
    ]
    npcs = [
        ("player", "玩家", "player"),
        ("guard_alos", "守卫阿洛斯", "gate_guard"),
        ("tavern_keeper_mira", "酒馆老板米拉", "tavern_keeper"),
        ("merchant_borin", "商人伯林", "merchant"),
        ("village_chief", "村长", "chief"),
        ("suspicious_traveler", "可疑旅人", "traveler"),
        ("warehouse_keeper", "仓库管理员", "warehouse_keeper"),
    ]
    items = [
        ("pass_token", "通行令", "permit"),
        ("silver_key", "银钥匙", "key"),
        ("warehouse_key", "仓库钥匙", "key"),
        ("coin_pouch", "钱袋", "money"),
        ("grain_bag", "粮袋", "resource"),
        ("rumor_note", "传闻纸条", "note"),
        ("water_bucket", "水桶", "tool"),
        ("ledger_book", "仓库账本", "ledger"),
    ]
    factions = [
        ("gate_watch", "城门卫队", "watch"),
        ("village_council", "村议会", "council"),
        ("merchant_circle", "商人圈", "merchant_guild"),
        ("tavern_public", "酒馆人群", "public"),
    ]
    specs: list[dict[str, Any]] = []
    specs.extend({"stable_key": key, "entity_type": "Location", "name": name, "properties": {"loc_type": loc_type}} for key, name, loc_type in locations)
    specs.extend({"stable_key": key, "entity_type": "Character", "name": name, "properties": {"archetype": archetype}} for key, name, archetype in npcs)
    specs.extend({"stable_key": key, "entity_type": "Item", "name": name, "properties": {"item_type": item_type, "stackable": item_type == "resource"}} for key, name, item_type in items)
    specs.extend({"stable_key": key, "entity_type": "Faction", "name": name, "properties": {"faction_type": faction_type}} for key, name, faction_type in factions)
    return specs


def _initial_states() -> list[tuple[str, str, Any, str]]:
    return [
        ("iron_gate", "locked", True, "canonical"),
        ("iron_gate", "open", False, "canonical"),
        ("warehouse", "locked", True, "canonical"),
        ("warehouse", "grain_stock", 12, "canonical"),
        ("guard_alos", "trust.player", 3, "canonical"),
        ("guard_alos", "hostility.player", 0, "canonical"),
        ("village_chief", "trust.merchant_borin", 2, "canonical"),
        ("merchant_borin", "gold", 8, "canonical"),
        ("player", "gold", 3, "canonical"),
        ("player", "reputation", 0, "canonical"),
        ("silver_key", "theft_suspect.player", True, "rumor"),
    ]


def _initial_locations() -> list[tuple[str, str]]:
    return [
        ("player", "village_gate"),
        ("guard_alos", "village_gate"),
        ("tavern_keeper_mira", "tavern"),
        ("merchant_borin", "market_stall"),
        ("village_chief", "village_square"),
        ("suspicious_traveler", "tavern"),
        ("warehouse_keeper", "warehouse"),
    ]


def _initial_holders() -> list[tuple[str, str]]:
    return [
        ("pass_token", "player"),
        ("silver_key", "guard_alos"),
        ("warehouse_key", "warehouse_keeper"),
        ("coin_pouch", "player"),
        ("grain_bag", "warehouse"),
        ("rumor_note", "tavern"),
        ("water_bucket", "well"),
        ("ledger_book", "warehouse"),
    ]


def _initial_memories() -> list[dict[str, Any]]:
    return [
        {
            "owner_id": "tavern_public",
            "memory_text": "酒馆里有人传言玩家和银钥匙失窃有关。",
            "truth_scope": "rumor",
            "salience": 0.7,
            "valence": -0.4,
            "confidence": 0.6,
        },
        {
            "owner_id": "guard_alos",
            "memory_text": "银钥匙目前仍由阿洛斯随身保管。",
            "truth_scope": "npc",
            "salience": 0.8,
            "valence": 0.0,
            "confidence": 1.0,
        },
        {
            "owner_id": "village_council",
            "memory_text": "村议会担心商人伯林借粮食短缺抬价。",
            "truth_scope": "faction",
            "salience": 0.75,
            "valence": -0.2,
            "confidence": 0.8,
        },
    ]


def _action_templates() -> list[ActionTemplate]:
    return [
        _talk("talk_to_guard", "和守卫交谈", "guard_alos"),
        _talk("talk_to_mira", "和米拉交谈", "tavern_keeper_mira"),
        _talk("talk_to_borin", "和商人伯林交谈", "merchant_borin"),
        _talk("talk_to_chief", "和村长交谈", "village_chief"),
        _talk("talk_to_warehouse_keeper", "和仓库管理员交谈", "warehouse_keeper"),
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
                {"type": "add_memory", "owner": "guard_alos", "memory_text": "玩家主动出示了合法通行令。", "truth_scope": "npc", "salience": 0.8, "valence": 0.2, "actor": "system"},
            ],
        ),
        ActionTemplate(
            action_id="request_access",
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
            action_id="ask_about_rumor",
            label="询问银钥匙传闻",
            target_id="tavern_keeper_mira",
            risk="low",
            reason="米拉在酒馆，知道酒馆人群的传闻。",
            preconditions=[{"type": "same_location", "a": "$actor", "b": "tavern_keeper_mira", "reason": "米拉不在当前位置。"}],
            effects=[{"type": "add_memory", "owner": "$actor", "memory_text": "米拉说，银钥匙传闻最早来自一个可疑旅人。", "truth_scope": "player", "salience": 0.7, "actor": "system"}],
        ),
        ActionTemplate(
            action_id="inspect_warehouse",
            label="检查仓库门锁",
            target_id="warehouse",
            risk="low",
            reason="仓库仍上锁，可以检查门锁和封条。",
            preconditions=[{"type": "state_equals", "entity": "warehouse", "attr": "locked", "value": True, "reason": "仓库没有上锁。"}],
            effects=[{"type": "add_memory", "owner": "$actor", "memory_text": "仓库封条完好，但账本被放在门内侧的桌上。", "truth_scope": "player", "salience": 0.65, "actor": "system"}],
        ),
        ActionTemplate(
            action_id="request_warehouse_access",
            label="请求进入仓库",
            target_id="warehouse_keeper",
            risk="low",
            reason="仓库管理员掌握仓库钥匙。",
            preconditions=[{"type": "same_location", "a": "$actor", "b": "warehouse_keeper", "reason": "仓库管理员不在当前位置。"}],
            effects=[{"type": "add_memory", "owner": "warehouse_keeper", "memory_text": "玩家请求进入仓库调查粮食问题。", "truth_scope": "npc", "salience": 0.6, "actor": "system"}],
        ),
        ActionTemplate(
            action_id="trade_grain",
            label="协商粮食交易",
            target_id="merchant_borin",
            risk="medium",
            reason="商人伯林有足够金币，但村长尚未完全信任他。",
            preconditions=[{"type": "resource_at_least", "entity": "merchant_borin", "attr": "gold", "value": 5, "reason": "商人伯林资金不足。"}],
            effects=[{"type": "add_memory", "owner": "merchant_borin", "memory_text": "玩家愿意协助调查仓库粮食交易。", "truth_scope": "npc", "salience": 0.55, "actor": "system"}],
        ),
    ]


def _talk(action_id: str, label: str, npc_id: str) -> ActionTemplate:
    return ActionTemplate(
        action_id=action_id,
        label=label,
        target_id=npc_id,
        risk="low",
        reason="目标 NPC 位于当前地点。",
        preconditions=[{"type": "same_location", "a": "$actor", "b": npc_id, "reason": "目标 NPC 不在当前位置。"}],
        effects=[],
    )


def _seed_evidence() -> dict[str, Any]:
    return {"source_id": "seed_village_world", "span": [0, 0], "extractor": "seed_village_v1", "confidence": 1.0}
