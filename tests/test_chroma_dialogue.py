from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService


def test_npc_dialogue_uses_chroma_owner_scoped_memory(tmp_path) -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    answer = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "你知道银钥匙在哪里吗")

    assert answer["memories"]
    assert all(memory["truth_scope"] == "npc" for memory in answer["memories"])
    assert "银钥匙" in answer["answer"]


def test_npc_dialogue_chroma_recall_does_not_cross_owner_scope() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    answer = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "村议会担心谁抬价")

    assert "村议会担心商人伯林" not in answer["answer"]
    assert all(memory["source_event_id"] for memory in answer["memories"])


def test_npc_dialogue_is_logged_and_summarized_into_npc_memory() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    answer = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "你记得我出示过通行令吗")

    events = service.events(DEMO_VILLAGE_WORLD_ID)
    assert events[-2]["event_type"] == "NPC_DIALOGUE"
    assert events[-2]["payload"]["question"] == "你记得我出示过通行令吗"
    assert events[-1]["event_type"] == "ADD_MEMORY"
    assert answer["dialogue_event_id"] == events[-2]["id"]
    assert answer["created_memory_ids"]

    created = [memory for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "guard_alos") if memory["id"] in answer["created_memory_ids"]]
    assert created
    assert created[0]["truth_scope"] == "npc"
    assert created[0]["source_event_id"] == answer["dialogue_event_id"]
    assert "玩家问我" in created[0]["memory_text"]

    follow_up = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "你记得我刚才问过什么吗")

    assert any("玩家问我" in memory["memory_text"] for memory in follow_up["memories"])


def test_projector_rebuild_queries_do_not_leave_open_transaction() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    service.search_memories(DEMO_VILLAGE_WORLD_ID, "guard_alos", "不存在的检索词")
    service.search_evidence(DEMO_VILLAGE_WORLD_ID, "不存在的证据词")
    service.kuzu_graph(DEMO_VILLAGE_WORLD_ID)
    service.kuzu_neighbors(DEMO_VILLAGE_WORLD_ID, "guard_alos")

    result = service.turn(DEMO_VILLAGE_WORLD_ID, "和守卫交谈")

    assert result["accepted"] is True
