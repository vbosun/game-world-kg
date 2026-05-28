from __future__ import annotations

import pytest

from game_world_kg.action_template import (
    ActionOutcome,
    ActionResolver,
    ActionTemplate,
    ActionTemplateEngine,
    ActionTemplateStore,
    PredicateEvaluator,
    _compute_outcome,
)
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


def test_upsert_insert_and_update_template(conn) -> None:
    """upsert should create a new template on first call and update it on second."""
    store = ActionTemplateStore(conn)
    world_id = DEMO_WORLD_ID

    new_template = ActionTemplate(
        action_id="test_upsert_action",
        label="测试 upsert",
        target_id=None,
        risk="low",
        reason="upsert 测试",
        preconditions=[],
        effects=[],
    )
    store.upsert(world_id, new_template)
    fetched = store.get(world_id, "test_upsert_action")
    assert fetched is not None
    assert fetched.label == "测试 upsert"
    assert fetched.risk == "low"

    updated = ActionTemplate(
        action_id="test_upsert_action",
        label="测试 upsert 更新",
        target_id="some_target",
        risk="high",
        reason="更新后的 reason",
        preconditions=[{"type": "same_location", "a": "$actor", "b": "$target"}],
        effects=[{"type": "set_state", "entity": "$target", "attr": "tested", "value": True, "actor": "$actor"}],
        cost_effects=[{"type": "delta_resource", "entity": "$actor", "attr": "gold", "delta": -1, "actor": "system"}],
    )
    store.upsert(world_id, updated)
    fetched2 = store.get(world_id, "test_upsert_action")
    assert fetched2 is not None
    assert fetched2.label == "测试 upsert 更新"
    assert fetched2.risk == "high"
    assert fetched2.target_id == "some_target"
    assert len(fetched2.preconditions) == 1
    assert len(fetched2.cost_effects) == 1


def test_disabled_template_not_in_affordances(conn) -> None:
    """A template with enabled=0 should not appear in list_enabled or affordances."""
    store = ActionTemplateStore(conn)
    world_id = DEMO_WORLD_ID

    store.upsert(world_id, ActionTemplate(
        action_id="disabled_test",
        label="应被禁用",
        target_id=None,
        risk="low",
        reason="test",
        preconditions=[],
        effects=[],
    ))
    conn.execute(
        "UPDATE action_templates SET enabled = 0 WHERE world_id = ? AND action_id = ?",
        (world_id, "disabled_test"),
    )
    enabled = store.list_enabled(world_id)
    assert "disabled_test" not in {t.action_id for t in enabled}

    affordances = ActionTemplateEngine(conn).list_for_actor(world_id)
    assert "disabled_test" not in {a["action_id"] for a in affordances}


def test_medium_risk_outcome_matrix(conn) -> None:
    """Medium risk actions produce FULL_SUCCESS or SUCCESS_WITH_COST based on skill+relation."""
    template = ActionTemplate(
        action_id="bribe_test",
        label="贿赂",
        target_id="guard_alos",
        risk="medium",
        reason="test",
        preconditions=[],
        effects=[],
    )

    # skill=0, relation=0 → effective=0 → SUCCESS_WITH_COST
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.SUCCESS_WITH_COST

    # After show_pass_token, trust=5 → relation_bonus=2 → effective=2 → FULL_SUCCESS
    log = EventLog(conn)
    turn_id = log.create_turn(DEMO_WORLD_ID, "build trust")
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    ActionResolver(conn).resolve(
        DEMO_WORLD_ID, turn_id, turn["turn_index"], "show_pass_token",
        [{"source_id": turn_id, "span": [0, 1], "extractor": "test", "confidence": 1.0}],
    )
    outcome2 = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome2 == ActionOutcome.FULL_SUCCESS


def test_low_risk_always_full_success(conn) -> None:
    """Low risk actions always produce FULL_SUCCESS regardless of skill."""
    template = ActionTemplate(
        action_id="talk_low_risk", label="交谈", target_id="guard_alos", risk="low",
        reason="test", preconditions=[], effects=[],
    )
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.FULL_SUCCESS


def test_high_risk_skill_zero_is_catastrophic(conn) -> None:
    """High risk with skill=0 and relation=0 produces CATASTROPHIC_FAILURE."""
    template = ActionTemplate(
        action_id="steal_high_risk", label="偷窃", target_id="guard_alos", risk="high",
        reason="test", preconditions=[], effects=[],
    )
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.CATASTROPHIC_FAILURE


def test_list_for_actor_npc_includes_appropriate_actions(conn) -> None:
    """NPC actor should get appropriate affordances, not player-only ones."""
    player_affordances = {a["action_id"] for a in ActionTemplateEngine(conn).list_for_actor(DEMO_WORLD_ID, "player")}
    guard_affordances = {a["action_id"] for a in ActionTemplateEngine(conn).list_for_actor(DEMO_WORLD_ID, "guard_alos")}

    # Guard shouldn't have player-exclusive actions
    assert "patrol" not in guard_affordances
    assert "report_to_faction" not in guard_affordances
    # Both should have common actions
    assert "talk_to_guard" in player_affordances
    # Guard should have some available actions
    assert len(guard_affordances) > 0


def test_unknown_predicate_type_raises(conn) -> None:
    """Unknown predicate type must raise ValueError."""
    evaluator = PredicateEvaluator(conn)
    with pytest.raises(ValueError, match="unknown predicate type"):
        evaluator.evaluate(DEMO_WORLD_ID, {"type": "nonexistent_predicate"}, {"actor": "player"})


def test_action_resolver_rejects_on_failed_precondition(conn) -> None:
    """ActionResolver returns rejected ActionResolution when precondition fails."""
    log = EventLog(conn)
    turn_id = log.create_turn(DEMO_WORLD_ID, "try unlock without key")
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()

    result = ActionResolver(conn).resolve(
        DEMO_WORLD_ID, turn_id, turn["turn_index"],
        "unlock_gate_with_key",
        [{"source_id": turn_id, "span": [0, 1], "extractor": "test", "confidence": 1.0}],
    )
    assert result is not None
    assert result.accepted is False
    assert len(result.events) == 0
    # Rejection reason should mention the precondition failure
    assert "钥匙" in result.reason
