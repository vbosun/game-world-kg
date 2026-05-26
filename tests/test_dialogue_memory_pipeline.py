from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.dialogue_memory import DialogueMemoryPipeline, MemoryOp
from game_world_kg.events import EventLog
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world


def test_dialogue_memory_validator_sends_canonical_ops_to_review() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_VILLAGE_WORLD_ID, "npc_dialogue:guard_alos:test")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        dialogue_event = log.append(
            DEMO_VILLAGE_WORLD_ID,
            turn_id,
            turn["turn_index"],
            "NPC_DIALOGUE",
            "player",
            {"npc_id": "guard_alos", "question": "test", "answer": "test", "recalled_memory_ids": []},
            participants=["player", "guard_alos"],
        )
        pipeline = DialogueMemoryPipeline(conn)
        op = MemoryOp(
            op_type="ADD_MEMORY",
            layer="canonical",
            owner_id="guard_alos",
            scope_key="canonical",
            claim_key="illegal:canonical",
            memory_text="对话不能直接写真相。",
            confidence=0.9,
            segment_id="seg_test",
            evidence_refs=[{"source_id": dialogue_event.id, "span": [0, 4]}],
            payload={"memory_kind": "dialogue_episode"},
        )
        op_id = pipeline._store_op(DEMO_VILLAGE_WORLD_ID, dialogue_event.id, op)
        reason = pipeline._validate_op(op)
        assert reason == "dialogue_cannot_write_canonical"
        review = pipeline._append_review(DEMO_VILLAGE_WORLD_ID, dialogue_event.id, op_id, reason, op)
        pipeline._mark_op(op_id, "review", reason=reason)

    assert review["reason"] == "dialogue_cannot_write_canonical"
    assert pipeline.memory_ops(DEMO_VILLAGE_WORLD_ID, dialogue_event.id)[0]["status"] == "review"
    assert pipeline.review_items(DEMO_VILLAGE_WORLD_ID)[0]["memory_op_id"] == op_id
