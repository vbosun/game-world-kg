from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_qingxi import QINGXI_WORLD_ID, seed_qingxi_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_qingxi_world(conn)
    return GameWorldService(conn)


def test_qingxi_play_state_starts_with_goal_panels() -> None:
    service = _service()

    state = service.play_state(QINGXI_WORLD_ID)

    assert state["world"]["name"] == "青溪镇"
    assert state["scene"]["location"]["id"] == "tea_stall"
    assert {"jiao_qi", "han_shu"} <= {npc["id"] for npc in state["scene"]["visible_npcs"]}
    assert {"quest_qingxi_trial_work", "quest_qingxi_white_shadow"} <= {quest["quest_id"] for quest in state["quests"]}
    assert {"qingxi_herb_shortage", "qingxi_white_shadow"} <= {tension["tension_id"] for tension in state["tensions"]}
    assert "refugee_worker" in state["player"]["identity_tags"]
    assert state["foreground"]["recommended_opportunity"]


def test_qingxi_first_ten_turns_create_progression_and_routes() -> None:
    service = _service()

    script = [
        ("打听白影", "ask_white_shadow_rumor", "jiao_qi"),
        ("去药铺", "move_to_location", "herb_shop"),
        ("整理药草", "help_sort_herbs", "sun_niang"),
        ("去灵田", "move_to_location", "spirit_field"),
        ("去破庙", "move_to_location", "ruined_temple"),
        ("夜探破庙", "inspect_ruined_temple", "ruined_temple"),
        ("回县仓", "move_to_location", "county_warehouse"),
        ("回茶棚", "move_to_location", "tea_stall"),
        ("去渡桥", "move_to_location", "ferry_bridge"),
        ("去山门", "move_to_location", "mountain_gate_road"),
        ("申请试工", "request_outer_trial", "lin_yan"),
    ]
    changes = []
    for player_input, action_id, target_id in script:
        result = service.play_turn(QINGXI_WORLD_ID, player_input, selected_action_id=action_id, selected_target_id=target_id)
        assert result["turn"]["accepted"] is True
        changes.extend(result["changes"])

    player = service.play_state(QINGXI_WORLD_ID)["player"]
    relationships = {item["id"]: item for item in service.play_state(QINGXI_WORLD_ID)["relationships"]}
    action_ids = {item["action_id"] for item in service.play_affordances(QINGXI_WORLD_ID)}

    assert "white_shadow_fears_fire" in player["known_clues"]
    assert "outer_trial_candidate" in player["identity_tags"]
    assert "sleep_at_temple" in player["permissions"]
    assert relationships["sun_niang"]["attitudes"]["trust.player"] >= 3
    assert relationships["lin_yan"]["attitudes"]["respect.player"] >= 1
    assert len([change for change in changes if change["type"] != "no_state_change"]) >= 5
    assert {"talk_to_lin_yan", "request_outer_trial", "spread_rumor"} & action_ids


def test_qingxi_play_npc_and_explain_routes_are_available() -> None:
    client = TestClient(create_app(":memory:"))

    tick = client.post(f"/worlds/{QINGXI_WORLD_ID}/play/npc-tick")
    activity = client.get(f"/worlds/{QINGXI_WORLD_ID}/play/npc-activity")
    quest = client.get(f"/worlds/{QINGXI_WORLD_ID}/play/explain/quest/quest_qingxi_white_shadow")
    state = client.get(f"/worlds/{QINGXI_WORLD_ID}/play/explain/state/player/identity_tags")

    assert tick.status_code == 200
    assert activity.status_code == 200
    assert quest.status_code == 200
    assert state.status_code == 200
    assert "evidence" not in quest.json()
    assert quest.json()["quest_id"] == "quest_qingxi_white_shadow"
