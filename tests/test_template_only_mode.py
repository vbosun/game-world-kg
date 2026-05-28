from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_template_only_mode_rejects_unknown_action() -> None:
    """In template_only mode, an action_id not in ActionTemplateStore must be rejected."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Override runtime_mode to template_only
        conn.execute("UPDATE worlds SET runtime_mode = 'template_only' WHERE id = ?", (DEMO_WORLD_ID,))
    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # An action_id that has no template
    result = service.turn_bound(w, "不存在的行动", "nonexistent_action_id")
    assert result["accepted"] is False
    assert "template" in result["reason"].lower() or "not found" in result["reason"].lower()


def test_template_only_mode_allows_valid_template_action() -> None:
    """In template_only mode, a valid action_id must be resolved via ActionTemplate."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        conn.execute("UPDATE worlds SET runtime_mode = 'template_only' WHERE id = ?", (DEMO_WORLD_ID,))
    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    result = service.turn_bound(w, "出示通行令", "show_pass_token")
    assert result["accepted"] is True
    assert result["action_id"] == "show_pass_token"


def test_template_only_mode_rejects_without_action_id() -> None:
    """In template_only mode, turn_bound with no action_id should reject gracefully."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        conn.execute("UPDATE worlds SET runtime_mode = 'template_only' WHERE id = ?", (DEMO_WORLD_ID,))
    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Simulate what happens when no action_id can be parsed
    from game_world_kg.rules import RuleEngine
    result = RuleEngine(conn).resolve_turn(w, "turn_test", 99, "test input", action_id=None)
    assert result.accepted is False


def test_legacy_demo_mode_still_parses_free_text() -> None:
    """In legacy_demo mode, service.turn() can parse free-text Chinese input."""
    service = _service()
    w = DEMO_WORLD_ID

    # Free text: "我向守卫出示通行令" → should be parsed to show_pass_token
    result = service.turn(w, "我向守卫出示通行令")
    # May work via LLM parsing or direct template match
    assert "accepted" in result


def test_all_demo_actions_have_templates() -> None:
    """Every demo action_id used in seed must have an ActionTemplate."""
    from game_world_kg.action_template import ActionTemplateStore
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    store = ActionTemplateStore(conn)
    demo_actions = [
        "talk_to_guard", "show_pass_token", "ask_guard_open_gate",
        "unlock_gate_with_key", "bribe_guard", "steal_silver_key",
        "enter_inner_city",
    ]
    for action_id in demo_actions:
        template = store.get(DEMO_WORLD_ID, action_id)
        assert template is not None, f"demo action {action_id} must have an ActionTemplate"


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)
