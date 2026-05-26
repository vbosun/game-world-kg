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
