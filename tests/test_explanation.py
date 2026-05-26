from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_explain_state_traces_current_state_to_event() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)
    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")

    explanation = service.explain_state(DEMO_WORLD_ID, "pass_token", "holder")

    assert explanation["value"] == "guard_alos"
    assert explanation["source_event"]["event_type"] == "TRANSFER_ITEM"
    assert explanation["state_deltas"][0]["old_value"] == "player"
    assert explanation["state_deltas"][0]["new_value"] == "guard_alos"
    assert explanation["evidence"]


def test_explain_state_endpoint() -> None:
    response = TestClient(create_app(":memory:")).get(f"/worlds/{DEMO_WORLD_ID}/explain/state/iron_gate/open")

    assert response.status_code == 200
    body = response.json()
    assert body["value"] is False
    assert body["source_event"]["event_type"] == "SET_STATE"
