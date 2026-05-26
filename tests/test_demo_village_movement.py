from __future__ import annotations

import pytest

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService


@pytest.fixture()
def service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    return GameWorldService(conn)


def _movement_targets(affordances: list[dict]) -> set[str]:
    return {item["target_id"] for item in affordances if item["action_id"] == "move_to_location"}


def test_demo_village_initial_movement_affordances_follow_connections(service: GameWorldService) -> None:
    targets = _movement_targets(service.affordances(DEMO_VILLAGE_WORLD_ID))

    assert {"village_square", "guard_room"} <= targets
    assert "inner_city" not in targets


def test_demo_village_can_move_across_main_locations(service: GameWorldService) -> None:
    visited = {"village_gate"}

    result = service.turn(DEMO_VILLAGE_WORLD_ID, "去村广场")
    assert result["accepted"] is True
    visited.add(service.state(DEMO_VILLAGE_WORLD_ID)["player"]["location"])
    assert {"tavern", "market_stall", "well", "warehouse"} <= _movement_targets(result["affordances"])

    for command, expected_location in [
        ("去酒馆", "tavern"),
        ("回到广场", "village_square"),
        ("去市集", "market_stall"),
        ("回到广场", "village_square"),
        ("去井边", "well"),
        ("回到广场", "village_square"),
        ("去仓库", "warehouse"),
        ("回到广场", "village_square"),
        ("去村口", "village_gate"),
        ("去守卫室", "guard_room"),
    ]:
        result = service.turn(DEMO_VILLAGE_WORLD_ID, command)
        assert result["accepted"] is True
        assert service.state(DEMO_VILLAGE_WORLD_ID)["player"]["location"] == expected_location
        visited.add(expected_location)

    assert len(visited) >= 6


def test_demo_village_rejects_unconnected_movement(service: GameWorldService) -> None:
    result = service.turn(DEMO_VILLAGE_WORLD_ID, "去酒馆")

    assert result["accepted"] is False
    assert service.state(DEMO_VILLAGE_WORLD_ID)["player"]["location"] == "village_gate"


def test_demo_village_inner_city_stays_locked_until_gate_opens(service: GameWorldService) -> None:
    blocked = service.turn(DEMO_VILLAGE_WORLD_ID, "去内城")
    assert blocked["accepted"] is False
    assert service.state(DEMO_VILLAGE_WORLD_ID)["player"]["location"] == "village_gate"

    service.turn(DEMO_VILLAGE_WORLD_ID, "我向守卫出示通行令")
    service.turn(DEMO_VILLAGE_WORLD_ID, "请守卫放行")
    opened_targets = _movement_targets(service.affordances(DEMO_VILLAGE_WORLD_ID))
    assert "inner_city" in opened_targets

    moved = service.turn(DEMO_VILLAGE_WORLD_ID, "去内城")
    assert moved["accepted"] is True
    assert service.state(DEMO_VILLAGE_WORLD_ID)["player"]["location"] == "inner_city"
