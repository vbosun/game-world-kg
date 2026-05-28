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


def test_qingxi_10_turn_checkpoint_progression() -> None:
    """P5-01: Scripted playtest with checkpoint assertions for key progression moments."""
    service = _service()

    # Checkpoint 1: player starts at tea_stall, talk to jiao_qi about white shadow
    result = service.play_turn(QINGXI_WORLD_ID, "打听白影", selected_action_id="ask_white_shadow_rumor", selected_target_id="jiao_qi")
    assert result["turn"]["accepted"] is True
    player = service.play_state(QINGXI_WORLD_ID)["player"]
    assert player["location"] == "tea_stall", "Checkpoint 1: player should be at tea_stall"
    assert "white_shadow_fears_fire" in player["known_clues"], "Checkpoint 1: should know white_shadow_fears_fire clue"

    # Checkpoint 2: move to herb_shop, build relationship with sun_niang
    service.play_turn(QINGXI_WORLD_ID, "去药铺", selected_action_id="move_to_location", selected_target_id="herb_shop")
    result = service.play_turn(QINGXI_WORLD_ID, "整理药草", selected_action_id="help_sort_herbs", selected_target_id="sun_niang")
    assert result["turn"]["accepted"] is True
    rels = {r["id"]: r for r in service.play_state(QINGXI_WORLD_ID)["relationships"]}
    assert rels["sun_niang"]["attitudes"].get("trust.player", 0) >= 3, "Checkpoint 2: trust with sun_niang should be >= 3"
    player = service.play_state(QINGXI_WORLD_ID)["player"]
    assert "pharmacy_backroom" in player["permissions"], "Checkpoint 2: should have pharmacy backroom access"

    # Checkpoint 3: travel to ruined_temple via spirit_field, get temple evidence
    service.play_turn(QINGXI_WORLD_ID, "去灵田", selected_action_id="move_to_location", selected_target_id="spirit_field")
    service.play_turn(QINGXI_WORLD_ID, "去破庙", selected_action_id="move_to_location", selected_target_id="ruined_temple")
    result = service.play_turn(QINGXI_WORLD_ID, "夜探破庙", selected_action_id="inspect_ruined_temple", selected_target_id="ruined_temple")
    assert result["turn"]["accepted"] is True
    player = service.play_state(QINGXI_WORLD_ID)["player"]
    assert "sleep_at_temple" in player["permissions"], "Checkpoint 3: should have sleep_at_temple permission"

    # Checkpoint 4: travel to mountain gate, share clue with lin_yan
    service.play_turn(QINGXI_WORLD_ID, "回灵田", selected_action_id="move_to_location", selected_target_id="spirit_field")
    service.play_turn(QINGXI_WORLD_ID, "回药铺", selected_action_id="move_to_location", selected_target_id="herb_shop")
    service.play_turn(QINGXI_WORLD_ID, "去茶棚", selected_action_id="move_to_location", selected_target_id="tea_stall")
    service.play_turn(QINGXI_WORLD_ID, "去渡桥", selected_action_id="move_to_location", selected_target_id="ferry_bridge")
    service.play_turn(QINGXI_WORLD_ID, "去山门", selected_action_id="move_to_location", selected_target_id="mountain_gate_road")
    result = service.play_turn(QINGXI_WORLD_ID, "分享线索", selected_action_id="share_clue_with_lin", selected_target_id="lin_yan")
    assert result["turn"]["accepted"] is True
    rels = {r["id"]: r for r in service.play_state(QINGXI_WORLD_ID)["relationships"]}
    assert rels["lin_yan"]["attitudes"].get("respect.player", 0) >= 2, "Checkpoint 4: respect from lin_yan should be >= 2"

    # Verify overall event types
    events = service.events(QINGXI_WORLD_ID)
    event_types = {e["event_type"] for e in events}
    assert "ADD_MEMORY" in event_types
    assert "MOVE_ENTITY" in event_types
    assert "CHANGE_RELATION" in event_types
