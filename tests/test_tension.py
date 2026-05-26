from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService
from game_world_kg.tension import TensionScanner


def _village_service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    return GameWorldService(conn)


def test_tension_scanner_finds_three_demo_village_lines() -> None:
    service = _village_service()
    tensions = TensionScanner(service).scan(DEMO_VILLAGE_WORLD_ID)
    tension_types = {item["type"] for item in tensions}

    assert "locked_location" in tension_types
    assert "rumor_unresolved" in tension_types
    assert "resource_shortage" in tension_types
    assert "quest_dependency_missing" in tension_types


def test_demo_village_quests_are_generated_from_tensions() -> None:
    service = _village_service()
    quests = service.quests(DEMO_VILLAGE_WORLD_ID)
    quest_ids = {quest["quest_id"] for quest in quests}

    assert "quest_find_legal_entry" in quest_ids
    assert "quest_clear_key_theft_rumor" in quest_ids
    assert "quest_access_warehouse" in quest_ids
    assert "quest_investigate_grain_trade" in quest_ids
    assert all(quest.get("tension_id") for quest in quests)
    assert all(quest["evidence"] for quest in quests)


def test_tensions_endpoint_returns_demo_village_tensions() -> None:
    response = TestClient(create_app(":memory:")).get(f"/worlds/{DEMO_VILLAGE_WORLD_ID}/tensions")

    assert response.status_code == 200
    assert any(item["tension_id"] == "tension_key_theft_rumor" for item in response.json())
