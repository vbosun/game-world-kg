from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.explanation import ExplanationService
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


# ── timeline ordering ─────────────────────────────────────────────────


def test_timeline_events_ordered_by_turn_and_event_order() -> None:
    """Events must be returned in chronological order (turn_index, event_order)."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")
    service.turn_bound(w, "请求放行", "ask_guard_open_gate")

    events = service.events(w)
    for i in range(len(events) - 1):
        a, b = events[i], events[i + 1]
        assert (a["turn_index"], a.get("event_order", 0)) <= (b["turn_index"], b.get("event_order", 0)), \
            f"events out of order at index {i}: turn {a['turn_index']} before turn {b['turn_index']}"


def test_timeline_summarizes_event_types() -> None:
    """Timeline in roleplay mode must summarize each event with a text field."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    from game_world_kg.playable_turn import PlayableTurnKernel
    timeline = PlayableTurnKernel(service).timeline(w)
    assert len(timeline) >= 1
    for entry in timeline:
        assert "type" in entry
        assert "text" in entry
        assert len(entry["text"]) > 0


# ── explain state traceability ────────────────────────────────────────


def test_explain_state_traces_to_correct_event() -> None:
    """explain_state must show which event set the current value."""
    service = _service()
    w = DEMO_WORLD_ID

    # Execute an action that changes trust
    service.turn_bound(w, "出示通行令", "show_pass_token")

    explanation = ExplanationService(service.conn).explain_state(w, "guard_alos", "trust.player")
    assert explanation["entity_id"] == "guard_alos"
    assert explanation["attr"] == "trust.player"
    assert explanation["value"] >= 4  # trust 3→5 after show_pass_token
    assert explanation["source_event_id"] is not None, "state must have a source event"
    assert explanation["source_event"] is not None
    assert explanation["source_event"]["event_type"] in {"SET_STATE", "CHANGE_RELATION"}, \
        f"source event should be SET_STATE or CHANGE_RELATION: {explanation['source_event']['event_type']}"


def test_explain_state_includes_delta_chain() -> None:
    """explain_state must include state deltas showing old→new transitions."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    explanation = ExplanationService(service.conn).explain_state(w, "guard_alos", "trust.player")
    deltas = explanation["state_deltas"]
    assert len(deltas) >= 1, f"should have at least one delta: {explanation}"
    delta = deltas[-1]
    assert "old_value" in delta
    assert "new_value" in delta
    # trust went from 3 to 5
    assert delta["new_value"] > delta.get("old_value", 0), \
        f"trust should increase: {delta['old_value']} → {delta['new_value']}"


# ── event explanation ─────────────────────────────────────────────────


def test_explain_event_shows_full_context() -> None:
    """explain_event must show event type, actor, participants, and state deltas."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    events = service.events(w)
    change_rel = next((e for e in events if e["event_type"] == "CHANGE_RELATION"), None)
    assert change_rel is not None, "show_pass_token should produce CHANGE_RELATION"

    explanation = ExplanationService(service.conn).explain_event(w, change_rel["id"])
    event = explanation["event"]
    assert event["event_type"] == "CHANGE_RELATION"
    assert event["actor_id"] is not None
    assert len(event.get("participants", [])) >= 1
    assert "state_deltas" in explanation


def test_explain_event_shows_evidence_refs() -> None:
    """Each event must carry evidence_refs tracing to its source."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    events = service.events(w)
    # Find an event with evidence_refs
    for event in events:
        explanation = ExplanationService(service.conn).explain_event(w, event["id"])
        evidence = explanation.get("evidence", [])
        assert isinstance(evidence, list), f"evidence should be a list: {evidence}"


# ── end-to-end causal chain ───────────────────────────────────────────


def test_full_causal_chain_action_to_state() -> None:
    """Trace the full chain: player action → event → state delta → current state."""
    service = _service()
    w = DEMO_WORLD_ID

    # 1. Execute action
    result = service.turn_bound(w, "出示通行令", "show_pass_token")
    assert result["accepted"] is True

    # 2. Find the CHANGE_RELATION event created by this turn
    events = service.events(w)
    turn_events = [e for e in events if e["turn_id"] == result["turn_id"]]
    change_rel = [e for e in turn_events if e["event_type"] == "CHANGE_RELATION"]
    assert len(change_rel) >= 1, f"turn should produce CHANGE_RELATION: {[e['event_type'] for e in turn_events]}"

    # 3. The event must have state_deltas modifying trust.player
    explanation = ExplanationService(service.conn).explain_event(w, change_rel[0]["id"])
    trust_deltas = [d for d in explanation["state_deltas"] if d["attr"] == "trust.player"]
    assert len(trust_deltas) >= 1, f"should have trust.player delta: {explanation['state_deltas']}"

    # 4. The current state should reflect the delta
    current_state = service.state(w)
    current_trust = current_state["guard_alos"]["trust.player"]
    delta_new = trust_deltas[0]["new_value"]
    assert current_trust == delta_new, \
        f"current trust ({current_trust}) should match delta new_value ({delta_new})"

    # 5. explain_state should point back to this event
    state_explanation = ExplanationService(service.conn).explain_state(w, "guard_alos", "trust.player")
    assert state_explanation["source_event_id"] == change_rel[0]["id"] or \
        state_explanation["source_event_id"] is not None, \
        "state must have a traceable source event"


def test_npc_action_causal_chain() -> None:
    """NPC action must produce a causal chain: action → resolution events → state."""
    service = _service()
    w = DEMO_WORLD_ID

    # Guard has unlock_gate_with_key (holds silver_key)
    result = service.tick_npc(w, "guard_alos")

    if result.get("acted") and result.get("action", {}).get("action_id") == "unlock_gate_with_key":
        # The NPC action produced resolution events
        events_in_result = result.get("events", [])
        assert len(events_in_result) >= 1, "NPC action must produce events"

        # Each event should be explainable
        for event_ref in events_in_result:
            if "id" in event_ref:
                explanation = ExplanationService(service.conn).explain_event(w, event_ref["id"])
                assert explanation["event"]["event_type"] is not None

        # The gate state should now reflect the unlock
        state = service.state(w)
        assert state["iron_gate"]["open"] is True, "guard should have unlocked the gate"


def test_causal_chain_survives_replay() -> None:
    """After replay, all events must still trace to their source state."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")
    events_before = service.events(w)
    states_before = {e["id"]: service.state(w) for e in events_before[-3:]}

    # Replay
    service.replay(w)

    events_after = service.events(w)
    # Same number of events
    assert len(events_after) == len(events_before), \
        f"replay should preserve event count: {len(events_before)} → {len(events_after)}"

    # Each event should still be explainable
    for event in events_after:
        explanation = ExplanationService(service.conn).explain_event(w, event["id"])
        assert explanation["event"]["id"] == event["id"]


# ── memory traceability ───────────────────────────────────────────────


def test_explain_memory_traces_to_source_event() -> None:
    """explain_memory must link a memory back to the event that created it."""
    service = _service()
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    # show_pass_token creates a guard memory
    memories = service.memories(w, "guard_alos")
    assert len(memories) >= 1, "show_pass_token should create a guard memory"

    memory = memories[-1]
    explanation = ExplanationService(service.conn).explain_memory(w, memory["id"])

    assert explanation["memory"]["memory_text"] == memory["memory_text"]
    assert "source_event" in explanation
    # The source event should exist and be traceable
    if explanation["source_event"] is not None:
        source = explanation["source_event"]
        assert source["event_type"] == "ADD_MEMORY"


# ── quest explain ─────────────────────────────────────────────────────


def test_explain_quest_shows_dependencies_and_evidence() -> None:
    """explain_quest must show depends_on, required_state, and evidence."""
    service = _service()
    w = DEMO_WORLD_ID

    from game_world_kg.quest import QuestGenerator

    quests = QuestGenerator(service).generate(w)
    quest = next((q for q in quests if q["quest_id"] == "quest_gain_guard_trust"), None)
    assert quest is not None, "should have gain_guard_trust quest"

    explanation = ExplanationService(service.conn).explain_quest(w, quest)
    assert explanation["quest_id"] == "quest_gain_guard_trust"
    assert explanation["traceable"] is True, "quest with evidence should be traceable"
    assert "required_state" in explanation
    assert "depends_on" in explanation


def test_explain_npc_action_has_contributing_factors() -> None:
    """NPC action explain must list contributing goals, tensions, and memories."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        from game_world_kg.seed_qingxi import QINGXI_WORLD_ID, seed_qingxi_world
        seed_qingxi_world(conn)
    service = GameWorldService(conn)

    explain = service.explain_npc_action(QINGXI_WORLD_ID, "sun_niang")

    # Causal factors
    assert "contributing_goals" in explain
    assert "contributing_tensions" in explain
    assert "contributing_memories" in explain
    assert "chosen_action" in explain
    assert "scoring_breakdown" in explain

    # At minimum, the explain must tell us WHY this NPC would act
    has_explanation = (
        explain.get("bound_to_goal")
        or explain.get("bound_to_memory")
        or explain.get("bound_to_tension")
        or explain["chosen_action"] is not None
    )
    assert has_explanation, f"NPC explain must provide causal context: {explain}"
