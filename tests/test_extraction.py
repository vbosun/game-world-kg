from __future__ import annotations

import pytest

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.extraction import ExtractionPipeline, RuleBasedExtractor, SchemaValidator, LLMExtractor
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


class FakeExtractionLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.json_calls = 0
        self.messages = []

    def complete_json(self, messages, *, temperature=0):
        self.json_calls += 1
        self.messages = messages
        return self.payload

    def complete_text(self, messages, *, temperature=0.4):
        return "fake"


@pytest.fixture()
def service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def test_rule_based_extractor_builds_schema_valid_candidate() -> None:
    candidate = RuleBasedExtractor().extract("log_001", "玩家把通行令递给守卫。")

    validation = SchemaValidator().validate(candidate)

    assert validation.passed is True
    assert candidate.action_id == "show_pass_token"
    assert candidate.scope == "canonical"
    assert candidate.evidence.source_id == "log_001"


def test_pipeline_writes_canonical_transfer_event(service: GameWorldService) -> None:
    result = ExtractionPipeline(service).process_text("log_001", "玩家把通行令递给守卫。")

    assert result["schema_pass"] is True
    assert result["accepted"] is True
    assert [event["event_type"] for event in result["events"]] == ["TRANSFER_ITEM", "CHANGE_RELATION", "ADD_MEMORY"]
    assert service.state(DEMO_WORLD_ID)["pass_token"]["holder"] == "guard_alos"
    assert result["events"][0]["evidence_refs"][0]["source_id"] == "log_001"


def test_pipeline_routes_rumor_without_canonical_pollution(service: GameWorldService) -> None:
    result = ExtractionPipeline(service).process_text("log_002", "村里有人说玩家偷了钥匙。")

    assert result["candidate"]["scope"] == "rumor"
    assert result["accepted"] is True
    assert result["memories"][0]["truth_scope"] == "rumor"
    assert service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos"


def test_pipeline_routes_subjective_suspicion_to_npc_memory(service: GameWorldService) -> None:
    result = ExtractionPipeline(service).process_text("log_003", "守卫怀疑玩家偷了钥匙。")

    assert result["candidate"]["scope"] == "npc"
    assert result["accepted"] is True
    assert result["memories"][0]["owner_id"] == "guard_alos"
    assert result["memories"][0]["truth_scope"] == "npc"
    assert service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos"


def test_pipeline_rejects_illegal_key_claim(service: GameWorldService) -> None:
    result = ExtractionPipeline(service).process_text("log_004", "玩家用并不存在的银钥匙打开铁门。")

    assert result["candidate"]["action_id"] == "unlock_gate_with_key"
    assert result["accepted"] is False
    assert result["events"] == []
    assert result["rejected"][0]["reason"] == "玩家没有银钥匙，不能用钥匙打开铁门。"
    assert service.state(DEMO_WORLD_ID)["iron_gate"]["open"] is False


def test_pipeline_uses_llm_extractor_for_ambiguous_subjective_text() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    fake_llm = FakeExtractionLLM({"action_id": "guard_suspects_player", "confidence": 0.88, "evidence_span": [0, 18]})
    service = GameWorldService(conn, fake_llm)

    result = ExtractionPipeline(service).process_text("log_llm_001", "阿洛斯皱眉，似乎仍觉得我和钥匙失窃有关。")

    assert fake_llm.json_calls == 1
    assert result["candidate"]["action_id"] == "guard_suspects_player"
    assert result["candidate"]["scope"] == "npc"
    assert result["candidate"]["evidence"]["extractor"] == "llm_extractor_v1"
    assert result["events"][0]["evidence_refs"][0]["source_id"] == "log_llm_001"
    assert result["events"][0]["evidence_refs"][0]["span"] == [0, 18]
    assert result["memories"][0]["truth_scope"] == "npc"
    assert service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos"


def test_pipeline_uses_llm_extractor_for_ambiguous_rumor_text() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    fake_llm = FakeExtractionLLM({"action_id": "rumor_player_stole_key", "confidence": 0.81, "evidence_span": [0, 20]})
    service = GameWorldService(conn, fake_llm)

    result = ExtractionPipeline(service).process_text("log_llm_002", "村口的人们小声议论，说我昨夜靠近过守卫室。")

    assert fake_llm.json_calls == 1
    assert result["candidate"]["scope"] == "rumor"
    assert result["memories"][0]["truth_scope"] == "rumor"
    assert service.state(DEMO_WORLD_ID)["silver_key"]["holder"] == "guard_alos"


def test_rule_extractor_takes_precedence_over_llm(service: GameWorldService) -> None:
    fake_llm = FakeExtractionLLM({"action_id": "unlock_gate_with_key", "confidence": 0.99, "evidence_span": [0, 10]})
    service.llm_client = fake_llm

    result = ExtractionPipeline(service).process_text("log_005", "玩家把通行令递给守卫。")

    assert fake_llm.json_calls == 0
    assert result["candidate"]["action_id"] == "show_pass_token"


def test_llm_extractor_expands_too_short_evidence_span(service: GameWorldService) -> None:
    fake_llm = FakeExtractionLLM({"action_id": "guard_suspects_player", "confidence": 0.9, "evidence_span": [0, 1]})

    candidate = LLMExtractor(fake_llm).extract("log_llm_003", "阿洛斯皱眉，似乎仍觉得我和钥匙失窃有关。", service.state(DEMO_WORLD_ID), service.graph(DEMO_WORLD_ID)["nodes"])

    assert candidate is not None
    assert candidate.evidence.span == (0, len(candidate.text))


def test_llm_extractor_prompt_marks_legacy_fixed_action_ids(service: GameWorldService) -> None:
    fake_llm = FakeExtractionLLM({"action_id": "guard_suspects_player", "confidence": 0.9, "evidence_span": [0, 18]})

    LLMExtractor(fake_llm).extract("log_llm_004", "阿洛斯怀疑我。", service.state(DEMO_WORLD_ID), service.graph(DEMO_WORLD_ID)["nodes"])
    system = fake_llm.messages[0]["content"]

    assert "旧日志抽取 PoC 路径" in system
    assert "不要发明动态 WorldSpec action_id" in system
    assert "不要决定是否进入 canonical" in system
