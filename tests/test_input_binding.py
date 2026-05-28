from __future__ import annotations

from typing import Any

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service(llm: Any | None = None) -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn, llm)


def test_llm_target_mismatch_does_not_fallback() -> None:
    """P0-01: When LLM picks action_id X with target_id Y, and exact match fails,
    the system must NOT silently fall back to binding action_id X with a different target."""
    service = _service()

    # LLM wants to "show_pass_token" to "iron_gate" but iron_gate isn't a valid target for that action.
    # The exact (action_id, target_id) match should fail, and since candidate HAS a target_id,
    # the action_id-only fallback should NOT be used.
    result = service.play_turn(
        DEMO_WORLD_ID,
        "show pass to the gate",
        selected_action_id="show_pass_token",
        selected_target_id="iron_gate",
    )

    assert result["turn"]["accepted"] is False
    assert result["turn"]["action_id"] == "__unparsed__"


def test_exact_match_preferred_over_fuzzy() -> None:
    """When an affordance with exact (action_id, target_id) exists, it must be preferred
    over any action_id-only match."""
    service = _service()

    # First, show token to guard_alos which IS a valid current affordance
    result = service.play_turn(
        DEMO_WORLD_ID,
        "show pass token",
        selected_action_id="show_pass_token",
        selected_target_id="guard_alos",
    )

    assert result["turn"]["accepted"] is True
    assert result["turn"]["action_id"] == "show_pass_token"
    assert result["bound_action"]["target_id"] == "guard_alos"


def test_llm_parser_cannot_bind_to_non_current_affordance() -> None:
    """LLM-parsed action must be a current affordance. Even if the LLM generates
    a valid-looking action_id, it's rejected if not in the current affordance list."""
    service = _service()

    # "unlock_gate_with_key" exists as a template but is not a current affordance
    # because the player doesn't have the key
    result = service.play_turn(
        DEMO_WORLD_ID,
        "unlock gate with key",
        selected_action_id="unlock_gate_with_key",
        selected_target_id="iron_gate",
    )

    assert result["turn"]["accepted"] is False


def test_illegal_free_input_returns_rule_rejection_with_next_paths() -> None:
    """Free-text input that can't be parsed into a valid affordance should return
    a rule_rejection with suggested next paths."""
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我召唤一座不存在的空中城")

    rejection = next((c for c in result["changes"] if c["type"] == "rule_rejection"), None)
    assert rejection is not None
    # The response should include continuable paths even after rejection
    assert result.get("affordances") or result.get("next_affordances") or result.get("continuations") is not None


class MisleadingLLM:
    def complete_json(self, messages, *, temperature=0, timeout_seconds=None):
        return {"action_id": "unlock_gate_with_key", "target_id": "iron_gate", "confidence": 1.0, "reason": "forced"}

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        return "misleading response"


def test_selected_action_bypasses_llm_parser() -> None:
    """When selected_action_id is provided, the LLM action parser must NOT be called.
    The explicit user selection takes precedence."""
    llm = MisleadingLLM()
    service = _service(llm)

    result = service.play_turn(
        DEMO_WORLD_ID,
        "ignored free text",
        selected_action_id="show_pass_token",
        selected_target_id="guard_alos",
    )

    # The selected action is used, LLM is bypassed
    assert result["turn"]["accepted"] is True
    assert result["turn"]["action_id"] == "show_pass_token"
    assert result["bound_action"]["action_id"] == "show_pass_token"
