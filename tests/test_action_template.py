from __future__ import annotations

import pytest

from game_world_kg.action_template import ActionResolver, ActionTemplateEngine, ActionTemplateStore
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world


@pytest.fixture()
def conn():
    db = connect(":memory:")
    init_db(db)
    with transaction(db):
        seed_demo_world(db)
    return db


def test_seed_writes_gate_action_templates(conn) -> None:
    templates = ActionTemplateStore(conn).list_enabled(DEMO_WORLD_ID)
    action_ids = {template.action_id for template in templates}

    assert len(templates) >= 7
    assert {"show_pass_token", "bribe_guard", "ask_guard_open_gate", "enter_inner_city"} <= action_ids


def test_template_engine_generates_affordances_from_preconditions(conn) -> None:
    affordances = ActionTemplateEngine(conn).list_for_actor(DEMO_WORLD_ID)
    ids = {item["action_id"] for item in affordances}

    assert "show_pass_token" in ids
    assert "bribe_guard" in ids
    assert "unlock_gate_with_key" not in ids
    assert "ask_guard_open_gate" not in ids


def test_action_resolver_executes_show_pass_token_template(conn) -> None:
    log = EventLog(conn)
    turn_id = log.create_turn(DEMO_WORLD_ID, "template show pass")
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()

    result = ActionResolver(conn).resolve(
        DEMO_WORLD_ID,
        turn_id,
        turn["turn_index"],
        "show_pass_token",
        [{"source_id": turn_id, "span": [0, 18], "extractor": "test", "confidence": 1.0}],
    )

    assert result is not None
    assert result.accepted is True
    assert [event.event_type for event in result.events] == ["TRANSFER_ITEM", "CHANGE_RELATION", "ADD_MEMORY"]
    pass_holder = conn.execute(
        "SELECT value_json FROM states WHERE world_id = ? AND entity_id = 'pass_token' AND attr = 'holder'",
        (DEMO_WORLD_ID,),
    ).fetchone()["value_json"]
    trust = conn.execute(
        "SELECT value_json FROM states WHERE world_id = ? AND entity_id = 'guard_alos' AND attr = 'trust.player'",
        (DEMO_WORLD_ID,),
    ).fetchone()["value_json"]
    assert pass_holder == '"guard_alos"'
    assert trust == "5"
