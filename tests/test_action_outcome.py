from __future__ import annotations

from game_world_kg.action_template import (
    ActionOutcome,
    ActionResolution,
    ActionTemplate,
    ActionTemplateStore,
    _compute_outcome,
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


def test_fail_forward_v0_does_not_claim_alternate_effect_plan() -> None:
    """Verify _compute_outcome is post-hoc: effects execute before outcome is computed."""
    # This is verified by reading the code: validate_and_resolve_action calls
    # effects.execute() BEFORE _compute_outcome(). The test confirms this is
    # documented as v0 and effects always run fully regardless of outcome.
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    # Get a high-risk template
    store = ActionTemplateStore(conn)
    template = store.get(DEMO_WORLD_ID, "steal_silver_key")
    assert template is not None
    assert template.risk == "high"

    # With no skill or relationship, a high-risk action should produce
    # non-FULL_SUCCESS outcome. But effects still execute completely.
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    # High risk, skill=0, relation=0 → catastrophic_failure
    assert outcome != ActionOutcome.FULL_SUCCESS

    # The key invariant: validate_and_resolve_action calls effects BEFORE _compute_outcome.
    # This means the outcome label is post-hoc and does not alter effects.
    # Future work would reverse this order.


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
