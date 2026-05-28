from __future__ import annotations

from game_world_kg.action_template import ActionOutcome, _compute_outcome
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.projector import StateProjector, delta
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


# ── outcome computation ───────────────────────────────────────────────


def test_bribe_guard_is_success_with_cost_at_skill_zero() -> None:
    """Medium risk + skill=0 → SUCCESS_WITH_COST."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    from game_world_kg.action_template import ActionTemplateStore
    template = ActionTemplateStore(conn).get(DEMO_WORLD_ID, "bribe_guard")
    assert template is not None

    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.SUCCESS_WITH_COST, f"expected SUCCESS_WITH_COST, got {outcome}"


def test_bribe_guard_full_success_with_high_skill_and_trust() -> None:
    """Medium risk + effective>=2 → FULL_SUCCESS."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set skill.social=3 so effective = 3 + trust_bonus >= 2
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "set_skill", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "player", "attr": "skill.social", "value": 3},
            participants=["player"],
            state_deltas=[delta("player", "skill.social", None, 3)],
        )
        projector.apply_event(event)

    from game_world_kg.action_template import ActionTemplateStore
    template = ActionTemplateStore(conn).get(DEMO_WORLD_ID, "bribe_guard")
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.FULL_SUCCESS, f"expected FULL_SUCCESS, got {outcome}"


def test_steal_silver_key_catastrophic_at_skill_zero() -> None:
    """High risk + skill=0 → CATASTROPHIC_FAILURE."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    from game_world_kg.action_template import ActionTemplateStore
    template = ActionTemplateStore(conn).get(DEMO_WORLD_ID, "steal_silver_key")
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.CATASTROPHIC_FAILURE, f"expected CATASTROPHIC_FAILURE, got {outcome}"


def test_high_risk_fail_forward_at_moderate_skill() -> None:
    """High risk + effective=2 or 3 → FAIL_FORWARD."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set skill.stealth=2 so effective = 2 (no trust bonus since skill < 4)
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

    from game_world_kg.action_template import ActionTemplateStore
    template = ActionTemplateStore(conn).get(DEMO_WORLD_ID, "steal_silver_key")
    outcome = _compute_outcome(conn, DEMO_WORLD_ID, "player", "guard_alos", template, {"actor": "player", "target": "guard_alos"})
    assert outcome == ActionOutcome.FAIL_FORWARD, f"expected FAIL_FORWARD, got {outcome}"


# ── effect plan selection (end-to-end via turn_bound) ─────────────────


def test_catastrophic_failure_applies_catastrophic_effects() -> None:
    """CATASTROPHIC_FAILURE must execute catastrophic_effects, not main effects."""
    service = _service()
    w = DEMO_WORLD_ID

    initial_state = service.state(w)
    initial_hostility = initial_state["guard_alos"]["hostility.player"]
    initial_gold = initial_state["player"]["gold"]

    # High risk steal with skill=0 → CATASTROPHIC_FAILURE
    result = service.turn_bound(w, "偷钥匙", "steal_silver_key")

    assert result["accepted"] is True
    assert result["outcome"] == "catastrophic_failure"

    state_after = service.state(w)
    # Catastrophic effects: hostility +5 (not the main effect's +2)
    assert state_after["guard_alos"]["hostility.player"] >= initial_hostility + 5, \
        f"catastrophic should apply +5 hostility; got {state_after['guard_alos']['hostility.player']}"
    # Catastrophic effects: gold -3
    assert state_after["player"]["gold"] <= initial_gold - 3, \
        f"catastrophic should apply -3 gold; got {state_after['player']['gold']}"

    # Verify catastrophic guard_memory was written
    memories = service.memories(w, "guard_alos")
    memory_texts = [m["memory_text"] for m in memories]
    assert any("公然试图偷取银钥匙" in t for t in memory_texts), \
        f"catastrophic memory should be written: {memory_texts}"

    # Verify player memory (catastrophic adds player-scoped memory too)
    player_memories = service.memories(w, "player")
    player_texts = [m["memory_text"] for m in player_memories]
    assert any("偷钥匙" in t for t in player_texts), \
        f"catastrophic should add player memory: {player_texts}"


def test_success_with_cost_applies_cost_effects() -> None:
    """SUCCESS_WITH_COST must execute main effects + cost_effects."""
    service = _service()
    w = DEMO_WORLD_ID

    initial_state = service.state(w)
    initial_gold = initial_state["player"]["gold"]
    initial_trust = initial_state["guard_alos"]["trust.player"]

    # bribe_guard is medium risk, skill=0 → SUCCESS_WITH_COST
    result = service.turn_bound(w, "贿赂", "bribe_guard")

    assert result["accepted"] is True
    assert result["outcome"] == "success_with_cost"

    state_after = service.state(w)
    # Main effects: gold -1, reputation -1, trust +1
    assert state_after["player"]["gold"] == initial_gold - 1, \
        f"bribe main effect: -1 gold; got {state_after['player']['gold']}"
    assert state_after["guard_alos"]["trust.player"] == initial_trust + 1


def test_high_risk_success_with_cost_applies_cost_effects() -> None:
    """High risk + skill>=4 → SUCCESS_WITH_COST with cost_effects applied."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set skill.stealth=4 to trigger SUCCESS_WITH_COST for steal_silver_key
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

    # steal_silver_key with skill=4 → SUCCESS_WITH_COST
    result = service.turn_bound(w, "偷钥匙", "steal_silver_key")

    assert result["accepted"] is True
    assert result["outcome"] == "success_with_cost"

    state_after = service.state(w)
    # Main effects: hostility +2, memory
    # cost_effects: gold -1
    assert state_after["player"]["gold"] == initial_gold - 1, \
        f"SUCCESS_WITH_COST should apply cost_effects: gold -1; got {state_after['player']['gold']}"
    assert result.get("costs"), "must include costs in result"


def test_full_success_only_applies_main_effects() -> None:
    """FULL_SUCCESS must only apply main effects, no cost/fail/catastrophic."""
    service = _service()
    w = DEMO_WORLD_ID

    initial_state = service.state(w)
    initial_gold = initial_state["player"]["gold"]

    # show_pass_token is low risk → always FULL_SUCCESS
    result = service.turn_bound(w, "出示通行令", "show_pass_token")

    assert result["accepted"] is True
    assert result["outcome"] == "full_success"

    state_after = service.state(w)
    # Main effects: transfer pass_token, trust +2, add_memory (npc scope)
    # No cost effects — gold should be unchanged
    assert state_after["player"]["gold"] == initial_gold, \
        f"full_success should not apply cost effects; gold unchanged"
    assert state_after["guard_alos"]["trust.player"] == initial_state["guard_alos"]["trust.player"] + 2
    # pass_token transferred
    assert state_after["pass_token"]["holder"] == "guard_alos"


def test_fail_forward_applies_fail_effects() -> None:
    """FAIL_FORWARD must execute fail_effects instead of main effects."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set skill.stealth=2 to trigger FAIL_FORWARD for steal_silver_key (high risk)
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

    initial_state = service.state(w)
    initial_hostility = initial_state["guard_alos"]["hostility.player"]

    # steal_silver_key with skill.stealth=2 → FAIL_FORWARD
    result = service.turn_bound(w, "偷钥匙但失败", "steal_silver_key")

    assert result["accepted"] is True
    assert result["outcome"] == "fail_forward"

    state_after = service.state(w)
    # fail_effects only add a memory (no hostility change, no item transfer)
    # Main effects (hostility +2, add_memory) are NOT applied
    # But fail_effects add a guard suspicion memory
    memories = service.memories(w, "guard_alos")
    memory_texts = [m["memory_text"] for m in memories]
    assert any("行迹可疑" in t for t in memory_texts), \
        f"fail_forward should write fail memory: {memory_texts}"

    # Key should NOT be stolen (main effect not applied)
    assert state_after.get("silver_key", {}).get("holder") == "guard_alos", \
        "fail_forward should not transfer silver_key"


def test_outcome_reflected_in_play_turn_response() -> None:
    """play_turn must return outcome in turn dict and changes."""
    service = _service()
    w = DEMO_WORLD_ID

    # bribe_guard → SUCCESS_WITH_COST
    result = service.play_turn(w, "贿赂", selected_action_id="bribe_guard", selected_target_id="guard_alos")

    # Outcome is in feedback
    assert result["feedback"]["outcome"] == "success_with_cost"
    # changes should include outcome change
    changes = result["feedback"]["changes"]
    outcome_change = next((c for c in changes if c["type"] == "outcome"), None)
    assert outcome_change is not None, f"non-full-success must have outcome in changes: {changes}"
    assert outcome_change["outcome"] == "success_with_cost"


def test_rejected_action_has_no_outcome() -> None:
    """Rejected actions don't have outcome (outcome only applies to accepted)."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "我用不存在的神器开门")
    # Rejected turns should have no event-level outcome
    feedback = result["feedback"]
    assert not feedback.get("outcome") or feedback["outcome"] == "full_success", \
        f"rejection shouldn't set a failure outcome: {feedback.get('outcome')}"
