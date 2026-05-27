from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def test_play_state_returns_scene_panels_and_actions() -> None:
    service = _service()

    state = service.play_state(DEMO_WORLD_ID)

    assert state["scene"]["location"]["id"] == "village_gate"
    assert state["scene"]["visible_npcs"]
    assert 1 <= len(state["affordances"]) <= 7
    assert state["quests"]
    assert state["tensions"]
    assert "relationships" in state
    assert "known_clues" in state["player"]


def test_play_turn_binds_current_action_and_returns_changes() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我想把通行令交给守卫", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    assert result["turn"]["accepted"] is True
    assert result["bound_action"]["action_id"] == "show_pass_token"
    assert any(change["type"] in {"resource_change", "relationship_change", "knowledge_change"} for change in result["changes"])
    assert result["feedback"]["next_hooks"]
    assert any(item["id"] == "guard_alos" for item in result["relationships"])


def test_play_turn_rejects_unbound_free_input_with_game_hint_and_event() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我召唤陨石砸开所有城门")

    assert result["turn"]["accepted"] is False
    assert result["turn"]["action_id"] == "__unparsed__"
    assert result["bound_action"] is None
    assert result["changes"][0]["type"] == "rule_rejection"
    assert "你可以先尝试" in result["feedback"]["narration"]
    assert service.events(DEMO_WORLD_ID)[-1]["event_type"] == "ACTION_REJECTED"


def test_play_api_routes_are_available() -> None:
    client = TestClient(create_app(":memory:"))

    state = client.get("/worlds/demo_gate/play/state")
    turn = client.post(
        "/worlds/demo_gate/play/turn",
        json={"player_input": "交出通行令", "selected_action_id": "show_pass_token", "selected_target_id": "guard_alos"},
    )
    quests = client.get("/worlds/demo_gate/play/quests")
    timeline = client.get("/worlds/demo_gate/play/timeline")

    assert state.status_code == 200
    assert turn.status_code == 200
    assert quests.status_code == 200
    assert timeline.status_code == 200
    assert turn.json()["changes"]
