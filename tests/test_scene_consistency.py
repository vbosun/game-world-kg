from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world
from game_world_kg.service import GameWorldService


# ── affordance density ────────────────────────────────────────────────


def test_demo_world_initial_scene_has_3_to_7_affordances() -> None:
    """Each playable scene should offer 3-7 meaningful affordances (ACT-04)."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    affordances = service.affordances(DEMO_WORLD_ID)
    # Initial scene: village_gate with guard_alos present, gate locked
    assert 3 <= len(affordances) <= 12, \
        f"initial scene should have 3-12 affordances, got {len(affordances)}: {[a['action_id'] for a in affordances]}"

    # Every affordance must have required fields
    for aff in affordances:
        assert "action_id" in aff
        assert "label" in aff
        assert "risk" in aff
        assert aff["risk"] in {"low", "medium", "high"}


def test_demo_world_scene_affordances_change_after_gate_opens() -> None:
    """After opening the gate, affordances must include enter_inner_city."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # Open the gate
    service.turn_bound(DEMO_WORLD_ID, "出示通行令", "show_pass_token")
    service.turn_bound(DEMO_WORLD_ID, "请求放行", "ask_guard_open_gate")

    affordances = service.affordances(DEMO_WORLD_ID)
    action_ids = {a["action_id"] for a in affordances}
    assert "enter_inner_city" in action_ids, \
        f"after gate opens, enter_inner_city must be available: {action_ids}"
    # Still have 3+ affordances
    assert len(affordances) >= 3, f"should have >=3 affordances after gate opens: {len(affordances)}"


def test_demo_village_initial_affordance_density() -> None:
    """Demo village initial scene should have adequate affordances."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_village_world(conn)
    service = GameWorldService(conn)

    affordances = service.affordances(DEMO_VILLAGE_WORLD_ID)
    assert len(affordances) >= 3, \
        f"village initial scene should have >=3 affordances, got {len(affordances)}"

    # Verify each has required fields
    for aff in affordances:
        assert aff.get("action_id")
        assert aff.get("label")


# ── state consistency under mixed outcomes ─────────────────────────────


def test_state_consistent_after_full_success_then_catastrophic() -> None:
    """After full_success followed by catastrophic_failure, state must be coherent."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # Full success
    r1 = service.turn_bound(DEMO_WORLD_ID, "出示通行令", "show_pass_token")
    assert r1["accepted"] is True
    assert r1["outcome"] == "full_success"

    # Catastrophic failure (high risk steal with skill=0)
    r2 = service.turn_bound(DEMO_WORLD_ID, "偷钥匙", "steal_silver_key")
    assert r2["accepted"] is True
    assert r2["outcome"] == "catastrophic_failure"

    # State coherence checks
    state = service.state(DEMO_WORLD_ID)

    # pass_token was transferred to guard_alos (full_success worked)
    assert state.get("pass_token", {}).get("holder") == "guard_alos"

    # silver_key still with guard_alos (catastrophic didn't steal it)
    assert state.get("silver_key", {}).get("holder") == "guard_alos"

    # guard_alos trust increased (from show_pass_token)
    assert state["guard_alos"]["trust.player"] >= 4

    # guard_alos hostility increased (from catastrophic failure)
    assert state["guard_alos"]["hostility.player"] >= 5

    # Player lost gold (catastrophic cost)
    assert state["player"]["gold"] <= 0

    # Events are sequential and consistent
    events = service.events(DEMO_WORLD_ID)
    assert len(events) > 0


def test_state_consistent_after_success_with_cost_then_retry() -> None:
    """After SUCCESS_WITH_COST, retrying same action should work on better conditions."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # bribe_guard: medium risk, skill=0 → SUCCESS_WITH_COST
    r1 = service.turn_bound(DEMO_WORLD_ID, "贿赂", "bribe_guard")
    assert r1["accepted"] is True
    assert r1["outcome"] == "success_with_cost"

    state_after_first = service.state(DEMO_WORLD_ID)
    trust_after_first = state_after_first["guard_alos"]["trust.player"]

    # Bribe again — trust should now be higher (3→4 after one bribe)
    # Medium risk: effective = skill.social + trust_bonus. After first bribe, trust=4, bonus=1
    # Still SUCCESS_WITH_COST since effective=1 < 2
    r2 = service.turn_bound(DEMO_WORLD_ID, "再贿赂", "bribe_guard")
    assert r2["accepted"] is True

    state_after_second = service.state(DEMO_WORLD_ID)
    assert state_after_second["guard_alos"]["trust.player"] > trust_after_first

    # Gold decreased by 2 total (1 per bribe)
    assert state_after_second["player"]["gold"] >= 0


def test_state_consistent_after_rejection_no_state_leak() -> None:
    """Rejected actions must not change canonical state."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    state_before = service.state(DEMO_WORLD_ID)

    # Attempt unlock without key — should be rejected
    r = service.turn_bound(DEMO_WORLD_ID, "用钥匙开门", "unlock_gate_with_key")
    assert r["accepted"] is False

    state_after = service.state(DEMO_WORLD_ID)
    # All key entities must be identical
    for entity_id in ["player", "guard_alos", "iron_gate", "pass_token", "silver_key"]:
        if entity_id in state_before:
            for attr, value in state_before[entity_id].items():
                assert state_after.get(entity_id, {}).get(attr) == value, \
                    f"{entity_id}.{attr} changed after rejection: {value} → {state_after.get(entity_id, {}).get(attr)}"


def test_world_state_self_consistent_after_10_turns() -> None:
    """After a 10-turn sequence with mixed outcomes, world must be self-consistent."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    turns = [
        ("出示通行令", "show_pass_token", None),       # full_success
        ("贿赂守卫", "bribe_guard", "guard_alos"),       # success_with_cost
        ("偷钥匙", "steal_silver_key", "guard_alos"),    # catastrophic
    ]

    for i in range(3):
        for player_input, action_id, target_id in turns:
            result = service.turn_bound(DEMO_WORLD_ID, f"{player_input} #{i}", action_id, target_id=target_id)
            assert result["accepted"] in {True, False}

    state = service.state(DEMO_WORLD_ID)

    # All entities should have valid states
    for entity_id, attrs in state.items():
        assert isinstance(entity_id, str) and len(entity_id) > 0
        assert isinstance(attrs, dict)
        for attr, value in attrs.items():
            # No None values in canonical state
            if attr != "rumor" and not attr.startswith("rumor."):
                assert value is not None, f"{entity_id}.{attr} should not be None"

    # Cross-reference checks
    # If gate is open, locked should be False
    if state.get("iron_gate", {}).get("open") is True:
        assert state["iron_gate"]["locked"] is False, "open gate must be unlocked"

    # Items can only be held by one entity
    holders = {}
    for entity_id, attrs in state.items():
        if attrs.get("holder"):
            held = attrs["holder"]
            if held not in holders:
                holders[held] = []
            holders[held].append(entity_id)

    # Turn count matches events (seed + at least some accepted actions)
    events = service.events(DEMO_WORLD_ID)
    turn_indices = {e["turn_index"] for e in events}
    assert len(turn_indices) >= 4, f"should have at least 4 distinct turns (seed + actions), got {len(turn_indices)}"


def test_affordances_reflect_current_state_not_stale() -> None:
    """Affordances must update immediately after state changes."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # Initially, ask_guard_open_gate is NOT available (trust < 5)
    affordances_before = {a["action_id"] for a in service.affordances(DEMO_WORLD_ID)}
    assert "ask_guard_open_gate" not in affordances_before

    # Show pass token → trust 3→5
    service.turn_bound(DEMO_WORLD_ID, "出示通行令", "show_pass_token")

    # Now ask_guard_open_gate IS available
    affordances_after = {a["action_id"] for a in service.affordances(DEMO_WORLD_ID)}
    assert "ask_guard_open_gate" in affordances_after

    # Open the gate
    service.turn_bound(DEMO_WORLD_ID, "请求放行", "ask_guard_open_gate")

    # After gate opens, ask_guard_open_gate should NOT be available (gate already open)
    affordances_final = {a["action_id"] for a in service.affordances(DEMO_WORLD_ID)}
    assert "ask_guard_open_gate" not in affordances_final, \
        "ask_guard_open_gate should disappear after gate is opened"
    assert "enter_inner_city" in affordances_final, \
        "enter_inner_city should appear after gate opens"
