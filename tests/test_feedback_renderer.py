from __future__ import annotations

from game_world_kg.feedback_renderer import FeedbackRenderer


def test_player_growth_reads_growth_lines() -> None:
    """PLAYER_GROWTH feedback must read payload.growth_lines, not old attr/delta fields."""
    renderer = FeedbackRenderer()

    events: list[dict[str, Any]] = [
        {
            "event_type": "PLAYER_GROWTH",
            "payload": {
                "action_id": "help_sort_herbs",
                "growth_lines": [
                    {"line": "skill", "attr": "skill.herbalism", "delta": 1, "event_type": "skill_growth"},
                    {"line": "permission", "permission": "pharmacy_backroom", "event_type": "permission_growth"},
                    {"line": "identity", "tag": "healer_apprentice", "event_type": "identity_growth"},
                ],
            },
        },
    ]
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}

    changes = renderer.changes(events, before, after)

    assert len(changes) == 3
    change_types = {c["type"] for c in changes}
    assert "growth" in change_types
    assert "permission_change" in change_types
    assert "identity_change" in change_types

    skill_change = next(c for c in changes if c["line"] == "skill")
    assert skill_change["attr"] == "skill.herbalism"
    assert skill_change["delta"] == 1

    permission_change = next(c for c in changes if c["line"] == "permission")
    assert permission_change["permission"] == "pharmacy_backroom"

    identity_change = next(c for c in changes if c["line"] == "identity")
    assert identity_change["tag"] == "healer_apprentice"


def test_player_growth_layers_classify_lines_correctly() -> None:
    """Growth lines must land in correct layers: identity/social, permission/mechanics, etc."""
    renderer = FeedbackRenderer()

    events: list[dict[str, Any]] = [
        {
            "event_type": "PLAYER_GROWTH",
            "payload": {
                "action_id": "test_action",
                "growth_lines": [
                    {"line": "identity", "tag": "trusted_visitor", "event_type": "identity_growth"},
                    {"line": "relationship", "src": "guard_alos", "rel": "TRUSTS", "dst": "player", "delta": 2, "event_type": "relationship_growth"},
                    {"line": "knowledge", "clue": "secret_entrance", "event_type": "knowledge_growth"},
                    {"line": "permission", "permission": "back_door", "event_type": "permission_growth"},
                    {"line": "skill", "attr": "skill.social", "delta": 1, "event_type": "skill_growth"},
                ],
            },
        },
    ]
    before: dict[str, dict[str, Any]] = {"player": {}}
    after: dict[str, dict[str, Any]] = {"player": {}}

    changes = renderer.changes(events, before, after)
    layers = renderer._build_layers(changes, {})

    assert len(changes) == 5
    assert len(layers["narrative"]) >= 1, "knowledge should be in narrative"
    assert len(layers["mechanics"]) >= 2, "permission + skill should be in mechanics"
    assert len(layers["social"]) >= 2, "identity + relationship should be in social"

    narrative_types = {c["line"] for c in layers["narrative"]}
    assert "knowledge" in narrative_types

    mechanics_types = {c["line"] for c in layers["mechanics"]}
    assert "permission" in mechanics_types
    assert "skill" in mechanics_types

    social_types = {c["line"] for c in layers["social"]}
    assert "identity" in social_types
    assert "relationship" in social_types


def test_player_growth_empty_lines_no_crash() -> None:
    """Empty growth_lines should not crash."""
    renderer = FeedbackRenderer()
    events: list[dict[str, Any]] = [
        {"event_type": "PLAYER_GROWTH", "payload": {"action_id": "test", "growth_lines": []}},
    ]
    changes = renderer.changes(events, {"player": {"location": "tea_stall"}}, {"player": {"location": "tea_stall"}})
    # With empty growth_lines and no state diffs, we get the no_state_change fallback
    assert changes[0]["type"] == "no_state_change"
