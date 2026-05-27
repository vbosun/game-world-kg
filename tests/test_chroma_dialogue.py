from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.memory import MemoryAwareDialogue
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService


class HallucinatingLLM:
    def complete_json(self, messages, *, temperature=0):
        return {"action_id": "talk_to_guard", "confidence": 0.9, "reason": "unused"}

    def complete_text(self, messages, *, temperature=0.4):
        return "不记得你做过什么，你上次来时只点了三杯酒，然后就匆匆走了。"


class CapturingDialogueLLM:
    def __init__(self) -> None:
        self.messages = []

    def complete_json(self, messages, *, temperature=0):
        return {"action_id": "talk_to_guard", "confidence": 0.9, "reason": "unused"}

    def complete_text(self, messages, *, temperature=0.4):
        self.messages = messages
        return "传闻银钥匙还在守卫那里。"


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


def test_memory_dialogue_prompt_marks_rumor_and_low_confidence_boundaries() -> None:
    conn = connect(":memory:")
    init_db(conn)
    llm = CapturingDialogueLLM()
    dialogue = MemoryAwareDialogue(conn, llm)

    dialogue._llm_answer(
        "guard_alos",
        "钥匙在哪",
        [{"memory_text": "有人说银钥匙在守卫那里。", "truth_scope": "rumor", "confidence": 0.4}],
        "fallback",
    )
    system = llm.messages[0]["content"]

    assert 'truth_scope="rumor"' in system
    assert "我听说" in system
    assert "confidence 较低" in system
    assert "不要把 npc/faction/rumor memory 说成 canonical truth" in system


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
    assert answer["segments"]
    assert answer["memory_ops"][0]["status"] == "applied"
    assert answer["memory_ops"][0]["scope_key"] == "npc_belief:guard_alos"
    assert events[-1]["payload"]["memory_kind"] == "dialogue_episode"
    assert events[-1]["payload"]["supporting_memory_ids"] == [memory["id"] for memory in answer["memories"]]

    created = [memory for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "guard_alos") if memory["id"] in answer["created_memory_ids"]]
    assert created
    assert created[0]["truth_scope"] == "npc"
    assert created[0]["scope_key"] == "npc_belief:guard_alos"
    assert created[0]["layer"] == "episodic"
    assert created[0]["memory_kind"] == "dialogue_episode"
    assert created[0]["source_event_id"] == answer["dialogue_event_id"]
    assert "玩家曾向我询问" in created[0]["memory_text"]
    assert "我回答" not in created[0]["memory_text"]

    follow_up = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "你记得我刚才问过什么吗")

    assert any("玩家曾向我询问" in memory["memory_text"] for memory in follow_up["memories"])


def test_npc_dialogue_does_not_persist_hallucinated_answer_without_memory_support() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn, HallucinatingLLM())

    answer = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "tavern_keeper_mira", "你记得我做过什么吗")

    assert answer["memories"] == []
    assert answer["answer"] == "我不知道这件事。"

    created = [
        memory
        for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "tavern_keeper_mira")
        if memory["id"] in answer["created_memory_ids"]
    ]
    assert created
    assert "三杯酒" not in created[0]["memory_text"]
    assert "我回答" not in created[0]["memory_text"]
    assert "玩家曾向我询问：你记得我做过什么吗" in created[0]["memory_text"]


def test_npc_dialogue_rumor_is_scoped_without_canonical_pollution() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    answer = service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "tavern_keeper_mira", "你听说银钥匙的谣言了吗")

    ops = answer["memory_ops"]
    assert {op["op_type"] for op in ops} == {"ADD_MEMORY", "FLAG_RUMOR"}
    assert any(op["scope_key"] == "rumor:village_square" and op["status"] == "applied" for op in ops)

    created = [
        memory
        for memory in service.memories(DEMO_VILLAGE_WORLD_ID, "tavern_keeper_mira")
        if memory["id"] in answer["created_memory_ids"]
    ]
    assert any(memory["truth_scope"] == "rumor" for memory in created)
    assert service.state(DEMO_VILLAGE_WORLD_ID)["silver_key"]["holder"] == "guard_alos"


def test_memory_query_returns_dev_metadata() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)
    service.npc_dialogue(DEMO_VILLAGE_WORLD_ID, "guard_alos", "你记得我出示过通行令吗")

    result = service.memory_query(DEMO_VILLAGE_WORLD_ID, "guard_alos", "通行令", mode="dev")

    assert result["mode"] == "dev"
    assert result["memories"]
    assert all("scope_key" in memory for memory in result["memories"])


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
