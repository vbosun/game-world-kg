from __future__ import annotations

import pytest

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.quest import QuestGenerator, QuestValidator
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


@pytest.fixture()
def service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def test_generates_gate_entry_and_trust_quests_from_initial_state(service: GameWorldService) -> None:
    quests = QuestGenerator(service).generate(DEMO_WORLD_ID)
    quest_ids = {quest["quest_id"] for quest in quests}

    assert "quest_gain_guard_trust" in quest_ids
    assert "quest_find_legal_entry" in quest_ids
    assert "quest_clear_key_theft_rumor" not in quest_ids


def test_generates_rumor_quest_when_rumor_exists(service: GameWorldService) -> None:
    service.turn(DEMO_WORLD_ID, "村里有人说玩家偷了钥匙")

    quests = QuestGenerator(service).generate(DEMO_WORLD_ID)
    rumor = next(quest for quest in quests if quest["quest_id"] == "quest_clear_key_theft_rumor")

    assert rumor["depends_on"]
    assert rumor["evidence"][0]["source_type"] == "memory"
    assert rumor["evidence"][0]["truth_scope"] == "rumor"


def test_generated_quests_are_valid_traceable_and_completable(service: GameWorldService) -> None:
    service.turn(DEMO_WORLD_ID, "村里有人说玩家偷了钥匙")
    quests = QuestGenerator(service).generate(DEMO_WORLD_ID)
    validations = [QuestValidator(service).validate(quest, DEMO_WORLD_ID) for quest in quests]

    assert quests
    assert all(item["dependency_valid"] for item in validations)
    assert all(item["traceable"] for item in validations)
    assert all(item["completable"] for item in validations)
    assert all(item["reward_valid"] for item in validations)
    assert all(item["failure_valid"] for item in validations)
    assert all(item["valid"] for item in validations)


def test_open_gate_removes_legal_entry_quest(service: GameWorldService) -> None:
    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    service.turn(DEMO_WORLD_ID, "请守卫放行让我进去")

    quest_ids = {quest["quest_id"] for quest in QuestGenerator(service).generate(DEMO_WORLD_ID)}

    assert "quest_find_legal_entry" not in quest_ids
