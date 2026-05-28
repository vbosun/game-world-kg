from __future__ import annotations

from game_world_kg.action_template import (
    ActionOutcome,
    ActionResolution,
    ActionTemplate,
    ActionTemplateStore,
    _compute_outcome,
    validate_and_resolve_action,
)
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.feedback_renderer import FeedbackRenderer
from game_world_kg.projector import StateProjector
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_outcome_is_reported_in_feedback_layers() -> None:
    """When outcome is not full_success, feedback layers must show it."""
    renderer = FeedbackRenderer()

    turn_result = {
        "accepted": True,
        "action_id": "test_action",
        "narration": "test",
        "reason": "ok",
        "outcome": "success_with_cost",
        "events": [],
        "affordances": [],
    }
    before = {"player": {}}
    after = {"player": {}}

    feedback = renderer.render(turn_result, before, after)

    # Flat changes should have outcome at position 0
    assert feedback["changes"][0]["type"] == "outcome"
    assert feedback["changes"][0]["outcome"] == "success_with_cost"

    # Layers should also have outcome
    narrative = feedback["layers"]["narrative"]
    outcome_in_narrative = any(c["type"] == "outcome" for c in narrative)
    assert outcome_in_narrative, "narrative layer should contain outcome"


def test_fail_forward_effect_plan_selection() -> None:
    """Outcome is computed BEFORE effects; catastrophic_failure selects alternate effects."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    store = ActionTemplateStore(conn)
    template = store.get(DEMO_WORLD_ID, "steal_silver_key")
    assert template is not None
    assert template.risk == "high"
    # Template has catastrophic_effects defined
    assert len(template.catastrophic_effects) > 0

    # High risk, skill=0, relation=0 → catastrophic_failure
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.CATASTROPHIC_FAILURE

    # validate_and_resolve_action now computes outcome BEFORE executing effects
    # and selects the appropriate effect plan (catastrophic_effects in this case)
    log = EventLog(conn)
    turn_id = log.create_turn(DEMO_WORLD_ID, "test_theft")
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    resolution = validate_and_resolve_action(
        conn, DEMO_WORLD_ID, turn_id, turn["turn_index"],
        "steal_silver_key", [], actor_id="player", target_id="guard_alos",
    )
    assert resolution is not None
    assert resolution.accepted is True
    assert resolution.outcome == ActionOutcome.CATASTROPHIC_FAILURE
    assert len(resolution.costs) > 0
    # Catastrophic effects include hostility +5 (not just the +2 from main effects)
    state = StateProjector(conn)
    hostility = state.get_state(DEMO_WORLD_ID, "guard_alos", "hostility.player")
    assert hostility >= 5


def test_full_success_outcome_not_added_to_changes() -> None:
    """Full success outcome should not pollute changes with an outcome entry."""
    renderer = FeedbackRenderer()
    turn_result: dict[str, object] = {
        "accepted": True,
        "action_id": "test",
        "narration": "ok",
        "reason": "ok",
        "outcome": "full_success",
        "events": [],
        "affordances": [],
    }
    before: dict[str, dict[str, object]] = {"player": {}}
    after: dict[str, dict[str, object]] = {"player": {}}
    feedback = renderer.render(turn_result, before, after)
    # No outcome entry since it's full_success
    outcome_entries = [c for c in feedback["changes"] if c.get("type") == "outcome"]
    assert len(outcome_entries) == 0
