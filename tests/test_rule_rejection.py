from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def test_rejection_reason_is_specific_not_generic() -> None:
    """Rejection should state specifically why, not just 'action rejected'."""
    service = _service()

    # Try to unlock gate without key — should fail with key-specific reason
    result = service.turn(DEMO_WORLD_ID, "我用钥匙打开铁门")
    assert result["accepted"] is False
    assert "钥匙" in result["reason"], f"rejection reason should mention missing key: {result['reason']}"


def test_affordances_available_after_rejection() -> None:
    """After a rejection, the player must still have actionable affordances."""
    service = _service()

    # A rejected action
    service.turn(DEMO_WORLD_ID, "我用钥匙打开铁门")

    # Check that affordances are still available
    affordances = service.affordances(DEMO_WORLD_ID)
    assert len(affordances) > 0, "player should still have affordances after rejection"


def test_consecutive_rejections_do_not_crash() -> None:
    """Multiple consecutive invalid actions must not crash or corrupt state."""
    service = _service()

    initial_state = service.state(DEMO_WORLD_ID)
    # Use actions that are known to fail precondition checks
    for i in range(5):
        result = service.turn(DEMO_WORLD_ID, "我掏出一把银钥匙打开铁门")
        assert result["accepted"] is False, f"iteration {i}: unlock without key should be rejected"
        assert result["events"] == []

    # State should be unchanged after all rejections
    state_after = service.state(DEMO_WORLD_ID)
    assert state_after["player"]["location"] == initial_state["player"]["location"]
    assert state_after["iron_gate"]["open"] is False


def test_rejection_then_valid_action_still_works() -> None:
    """After multiple rejections, a valid action must still succeed."""
    service = _service()

    # Several rejections
    service.turn(DEMO_WORLD_ID, "我飞过城门")
    service.turn(DEMO_WORLD_ID, "我用不存在的神器开门")

    # Then a valid action
    result = service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    assert result["accepted"] is True
    assert result["action_id"] == "show_pass_token"
    assert len(result["events"]) > 0


def test_play_turn_rejection_has_rule_rejection_in_changes() -> None:
    """play_turn rejection must include rule_rejection change with detail."""
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我召唤天神摧毁城门")

    rejection = next((c for c in result.get("changes", []) if c["type"] == "rule_rejection"), None)
    assert rejection is not None, "should have rule_rejection in changes"
    assert "detail" in rejection, "rule_rejection should have detail field"
    assert len(rejection["detail"]) > 0, "detail should not be empty"


def test_play_turn_rejection_still_returns_scene() -> None:
    """Even on rejection, play_turn should return a valid scene state."""
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我尝试不可能的事")

    # Should still return scene/state
    assert "scene" in result
    assert "affordances" in result or "next_affordances" in result
    # affordances should be non-empty so player can continue
    affordances = result.get("affordances") or result.get("next_affordances") or []
    assert len(affordances) > 0, "rejection must still provide actionable next steps"
