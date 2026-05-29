"""P3-01: Fail-forward experience deepening.

Verify:
- fail_forward produces at least one clue/relation/tension/memory push
- catastrophic doesn't also give success rewards
- success_with_cost clearly consumes resources or increases risk
"""
from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.projector import StateProjector, delta
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_fail_forward_creates_memory_or_clue() -> None:
    """FAIL_FORWARD must produce at least a memory, clue, or tension push."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "set_stealth", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "player", "attr": "skill.stealth", "value": 2},
            participants=["player"],
            state_deltas=[delta("player", "skill.stealth", None, 2)],
        )
        projector.apply_event(event)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # steal_silver_key with skill.stealth=2 → FAIL_FORWARD
    result = service.turn_bound(w, "偷", "steal_silver_key")
    assert result["accepted"] is True
    assert result["outcome"] == "fail_forward"

    # FAIL_FORWARD must produce at least one event that pushes the story forward
    events = service.events(w)
    turn_events = [e for e in events if e["turn_id"] == result["turn_id"]]
    event_types = {e["event_type"] for e in turn_events}

    # fail_effects of steal_silver_key: ADD_MEMORY (行迹可疑)
    assert "ADD_MEMORY" in event_types, \
        f"fail_forward should create memory: {event_types}"

    # The memory should be visible in the NPC's perspective
    memories = service.memories(w, "guard_alos")
    fail_memories = [m for m in memories if "行迹可疑" in m.get("memory_text", "")]
    assert len(fail_memories) >= 1, \
        f"fail_forward should write guard suspicion memory: {[m['memory_text'] for m in memories]}"


def test_catastrophic_does_not_apply_success_rewards() -> None:
    """CATASTROPHIC_FAILURE must apply catastrophic_effects, not success effects."""
    service = _service()
    w = DEMO_WORLD_ID

    initial_state = service.state(w)

    # steal_silver_key (high risk, skill=0 → CATASTROPHIC)
    result = service.turn_bound(w, "偷钥匙", "steal_silver_key")
    assert result["accepted"] is True
    assert result["outcome"] == "catastrophic_failure"

    state = service.state(w)

    # Success effects include hostility +2 and guard memory about attempt
    # Catastrophic effects include: hostility +5, gold -3, guard memory (公然), player memory
    # The silver_key should NOT have been transferred to player (no transfer_item effect)
    assert state["silver_key"]["holder"] == "guard_alos", \
        "catastrophic failure must not transfer key to player"

    # Hostility should be the catastrophic value (+5), not the success value (+2)
    assert state["guard_alos"]["hostility.player"] >= initial_state["guard_alos"]["hostility.player"] + 5, \
        "catastrophic hostility should be +5"

    # Player should have lost gold (catastrophic cost)
    assert state["player"]["gold"] < initial_state["player"]["gold"], \
        "catastrophic must consume gold"


def test_success_with_cost_applies_both_success_and_cost() -> None:
    """SUCCESS_WITH_COST must execute success effects followed by cost effects."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set skill.stealth=4 for SUCCESS_WITH_COST on steal (high risk)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "set_stealth", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "player", "attr": "skill.stealth", "value": 4},
            participants=["player"],
            state_deltas=[delta("player", "skill.stealth", None, 4)],
        )
        projector.apply_event(event)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    initial_gold = service.state(w)["player"]["gold"]

    result = service.turn_bound(w, "偷钥匙", "steal_silver_key")
    assert result["accepted"] is True
    assert result["outcome"] == "success_with_cost"

    state = service.state(w)
    # Success effects: hostility +2, add_memory
    # cost_effects: gold -1
    assert state["player"]["gold"] == initial_gold - 1, \
        f"SUCCESS_WITH_COST should apply cost_effects: gold -1; got gold={state['player']['gold']}"
    assert state["guard_alos"]["hostility.player"] >= 2, \
        "success effect: hostility should increase"
    assert result.get("costs"), "must include costs in result"


def test_full_success_does_not_incur_costs() -> None:
    """FULL_SUCCESS must not apply cost_effects or consume extra resources."""
    service = _service()
    w = DEMO_WORLD_ID

    initial_gold = service.state(w)["player"]["gold"]

    # show_pass_token is low risk → FULL_SUCCESS
    result = service.turn_bound(w, "出示通行令", "show_pass_token")
    assert result["accepted"] is True
    assert result["outcome"] == "full_success"

    # Gold should be unchanged (no cost effects applied)
    state = service.state(w)
    assert state["player"]["gold"] == initial_gold, \
        "FULL_SUCCESS should not consume resources in cost_effects"


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)
