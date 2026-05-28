from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.feedback_renderer import FeedbackRenderer
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


# ── four-layer feedback in play_turn ──────────────────────────────────


def test_play_turn_includes_all_four_feedback_layers() -> None:
    """play_turn response must include narration, changes, next_hooks, world_reactions."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    # Four feedback layers
    assert "feedback" in result, "play_turn must return feedback"
    assert "narration" in result["feedback"], "feedback must include narration"
    assert "changes" in result["feedback"], "feedback must include changes"
    assert "next_hooks" in result["feedback"], "feedback must include next_hooks"
    # world_reactions is at result level, not inside feedback
    assert "world_reactions" in result, "play_turn must return world_reactions layer"


def test_accepted_turn_produces_meaningful_changes() -> None:
    """An accepted action must produce at least one change."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    feedback = result["feedback"]
    assert len(feedback["changes"]) >= 1, f"accepted turn must produce changes: {feedback['changes']}"
    change_types = {c["type"] for c in feedback["changes"]}
    # show_pass_token: TRANSFER_ITEM→resource_change, CHANGE_RELATION→relationship_change, ADD_MEMORY→knowledge_change
    assert "resource_change" in change_types or "relationship_change" in change_types, \
        f"show_pass_token should produce resource or relationship change: {change_types}"


def test_changes_map_to_correct_layers() -> None:
    """Each change type must map to one of {narrative, mechanics, social, world}."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    layers = result["feedback"]["layers"]
    assert "narrative" in layers
    assert "mechanics" in layers
    assert "social" in layers
    assert "world" in layers

    # show_pass_token changes:
    # TRANSFER_ITEM → resource_change → mechanics
    # CHANGE_RELATION → relationship_change → social
    # ADD_MEMORY → knowledge_change → narrative
    # Also relationship growth → social
    # And skill growth → mechanics
    all_layer_changes = layers["narrative"] + layers["mechanics"] + layers["social"] + layers["world"]
    assert len(all_layer_changes) >= 1, "changes must be distributed across layers"


def test_next_hooks_provide_actionable_suggestions() -> None:
    """next_hooks must include available_action entries with action_id and label."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    hooks = result["feedback"]["next_hooks"]
    assert len(hooks) >= 1, f"next_hooks must have at least 1 suggestion: {hooks}"

    action_hooks = [h for h in hooks if h["type"] == "available_action"]
    assert len(action_hooks) >= 1, "must have available_action hooks"
    for hook in action_hooks:
        assert "action_id" in hook
        assert "label" in hook


def test_next_hooks_signal_relationship_change() -> None:
    """When relationship changes, next_hooks must include new_opportunity hint."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    hooks = result["feedback"]["next_hooks"]
    # show_pass_token changes guard_alos TRUSTS player +2 → relationship_change
    has_opportunity = any(h["type"] == "new_opportunity" for h in hooks)
    assert has_opportunity, f"relationship change should trigger new_opportunity hook: {hooks}"


# ── rejection feedback ────────────────────────────────────────────────


def test_rejection_feedback_includes_all_layers() -> None:
    """Even rejected turns must return feedback with narration, changes, next_hooks."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "我飞过城门")
    assert result["turn"]["accepted"] is False

    feedback = result["feedback"]
    assert "narration" in feedback
    assert len(feedback["narration"]) > 0
    assert "changes" in feedback
    assert len(feedback["changes"]) >= 1
    assert "next_hooks" in feedback
    assert len(feedback["next_hooks"]) >= 1


def test_rejection_changes_include_rule_rejection() -> None:
    """Rejection changes must include rule_rejection type."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "我召唤一座城")
    feedback = result["feedback"]

    rejection = next((c for c in feedback["changes"] if c["type"] == "rule_rejection"), None)
    assert rejection is not None, f"rejection must include rule_rejection in changes: {feedback['changes']}"


# ── feedback renderer unit tests ──────────────────────────────────────


def test_state_change_detected_from_before_after_diff() -> None:
    """FeedbackRenderer.changes must detect state diffs not covered by events."""
    renderer = FeedbackRenderer()
    events: list[dict] = []
    before = {"player": {"location": "village_gate"}}
    after = {"player": {"location": "inner_city"}}

    changes = renderer.changes(events, before, after)
    assert len(changes) >= 1
    location_change = next((c for c in changes if c.get("attr") == "location"), None)
    assert location_change is not None, f"should detect location diff: {changes}"
    assert location_change["from"] == "village_gate"
    assert location_change["to"] == "inner_city"


def test_no_state_change_fallback() -> None:
    """When no events and no state diffs, changes must include no_state_change."""
    renderer = FeedbackRenderer()
    events: list[dict] = []
    before = {"player": {"location": "village_gate"}}
    after = {"player": {"location": "village_gate"}}

    changes = renderer.changes(events, before, after)
    assert changes[0]["type"] == "no_state_change"


def test_feedback_includes_outcome_on_non_full_success() -> None:
    """When outcome is not full_success, feedback must include outcome info."""
    renderer = FeedbackRenderer()
    turn_result = {
        "accepted": True,
        "action_id": "bribe_guard",
        "narration": "test",
        "reason": "",
        "outcome": "success_with_cost",
        "events": [],
        "affordances": [],
    }
    before: dict[str, dict] = {"player": {}}
    after: dict[str, dict] = {"player": {}}

    feedback = renderer.render(turn_result, before, after)
    assert feedback["outcome"] == "success_with_cost"
    # changes should include the outcome change
    outcome_change = next((c for c in feedback["changes"] if c["type"] == "outcome"), None)
    assert outcome_change is not None


def test_layers_group_changes_by_type() -> None:
    """_build_layers must partition changes into 4 non-overlapping groups."""
    renderer = FeedbackRenderer()
    changes = [
        {"type": "knowledge_change", "label": "learned"},
        {"type": "state_change", "label": "changed"},
        {"type": "relationship_change", "label": "bonded"},
        {"type": "location_change", "label": "moved"},
        {"type": "unknown_weird", "label": "fallback"},
    ]
    layers = renderer._build_layers(changes, {})

    assert len(layers["narrative"]) == 1  # knowledge_change
    assert len(layers["mechanics"]) == 1  # state_change
    assert len(layers["social"]) == 1  # relationship_change
    assert len(layers["world"]) == 2  # location_change + fallback

    # Verify no overlap
    all_items = layers["narrative"] + layers["mechanics"] + layers["social"] + layers["world"]
    assert len(all_items) == len(changes), "every change must be in exactly one layer"
