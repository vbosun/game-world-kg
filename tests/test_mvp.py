from __future__ import annotations

import sqlite3

import pytest

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.service import GameWorldService
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world


class FakeLLM:
    def __init__(self, action_id: str = "talk_to_guard", narration: str = "AI 旁白。") -> None:
        self.action_id = action_id
        self.narration = narration
        self.json_calls = 0
        self.text_calls = 0

    def complete_json(self, messages, *, temperature=0):
        self.json_calls += 1
        return {"action_id": self.action_id, "confidence": 0.99, "reason": "fake parser"}

    def complete_text(self, messages, *, temperature=0.4):
        self.text_calls += 1
        return self.narration


@pytest.fixture()
def service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def test_seed_world_has_initial_gate_state(service: GameWorldService) -> None:
    state = service.state(DEMO_WORLD_ID)

    assert state["player"]["location"] == "village_gate"
    assert state["guard_alos"]["location"] == "village_gate"
    assert state["iron_gate"]["locked"] is True
    assert state["iron_gate"]["open"] is False
    assert state["pass_token"]["holder"] == "player"
    assert state["silver_key"]["holder"] == "guard_alos"
    assert state["guard_alos"]["trust.player"] == 3


def test_affordances_block_key_but_allow_pass_token(service: GameWorldService) -> None:
    affordance_ids = {item["action_id"] for item in service.affordances(DEMO_WORLD_ID)}

    assert "show_pass_token" in affordance_ids
    assert "unlock_gate_with_key" not in affordance_ids
    assert "ask_guard_open_gate" not in affordance_ids


def test_showing_pass_token_writes_events_memory_and_unlocks_trust_affordance(service: GameWorldService) -> None:
    result = service.turn(DEMO_WORLD_ID, "我把通行令递给守卫，问他能不能放我进去")

    assert result["accepted"] is True
    assert [event["event_type"] for event in result["events"]] == ["TRANSFER_ITEM", "CHANGE_RELATION", "ADD_MEMORY"]
    state = service.state(DEMO_WORLD_ID)
    assert state["pass_token"]["holder"] == "guard_alos"
    assert state["guard_alos"]["trust.player"] == 5
    assert any(memory["owner_id"] == "guard_alos" and memory["truth_scope"] == "npc" for memory in service.memories(DEMO_WORLD_ID))
    assert "ask_guard_open_gate" in {item["action_id"] for item in result["affordances"]}


def test_guard_opens_gate_only_after_trust_threshold(service: GameWorldService) -> None:
    rejected = service.turn(DEMO_WORLD_ID, "请守卫放行让我进去")
    assert rejected["accepted"] is False
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is False

    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    accepted = service.turn(DEMO_WORLD_ID, "请守卫放行让我进去")
    assert accepted["accepted"] is True
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is True


def test_bribe_increases_trust_and_reduces_reputation(service: GameWorldService) -> None:
    result = service.turn(DEMO_WORLD_ID, "我拿出钱袋贿赂守卫")

    assert result["accepted"] is True
    state = service.state(DEMO_WORLD_ID)
    assert state["guard_alos"]["trust.player"] == 4
    assert state["player"]["reputation"] == -1
    assert state["player"]["gold"] == 2


def test_failed_key_theft_adds_hostility_without_transferring_key(service: GameWorldService) -> None:
    result = service.turn(DEMO_WORLD_ID, "我试图偷守卫的银钥匙")

    assert result["accepted"] is True
    state = service.state(DEMO_WORLD_ID)
    assert state["silver_key"]["holder"] == "guard_alos"
    assert state["guard_alos"]["hostility.player"] == 2


def test_rumor_does_not_pollute_canonical_state(service: GameWorldService) -> None:
    result = service.turn(DEMO_WORLD_ID, "村里有人说玩家偷了钥匙")

    assert result["accepted"] is True
    assert service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos"
    memories = service.memories(DEMO_WORLD_ID)
    assert any(memory["truth_scope"] == "rumor" for memory in memories)


def test_replay_to_turn_restores_state(service: GameWorldService) -> None:
    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    service.turn(DEMO_WORLD_ID, "请守卫放行让我进去")
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is True

    replayed = service.replay(DEMO_WORLD_ID, to_turn=1)

    assert replayed["state"]["pass_token"]["holder"] == "guard_alos"
    assert replayed["state"]["guard_alos"]["trust.player"] == 5
    assert replayed["state"]["iron_gate"]["open"] is False


def test_missing_key_cannot_open_gate(service: GameWorldService) -> None:
    result = service.turn(DEMO_WORLD_ID, "我掏出一把银钥匙打开铁门")

    assert result["accepted"] is False
    assert result["events"] == []
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is False


def test_llm_candidate_cannot_bypass_rules() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    fake_llm = FakeLLM(action_id="unlock_gate_with_key", narration="规则拦截了开门。")
    service = GameWorldService(conn, fake_llm)

    result = service.turn(DEMO_WORLD_ID, "我说服铁门自己打开")

    assert result["accepted"] is False
    assert result["action_id"] == "unlock_gate_with_key"
    assert result["events"] == []
    assert result["narration"] == "规则拦截了开门。"
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is False
    assert fake_llm.json_calls == 1
    assert fake_llm.text_calls == 1


def test_replay_does_not_call_llm() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    fake_llm = FakeLLM(action_id="show_pass_token")
    service = GameWorldService(conn, fake_llm)
    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    json_calls = fake_llm.json_calls
    text_calls = fake_llm.text_calls

    service.replay(DEMO_WORLD_ID, to_turn=1)

    assert fake_llm.json_calls == json_calls
    assert fake_llm.text_calls == text_calls
