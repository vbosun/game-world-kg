from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService


def test_demo_village_30_turn_playthrough_advances_key_lines_and_replays() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    script = [
        "和守卫交谈",
        "我向守卫出示通行令",
        "请守卫放行",
        "去内城",
        "去村口",
        "去守卫室",
        "去村口",
        "去村广场",
        "和村长交谈",
        "和仓库管理员交谈",
        "去酒馆",
        "和米拉交谈",
        "询问米拉关于银钥匙传闻",
        "找可疑旅人澄清银钥匙谣言",
        "回到广场",
        "去仓库",
        "检查仓库门锁",
        "回到广场",
        "请求仓库权限",
        "和村长交谈",
        "去市集",
        "和商人伯林交谈",
        "和商人伯林协商粮食交易",
        "回到广场",
        "去井边",
        "回到广场",
        "去酒馆",
        "和米拉交谈",
        "回到广场",
        "去村口",
        "和守卫交谈",
    ]

    results = [service.turn(DEMO_VILLAGE_WORLD_ID, command) for command in script]

    assert len(results) >= 30
    assert all(result["accepted"] for result in results)
    final_state = service.state(DEMO_VILLAGE_WORLD_ID)
    assert final_state["iron_gate"]["open"] is True
    assert final_state["player"]["location"] == "village_gate"
    assert final_state["silver_key"]["holder"] == "guard_alos"
    assert final_state["silver_key"]["rumor.rumor_resolved"] is True
    assert final_state["warehouse"]["locked"] is False
    assert final_state["grain_bag"]["trade_completed"] is True
    assert any("可疑旅人" in memory["memory_text"] for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "player"))

    replayed = service.replay(DEMO_VILLAGE_WORLD_ID)
    replayed_state = replayed["state"]
    assert replayed_state["iron_gate"]["open"] == final_state["iron_gate"]["open"]
    assert replayed_state["player"]["location"] == final_state["player"]["location"]
    assert replayed_state["warehouse"]["locked"] == final_state["warehouse"]["locked"]
    assert replayed_state["grain_bag"]["trade_completed"] == final_state["grain_bag"]["trade_completed"]
