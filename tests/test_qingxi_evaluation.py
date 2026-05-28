from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_qingxi import QINGXI_WORLD_ID, seed_qingxi_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_qingxi_world(conn)
    return GameWorldService(conn)


def test_qingxi_30_turn_playability() -> None:
    """P5-02: 30-turn automated playthrough with assertions for world health."""
    service = _service()

    # Connections: tea_stall-ferry_bridge, tea_stall-herb_shop, tea_stall-county_warehouse,
    #   ferry_bridge-mountain_gate_road, herb_shop-spirit_field,
    #   county_warehouse-ruined_temple, spirit_field-ruined_temple
    script = [
        # Phase 1: Gather info at tea_stall (start location)
        ("打听白影", "ask_white_shadow_rumor", "jiao_qi"),
        # Phase 2: Help at herb shop
        ("去药铺", "move_to_location", "herb_shop"),
        ("和孙娘交谈", "talk_to_sun_niang", "sun_niang"),
        ("整理药草", "help_sort_herbs", "sun_niang"),
        # Phase 3: Explore spirit field
        ("去灵田", "move_to_location", "spirit_field"),
        # Phase 4: Investigate ruined_temple via spirit_field
        ("去破庙", "move_to_location", "ruined_temple"),
        ("夜探破庙", "inspect_ruined_temple", "ruined_temple"),
        # Phase 5: Travel around
        ("回灵田", "move_to_location", "spirit_field"),
        ("回药铺", "move_to_location", "herb_shop"),
        ("去茶棚", "move_to_location", "tea_stall"),
        ("去渡桥", "move_to_location", "ferry_bridge"),
        # Phase 6: Visit mountain gate
        ("去山门", "move_to_location", "mountain_gate_road"),
        ("分享线索", "share_clue_with_lin", "lin_yan"),
        # Phase 7: More exploration
        ("回渡桥", "move_to_location", "ferry_bridge"),
        ("去茶棚", "move_to_location", "tea_stall"),
        ("去县仓", "move_to_location", "county_warehouse"),
        ("去破庙", "move_to_location", "ruined_temple"),
        ("回县仓", "move_to_location", "county_warehouse"),
        ("去茶棚", "move_to_location", "tea_stall"),
        ("去渡桥", "move_to_location", "ferry_bridge"),
        ("去山门", "move_to_location", "mountain_gate_road"),
        ("申请试工", "request_outer_trial", "lin_yan"),
        # Phase 8: Return and spread rumors
        ("回渡桥", "move_to_location", "ferry_bridge"),
        ("去茶棚", "move_to_location", "tea_stall"),
        ("散播传闻", "spread_rumor", None),
        ("去药铺", "move_to_location", "herb_shop"),
        ("去灵田", "move_to_location", "spirit_field"),
        ("去破庙", "move_to_location", "ruined_temple"),
        ("回灵田", "move_to_location", "spirit_field"),
        ("回药铺", "move_to_location", "herb_shop"),
        ("回茶棚", "move_to_location", "tea_stall"),
    ]

    for i, (player_input, action_id, target_id) in enumerate(script):
        result = service.play_turn(
            QINGXI_WORLD_ID, player_input,
            selected_action_id=action_id,
            selected_target_id=target_id,
        )
        assert result["turn"]["accepted"] is True, f"Turn {i+1} '{player_input}' ({action_id}/{target_id}) should be accepted: {result['turn'].get('reason', '')}"

    # Assertions
    events = service.events(QINGXI_WORLD_ID)
    event_types = {e["event_type"] for e in events}

    # >= 5 visible world changes
    player = service.state(QINGXI_WORLD_ID).get("player", {})
    changes_count = 0
    if player.get("location") != "tea_stall":
        changes_count += 1
    if player.get("known_clues"):
        changes_count += len(player.get("known_clues", []))
    if player.get("identity_tags", []) != ["refugee_worker"]:
        changes_count += 1
    if player.get("permissions"):
        changes_count += len(player.get("permissions", []))
    skills = {k: v for k, v in player.items() if k.startswith("skill.") and v > 0}
    changes_count += len(skills)
    assert changes_count >= 5, f"Should have >= 5 visible world changes, got {changes_count}"

    # >= 1 NPC active event
    npc_events = [e for e in events if e["event_type"] in {"NPC_ACTION", "FACTION_ACTIVITY", "SPREAD_RUMOR"}]
    assert len(npc_events) >= 1, "Should have at least some NPC activity"

    # >= 2 continuation paths available
    affordances = service.play_affordances(QINGXI_WORLD_ID)
    assert len(affordances) >= 2, "Should have >= 2 continuation paths"

    # Replay consistency
    service.replay(QINGXI_WORLD_ID, to_turn=15)
    events_after_replay = service.events(QINGXI_WORLD_ID)
    assert len(events_after_replay) <= len(events), "Replay should not add extra events"

    # No canonical contamination from rumors
    for event in events:
        if event["event_type"] == "ADD_MEMORY":
            payload = event.get("payload", {})
            if payload.get("truth_scope") == "canonical":
                assert payload.get("owner_id") != "player", "Player memories should not be canonical"
