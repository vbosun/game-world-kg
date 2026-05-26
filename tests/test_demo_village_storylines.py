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


def test_rumor_line_discovers_and_clarifies_without_canonical_pollution(service: GameWorldService) -> None:
    service.turn(DEMO_VILLAGE_WORLD_ID, "去村广场")
    service.turn(DEMO_VILLAGE_WORLD_ID, "去酒馆")

    discovered = service.turn(DEMO_VILLAGE_WORLD_ID, "询问米拉关于银钥匙传闻")
    assert discovered["accepted"] is True
    assert any("可疑旅人" in memory["memory_text"] for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "player"))

    clarified = service.turn(DEMO_VILLAGE_WORLD_ID, "找可疑旅人澄清银钥匙谣言")
    assert clarified["accepted"] is True
    state = service.state(DEMO_VILLAGE_WORLD_ID)
    assert state["silver_key"]["holder"] == "guard_alos"
    assert state["silver_key"]["rumor.rumor_resolved"] is True
    assert "tension_key_theft_rumor" not in {item["tension_id"] for item in service.tensions(DEMO_VILLAGE_WORLD_ID)}


def test_warehouse_line_inspects_unlocks_and_completes_grain_trade(service: GameWorldService) -> None:
    service.turn(DEMO_VILLAGE_WORLD_ID, "去村广场")
    service.turn(DEMO_VILLAGE_WORLD_ID, "去仓库")

    inspected = service.turn(DEMO_VILLAGE_WORLD_ID, "检查仓库门锁")
    assert inspected["accepted"] is True
    assert service.state(DEMO_VILLAGE_WORLD_ID)["player"]["player.warehouse_clue"] == "seal_intact_ledger_inside"

    service.turn(DEMO_VILLAGE_WORLD_ID, "回到广场")
    unlocked = service.turn(DEMO_VILLAGE_WORLD_ID, "请求仓库权限")
    assert unlocked["accepted"] is True
    assert service.state(DEMO_VILLAGE_WORLD_ID)["warehouse"]["locked"] is False

    service.turn(DEMO_VILLAGE_WORLD_ID, "去市集")
    traded = service.turn(DEMO_VILLAGE_WORLD_ID, "和商人伯林协商粮食交易")
    assert traded["accepted"] is True
    state = service.state(DEMO_VILLAGE_WORLD_ID)
    assert state["warehouse"]["grain_stock"] == 8
    assert state["merchant_borin"]["gold"] == 3
    assert state["grain_bag"]["trade_completed"] is True

    tension_ids = {item["tension_id"] for item in service.tensions(DEMO_VILLAGE_WORLD_ID)}
    assert "tension_warehouse_locked" not in tension_ids
    assert "tension_grain_trade_blocked" not in tension_ids
