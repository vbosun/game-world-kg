from __future__ import annotations

import sqlite3
from typing import Any

from .action_template import ActionTemplate, ActionTemplateStore
from .db import utc_now
from .events import EventLog
from .projector import StateProjector, delta


QINGXI_WORLD_ID = "qingxi_town"


def seed_qingxi_world(conn: sqlite3.Connection, world_id: str = QINGXI_WORLD_ID) -> str:
    row = conn.execute("SELECT id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if row:
        seed_qingxi_action_templates(conn, world_id)
        return world_id

    conn.execute(
        "INSERT INTO worlds(id, name, description, runtime_mode, created_at) VALUES (?, ?, ?, 'template_only', ?)",
        (world_id, "青溪镇", "Beta 3 可玩层 30 分钟 vertical slice：药荒、外役招募与夜庙白影。", utc_now()),
    )
    log = EventLog(conn)
    turn_id = log.create_turn(world_id, "seed_qingxi_world", "初始化青溪镇可玩样板。")
    projector = StateProjector(conn)

    for spec in _entity_specs():
        event = log.append(world_id, turn_id, 0, "CREATE_ENTITY", "system", spec, participants=[spec["stable_key"]], evidence_refs=[_seed_evidence()])
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

    for src, dst, properties in _location_connections():
        event = log.append(
            world_id,
            turn_id,
            0,
            "CONNECT_LOCATION",
            "system",
            {"from": src, "to": dst, "properties": properties},
            participants=[src, dst],
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
        event = log.append(world_id, turn_id, 0, "ADD_MEMORY", "system", memory, participants=[memory["owner_id"]], evidence_refs=[_seed_evidence()])
        projector.apply_event(event)

    for tension in _initial_tensions():
        event = log.append(world_id, turn_id, 0, "ADD_TENSION", "system", tension, participants=tension["affected_entities"], evidence_refs=[_seed_evidence()])
        projector.apply_event(event)

    for quest in _initial_quests():
        event = log.append(world_id, turn_id, 0, "START_QUEST", "system", quest, participants=[quest["issuer_id"], quest["tension_id"]], evidence_refs=[_seed_evidence()])
        projector.apply_event(event)

    seed_qingxi_action_templates(conn, world_id)
    return world_id


def seed_qingxi_action_templates(conn: sqlite3.Connection, world_id: str = QINGXI_WORLD_ID) -> None:
    store = ActionTemplateStore(conn)
    for template in _action_templates():
        store.upsert(world_id, template)


def _entity_specs() -> list[dict[str, Any]]:
    locations = [
        ("ferry_bridge", "镇口渡桥", "crossroad"),
        ("tea_stall", "茶棚", "social_hub"),
        ("herb_shop", "药铺", "workshop"),
        ("county_warehouse", "县仓", "storehouse"),
        ("ruined_temple", "破庙", "danger_site"),
        ("spirit_field", "后山灵田", "resource_site"),
        ("mountain_gate_road", "山门外驿道", "faction_gate"),
    ]
    npcs = [
        ("player", "玩家", "refugee_worker"),
        ("sun_niang", "药婆孙娘", "healer"),
        ("jiao_qi", "焦七", "tea_gossip"),
        ("song_heng", "宋衡", "warehouse_clerk"),
        ("lin_yan", "林砚", "outer_sect_scout"),
        ("lu_san", "鲁三", "local_bully"),
        ("xiao_ni", "小妮", "temple_witness"),
        ("han_shu", "韩叔", "mountain_guide"),
        ("gu_hui", "顾回", "talisman_scholar"),
    ]
    items = [
        ("basic_food", "干粮", "resource"),
        ("herb_bundle", "药草包", "resource"),
        ("trial_token", "外役试工牌", "permit"),
        ("temple_ash", "破庙灰痕", "evidence"),
        ("old_bow", "旧弓", "tool"),
        ("warehouse_page", "县仓账页", "evidence"),
        ("fire_talisman", "火符", "tool"),
        ("tea_debt_note", "茶棚欠条", "debt"),
    ]
    factions = [
        ("herb_shop_faction", "药铺线", "local_trade"),
        ("outer_sect", "青木宗外门", "sect"),
        ("lu_san_crew", "鲁三脚夫", "gang"),
        ("town_public", "青溪镇众", "public"),
    ]
    specs: list[dict[str, Any]] = []
    specs.extend({"stable_key": key, "entity_type": "Location", "name": name, "properties": {"loc_type": loc_type}} for key, name, loc_type in locations)
    specs.extend({"stable_key": key, "entity_type": "Character", "name": name, "properties": {"archetype": archetype, "goals": _goals_for(key)}} for key, name, archetype in npcs)
    specs.extend({"stable_key": key, "entity_type": "Item", "name": name, "properties": {"item_type": item_type, "stackable": item_type == "resource"}} for key, name, item_type in items)
    specs.extend({"stable_key": key, "entity_type": "Faction", "name": name, "properties": {"faction_type": faction_type}} for key, name, faction_type in factions)
    return specs


def _goals_for(npc_id: str) -> list[dict[str, Any]]:
    goals = {
        "sun_niang": [{"goal_id": "restore_herb_supply", "priority": 0.9, "risk_tolerance": 0.2}],
        "jiao_qi": [{"goal_id": "spread_news", "priority": 0.7, "risk_tolerance": 0.4}],
        "lin_yan": [{"goal_id": "recruit_reliable_worker", "priority": 0.85, "risk_tolerance": 0.3}],
        "lu_san": [{"goal_id": "protect_night_route", "priority": 0.8, "risk_tolerance": 0.7}],
        "xiao_ni": [{"goal_id": "hide_temple_truth", "priority": 0.75, "risk_tolerance": 0.2}],
    }
    return goals.get(npc_id, [{"goal_id": "stay_informed", "priority": 0.5, "risk_tolerance": 0.3}])


def _initial_states() -> list[tuple[str, str, Any, str]]:
    return [
        ("player", "identity_tags", ["refugee_worker"], "canonical"),
        ("player", "permissions", [], "canonical"),
        ("player", "gold", 1, "canonical"),
        ("player", "food", 2, "canonical"),
        ("player", "stamina", 5, "canonical"),
        ("player", "skill.labor", 1, "canonical"),
        ("player", "known_clues", [], "canonical"),
        ("sun_niang", "trust.player", 1, "canonical"),
        ("jiao_qi", "trust.player", 1, "canonical"),
        ("lin_yan", "respect.player", 0, "canonical"),
        ("lu_san", "suspicion.player", 1, "canonical"),
        ("outer_sect", "reputation.player", 0, "canonical"),
        ("herb_shop", "herb_stock", "low", "canonical"),
        ("spirit_field", "danger_level", "rising", "canonical"),
        ("ruined_temple", "night_risk", "unknown", "canonical"),
    ]


def _initial_locations() -> list[tuple[str, str]]:
    return [
        ("player", "tea_stall"),
        ("jiao_qi", "tea_stall"),
        ("han_shu", "tea_stall"),
        ("sun_niang", "herb_shop"),
        ("song_heng", "county_warehouse"),
        ("lin_yan", "mountain_gate_road"),
        ("lu_san", "ferry_bridge"),
        ("xiao_ni", "ruined_temple"),
        ("gu_hui", "spirit_field"),
    ]


def _location_connections() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("tea_stall", "ferry_bridge", {}),
        ("tea_stall", "herb_shop", {}),
        ("tea_stall", "county_warehouse", {}),
        ("ferry_bridge", "mountain_gate_road", {}),
        ("herb_shop", "spirit_field", {}),
        ("county_warehouse", "ruined_temple", {}),
        ("spirit_field", "ruined_temple", {}),
    ]


def _initial_holders() -> list[tuple[str, str]]:
    return [
        ("basic_food", "player"),
        ("tea_debt_note", "jiao_qi"),
        ("herb_bundle", "herb_shop"),
        ("trial_token", "lin_yan"),
        ("temple_ash", "ruined_temple"),
        ("old_bow", "han_shu"),
        ("warehouse_page", "song_heng"),
        ("fire_talisman", "gu_hui"),
    ]


def _initial_memories() -> list[dict[str, Any]]:
    return [
        {"owner_id": "player", "memory_text": "你是逃荒来的短工，欠茶棚一顿饭钱，但韩叔愿意替你说一句话。", "truth_scope": "player", "salience": 0.8, "confidence": 1.0},
        {"owner_id": "town_public", "memory_text": "镇上都在谈药荒、外役招募和夜庙白影。", "truth_scope": "rumor", "salience": 0.8, "confidence": 0.7},
        {"owner_id": "jiao_qi", "memory_text": "焦七知道白影传闻和鲁三夜路有关，但不会白白告诉外乡人。", "truth_scope": "npc", "salience": 0.7, "confidence": 0.8},
        {"owner_id": "xiao_ni", "memory_text": "小妮知道破庙白影怕火，也知道县仓账页藏在灰龛后。", "truth_scope": "npc", "salience": 0.9, "confidence": 0.9},
    ]


def _initial_tensions() -> list[dict[str, Any]]:
    return [
        {
            "id": "qingxi_herb_shortage",
            "tension_type": "resource_shortage",
            "description": "药荒让药铺缺货、病人增多，孙娘急需可靠帮手。",
            "affected_entities": ["herb_shop", "sun_niang", "spirit_field"],
            "evidence": [{"source_type": "state", "entity_id": "herb_shop", "attr": "herb_stock", "value": "low"}],
            "suggested_actions": ["help_sort_herbs", "talk_to_sun_niang"],
            "priority": 0.9,
            "stake": "药铺倒闭，镇民无药可用",
            "deadline_turn": 15,
            "sponsors": ["sun_niang"],
            "blockers": ["lu_san"],
            "player_touchpoints": ["talk_to_sun_niang", "help_sort_herbs", "share_clue_with_lin"],
        },
        {
            "id": "qingxi_outer_recruitment",
            "tension_type": "opportunity",
            "description": "青木宗外门招外役，林砚只愿给可靠的人试工牌。",
            "affected_entities": ["outer_sect", "lin_yan", "trial_token"],
            "evidence": [{"source_type": "state", "entity_id": "outer_sect", "attr": "reputation.player", "value": 0}],
            "suggested_actions": ["request_outer_trial", "share_clue_with_lin"],
            "priority": 0.75,
            "stake": "成为外门杂役，获得庇护",
            "deadline_turn": 20,
            "sponsors": ["lin_yan"],
            "blockers": ["lu_san"],
            "player_touchpoints": ["talk_to_lin_yan", "request_outer_trial", "share_clue_with_lin"],
        },
        {
            "id": "qingxi_white_shadow",
            "tension_type": "rumor_unresolved",
            "description": "夜庙白影牵着偷采、藏账和夜路风险，传闻半真半假。",
            "affected_entities": ["ruined_temple", "xiao_ni", "lu_san", "temple_ash"],
            "evidence": [{"source_type": "memory", "owner_id": "town_public", "text": "夜庙白影"}],
            "suggested_actions": ["ask_white_shadow_rumor", "inspect_ruined_temple"],
            "priority": 0.85,
            "stake": "破庙白影真相可能颠覆小镇",
            "deadline_turn": None,
            "sponsors": ["jiao_qi"],
            "blockers": ["xiao_ni"],
            "player_touchpoints": ["talk_to_jiao_qi", "inspect_ruined_temple", "ask_white_shadow_rumor"],
        },
    ]


def _initial_quests() -> list[dict[str, Any]]:
    return [
        {"id": "quest_qingxi_trial_work", "title": "拿到外役试工入口", "issuer_id": "lin_yan", "tension_id": "qingxi_outer_recruitment", "objectives": [{"type": "gain_permission", "target": "outer_trial_candidate"}], "rewards": [{"type": "set_state", "entity": "player", "attr": "identity_tags", "value": ["refugee_worker", "outer_trial_candidate"]}], "failure_consequences": [{"type": "change_relation", "entity": "lin_yan", "attr": "respect.player", "delta": -1}], "evidence": [{"source_type": "tension", "tension_id": "qingxi_outer_recruitment"}]},
        {"id": "quest_qingxi_white_shadow", "title": "弄清夜庙白影", "issuer_id": "jiao_qi", "tension_id": "qingxi_white_shadow", "objectives": [{"type": "collect_evidence", "target": "temple_ash"}, {"type": "visit_location", "target": "ruined_temple"}], "rewards": [{"type": "grant_permission", "target": "sleep_at_temple"}], "failure_consequences": [{"type": "change_relation", "entity": "lu_san", "attr": "suspicion.player", "delta": 1}], "evidence": [{"source_type": "tension", "tension_id": "qingxi_white_shadow"}]},
    ]


def _action_templates() -> list[ActionTemplate]:
    return [
        ActionTemplate("move_to_location", "前往地点", None, "low", "目标地点与当前位置相连。", [{"type": "connected_location", "actor": "$actor", "target": "$target", "reason": "目标地点无法从当前位置直接到达。"}, {"type": "edge_unblocked", "actor": "$actor", "target": "$target", "reason": "路径暂时被局势封锁。"}], [{"type": "move_entity", "entity": "$actor", "to": "$target", "actor": "$actor"}]),
        _talk("talk_to_sun_niang", "和孙娘交谈", "sun_niang"),
        _talk("talk_to_jiao_qi", "和焦七交谈", "jiao_qi"),
        _talk("talk_to_lin_yan", "和林砚交谈", "lin_yan"),
        _talk("talk_to_lu_san", "和鲁三交谈", "lu_san"),
        _talk("talk_to_xiao_ni", "和小妮交谈", "xiao_ni"),
        ActionTemplate("help_sort_herbs", "替孙娘整理药草", "sun_niang", "low", "你用短工经验帮药铺稳住一小段药荒。", [{"type": "same_location", "a": "$actor", "b": "sun_niang", "reason": "孙娘不在这里。"}], [{"type": "change_relation", "src": "sun_niang", "rel": "TRUSTS", "dst": "$actor", "state_attr": "trust.player", "delta": 2, "actor": "system"}, {"type": "delta_resource", "entity": "$actor", "attr": "skill.herbalism", "delta": 1, "actor": "$actor"}, {"type": "grant_permission", "permission": "pharmacy_backroom", "actor": "system"}, {"type": "add_memory", "owner": "$actor", "memory_text": "孙娘让你进药铺后间帮忙，药荒可能和后山灵田异常有关。", "truth_scope": "player", "salience": 0.8, "actor": "system"}]),
        ActionTemplate("ask_white_shadow_rumor", "向焦七打听白影", "jiao_qi", "low", "焦七愿意卖你一个半真半假的夜庙线索。", [{"type": "same_location", "a": "$actor", "b": "jiao_qi", "reason": "焦七不在这里。"}], [{"type": "change_relation", "src": "jiao_qi", "rel": "TRUSTS", "dst": "$actor", "state_attr": "trust.player", "delta": 1, "actor": "system"}, {"type": "add_knowledge", "clue": "white_shadow_fears_fire", "actor": "system"}, {"type": "add_memory", "owner": "$actor", "memory_text": "焦七说夜庙白影怕火，但鲁三的人不喜欢别人问这条夜路。", "truth_scope": "player", "salience": 0.85, "actor": "system"}]),
        ActionTemplate("request_outer_trial", "向林砚申请外役试工", "lin_yan", "low", "林砚愿意给有药铺担保或白影线索的人试工入口。", [{"type": "same_location", "a": "$actor", "b": "lin_yan", "reason": "林砚不在这里。"}], [{"type": "change_relation", "src": "lin_yan", "rel": "RESPECTS", "dst": "$actor", "state_attr": "respect.player", "delta": 1, "actor": "system"}, {"type": "add_identity_tag", "tag": "outer_trial_candidate", "actor": "system"}, {"type": "grant_permission", "permission": "outer_trial", "actor": "system"}, {"type": "transfer_item", "item": "trial_token", "from": "lin_yan", "to": "$actor", "actor": "lin_yan"}]),
        ActionTemplate("inspect_ruined_temple", "带着火线索夜探破庙", "ruined_temple", "medium", "白影怕火的线索让你能把破庙风险变成证据。", [{"type": "state_equals", "entity": "$actor", "attr": "location", "value": "ruined_temple", "reason": "你还没到破庙。"}, {"type": "state_equals", "entity": "$actor", "attr": "known_clues", "value": ["white_shadow_fears_fire"], "reason": "你还不知道白影怕火，夜探风险太高。"}], [{"type": "grant_permission", "permission": "sleep_at_temple", "actor": "system"}, {"type": "set_state", "entity": "ruined_temple", "attr": "night_risk", "value": "mapped", "actor": "system"}, {"type": "add_memory", "owner": "$actor", "memory_text": "你在破庙灰龛后找到灰痕，白影更像人在借传闻藏东西。", "truth_scope": "player", "salience": 0.9, "actor": "system"}]),
        ActionTemplate("share_clue_with_lin", "把白影线索告诉林砚", "lin_yan", "low", "白影线索能证明你不是只会听传闻的外乡人。", [{"type": "same_location", "a": "$actor", "b": "lin_yan", "reason": "林砚不在这里。"}, {"type": "state_equals", "entity": "$actor", "attr": "known_clues", "value": ["white_shadow_fears_fire"], "reason": "你还没有可说的白影线索。"}], [{"type": "change_relation", "src": "lin_yan", "rel": "RESPECTS", "dst": "$actor", "state_attr": "respect.player", "delta": 2, "actor": "system"}, {"type": "delta_resource", "entity": "outer_sect", "attr": "reputation.player", "delta": 1, "actor": "system"}, {"type": "add_memory", "owner": "lin_yan", "memory_text": "玩家带来了白影怕火的线索，值得继续观察。", "truth_scope": "npc", "salience": 0.75, "actor": "system"}]),
        ActionTemplate("spread_rumor", "散播当前传闻", None, "medium", "传闻会改变别人对你的注意。", [{"type": "scope_allowed", "scope": "rumor"}], [{"type": "add_memory", "owner": "town_public", "memory_text": "玩家主动谈起夜庙白影，镇上更多人注意到了他。", "truth_scope": "rumor", "salience": 0.6, "actor": "$actor"}, {"type": "change_relation", "src": "lu_san", "rel": "SUSPECTS", "dst": "$actor", "state_attr": "suspicion.player", "delta": 1, "actor": "system"}]),
    ]


def _talk(action_id: str, label: str, npc_id: str) -> ActionTemplate:
    return ActionTemplate(action_id, label, npc_id, "low", "目标 NPC 位于当前地点。", [{"type": "same_location", "a": "$actor", "b": npc_id, "reason": "目标 NPC 不在当前位置。"}], [{"type": "add_conversation_event", "actor": "$actor", "target": npc_id, "topic": label}])


def _seed_evidence() -> dict[str, Any]:
    return {"source_id": "seed_qingxi_world", "span": [0, 0], "extractor": "seed_qingxi_v1", "confidence": 1.0}
