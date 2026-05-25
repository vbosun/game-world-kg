from __future__ import annotations

import pytest

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.extraction import ExtractionPipeline, RuleBasedExtractor, SchemaValidator
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


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
