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


def test_explain_event_memory_and_quest() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)
    service.turn(DEMO_WORLD_ID, "村里有人说玩家偷了钥匙")
    event_id = service.events(DEMO_WORLD_ID)[-1]["id"]
    memory_id = service.memories(DEMO_WORLD_ID)[0]["id"]
    quest_id = "quest_clear_key_theft_rumor"

    event_explanation = service.explain_event(DEMO_WORLD_ID, event_id)
    memory_explanation = service.explain_memory(DEMO_WORLD_ID, memory_id)
    quest_explanation = service.explain_quest(DEMO_WORLD_ID, quest_id)

    assert event_explanation["event"]["event_type"] == "ADD_MEMORY"
    assert memory_explanation["memory"]["truth_scope"] == "rumor"
    assert quest_explanation["quest_id"] == quest_id
    assert quest_explanation["traceable"] is True


def test_explain_endpoints_for_quest_and_event() -> None:
    client = TestClient(create_app(":memory:"))
    events = client.get(f"/worlds/{DEMO_WORLD_ID}/events").json()
    event_id = events[0]["id"]

    event_response = client.get(f"/worlds/{DEMO_WORLD_ID}/explain/event/{event_id}")
    quest_response = client.get(f"/worlds/{DEMO_WORLD_ID}/explain/quest/quest_find_legal_entry")

    assert event_response.status_code == 200
    assert quest_response.status_code == 200
    assert quest_response.json()["tension_id"] == "tension_locked_iron_gate"
