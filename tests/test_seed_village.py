from __future__ import annotations

from game_world_kg.action_template import ActionTemplateStore
from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.graph import WorldGraph
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world


def test_seed_village_creates_complete_demo_world() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)

    graph = WorldGraph(conn).graph(DEMO_VILLAGE_WORLD_ID)
    counts: dict[str, int] = {}
    for node in graph["nodes"]:
        counts[node["entity_type"]] = counts.get(node["entity_type"], 0) + 1

    assert counts["Location"] == 9
    assert counts["Character"] == 7
    assert counts["Item"] == 8
    assert counts["Faction"] == 4


def test_seed_village_preserves_scope_boundaries() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)

    state = WorldGraph(conn).state(DEMO_VILLAGE_WORLD_ID)
    memories = WorldGraph(conn).memories(DEMO_VILLAGE_WORLD_ID)

    assert state["silver_key"]["holder"] == "guard_alos"
    assert state["silver_key"]["rumor.theft_suspect.player"] is True
    assert any(memory["truth_scope"] == "rumor" for memory in memories)
    assert any(memory["truth_scope"] == "npc" and memory["owner_id"] == "guard_alos" for memory in memories)
    assert any(memory["truth_scope"] == "faction" and memory["owner_id"] == "village_council" for memory in memories)


def test_seed_village_has_at_least_ten_action_templates() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)

    templates = ActionTemplateStore(conn).list_enabled(DEMO_VILLAGE_WORLD_ID)
    action_ids = {template.action_id for template in templates}

    assert len(templates) >= 10
    assert {"show_pass_token", "request_access", "ask_about_rumor", "inspect_warehouse", "trade_grain"} <= action_ids


def test_app_startup_seeds_demo_village() -> None:
    from fastapi.testclient import TestClient

    app = create_app(":memory:")
    response = TestClient(app).get(f"/worlds/{DEMO_VILLAGE_WORLD_ID}/state")

    assert response.status_code == 200
    assert response.json()["player"]["location"] == "village_gate"
