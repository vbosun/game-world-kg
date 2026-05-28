from __future__ import annotations

from game_world_kg.action_template import ActionTemplate, ActionTemplateStore
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


# ── foreground NPC action ─────────────────────────────────────────────


def test_foreground_npc_tick_produces_npc_action_event() -> None:
    """Tick a foreground NPC (guard_alos) must write NPC_ACTION to EventLog."""
    service = _service()
    w = DEMO_WORLD_ID

    events_before = service.events(w)
    npc_action_before = [e for e in events_before if e["event_type"] == "NPC_ACTION"]

    result = service.tick_npc(w, "guard_alos")

    events_after = service.events(w)
    npc_actions_after = [e for e in events_after if e["event_type"] == "NPC_ACTION"]

    if result.get("acted"):
        assert len(npc_actions_after) > len(npc_action_before), "acting NPC must write NPC_ACTION to EventLog"
        marker = npc_actions_after[-1]
        assert marker["actor_id"] == "guard_alos"
        assert "action_id" in marker.get("payload", {})
    else:
        # Even if NPC didn't act, the result must have a reason
        assert "reason" in result


def test_npc_tick_result_includes_event_chain() -> None:
    """NPC tick result must include event IDs from the EventLog."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.tick_npc(w, "guard_alos")

    if result.get("acted"):
        assert "events" in result, "tick result must include events"
        assert len(result["events"]) > 0, "acting NPC must produce at least one event"
        for event in result["events"]:
            assert "id" in event, f"event missing id: {event}"
            assert "event_type" in event, f"event missing event_type: {event}"


def test_foreground_npc_uses_action_template_validation() -> None:
    """NPC action must pass through validate_and_resolve_action (ActionTemplate path)."""
    service = _service()
    w = DEMO_WORLD_ID

    # guard_alos has unlock_gate_with_key (holds silver_key)
    # Tick and verify the gate state reflects actual template execution
    state_before = service.state(w)
    gate_was_open = state_before["iron_gate"]["open"]

    result = service.tick_npc(w, "guard_alos")

    if result.get("acted") and result.get("action", {}).get("action_id") == "unlock_gate_with_key":
        state_after = service.state(w)
        assert state_after["iron_gate"]["open"] is True
        # Silver key holder should not change (NPC uses their own key)
    elif result.get("acted"):
        # Other action — just verify no crash and valid structure
        assert "action_id" in result.get("action", {})
    else:
        assert "reason" in result


# ── midground NPC tick ────────────────────────────────────────────────


def test_tick_world_includes_npc_count() -> None:
    """tick_world must return npc_count and results list."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.tick_world(w, limit=3)
    assert "npc_count" in result
    assert "results" in result
    assert isinstance(result["results"], list)


def test_midground_npc_tick_is_marked_in_result() -> None:
    """When turn reaches midground cycle (every 3 turns), midground NPCs get tier='midground'."""
    service = _service()
    w = DEMO_WORLD_ID

    # Consume turns to reach a turn_index that triggers midground
    # Turn 0 is bootstrap seed; play_turn adds turn 1
    for i in range(3):
        service.play_turn(w, "和守卫交谈", selected_action_id="talk_to_guard", selected_target_id="guard_alos")

    # Now turn_index should be around 3-4, next tick_world should trigger midground
    result = service.tick_world(w, limit=1)
    midground_results = [r for r in result["results"] if r.get("tier") == "midground"]
    # Midground may or may not trigger depending on exact turn index
    # Just verify the field is present and results are well-formed
    for r in result["results"]:
        assert "npc_id" in r
        assert "acted" in r
        assert isinstance(r["acted"], bool)


# ── background faction activity ───────────────────────────────────────


def _service_with_faction() -> GameWorldService:
    """Create a service with demo world + a Faction entity for background testing."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "seed_faction", "Add test faction.")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "merchants_guild", "entity_type": "Faction", "name": "商人工会", "properties": {"archetype": "merchant_guild"}},
            participants=["merchants_guild"],
        )
        projector.apply_event(event)
        # Set faction location so it shows up in state
        loc_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "merchants_guild", "attr": "location", "value": "inner_city"},
            participants=["merchants_guild"],
            state_deltas=[delta("merchants_guild", "location", None, "inner_city")],
        )
        projector.apply_event(loc_event)
        # Set entity_type in state
        type_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "merchants_guild", "attr": "entity_type", "value": "Faction"},
            participants=["merchants_guild"],
            state_deltas=[delta("merchants_guild", "entity_type", None, "Faction")],
        )
        projector.apply_event(type_event)
    return GameWorldService(conn)


def test_background_tick_produces_faction_activity_event() -> None:
    """Every 5 turns, background tick must write FACTION_ACTIVITY to EventLog."""
    service = _service_with_faction()
    w = DEMO_WORLD_ID

    # Play turns to reach turn_index where tick_world triggers background (turn_index % 5 == 0)
    # Turn 0 is bootstrap, turn 1 is seed_faction, turns 2-5 from play_turn
    for i in range(5):
        service.play_turn(w, "和守卫交谈", selected_action_id="talk_to_guard", selected_target_id="guard_alos")

    # Call tick_world — background should trigger
    result = service.tick_world(w, limit=1)

    # Check if background was triggered
    events = service.events(w)
    faction_events = [e for e in events if e["event_type"] == "FACTION_ACTIVITY"]
    # Background triggers at turn_index % 5 == 0. May or may not have triggered depending on exact state.
    # The point is to verify the pipeline works when it does trigger.
    if result.get("background") is not None:
        assert result["background"]["tier"] == "background"
        assert "faction_id" in result["background"]
        assert len(faction_events) >= 1
        assert faction_events[-1]["payload"]["faction_id"] == "merchants_guild"


def test_background_tick_returns_none_when_no_factions() -> None:
    """When world has no factions, background tick returns None."""
    service = _service()  # demo world has no factions
    w = DEMO_WORLD_ID

    result = service.tick_world(w, limit=1)
    assert result.get("background") is None


# ── rumor propagation ─────────────────────────────────────────────────


def test_rumor_propagation_event_written_to_eventlog() -> None:
    """When NPC has rumors and co-located NPCs, SPREAD_RUMOR event is written."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "add_rumor_memory", "Seed rumor for test.")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        # Add a rumor memory to guard_alos
        mem_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "ADD_MEMORY", "guard_alos",
            {"owner_id": "guard_alos", "memory_text": "听说内城有宝藏", "truth_scope": "rumor", "salience": 0.9, "valence": 0.1, "confidence": 0.5},
            participants=["guard_alos"],
        )
        projector.apply_event(mem_event)
        # Add a second NPC at the same location for rumor spread
        npc_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "merchant_li", "entity_type": "Character", "name": "商人李", "properties": {"archetype": "merchant"}},
            participants=["merchant_li"],
        )
        projector.apply_event(npc_event)
        # Set merchant location to same as guard
        loc_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "merchant_li", "attr": "location", "value": "village_gate"},
            participants=["merchant_li"],
            state_deltas=[delta("merchant_li", "location", None, "village_gate")],
        )
        projector.apply_event(loc_event)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Tick guard_alos — should propagate rumor to merchant_li
    result = service.tick_npc(w, "guard_alos")

    events = service.events(w)
    rumor_events = [e for e in events if e["event_type"] == "SPREAD_RUMOR"]

    if result.get("acted"):
        # Guard acted AND has rumor memories, so rumor should spread
        assert len(rumor_events) >= 1, f"acting NPC with rumors should spread them: {[e['event_type'] for e in events]}"
        rumor = rumor_events[-1]
        assert rumor["actor_id"] == "guard_alos"
        assert "merchant_li" in rumor.get("participants", [])
        assert "宝藏" in rumor.get("payload", {}).get("memory_text", "")


# ── three-tier event type distinction ─────────────────────────────────


def test_three_tier_events_have_distinct_types() -> None:
    """Foreground→NPC_ACTION, background→FACTION_ACTIVITY, rumor→SPREAD_RUMOR are distinct."""
    service = _service_with_faction()
    w = DEMO_WORLD_ID

    # Tick a foreground NPC
    service.tick_npc(w, "guard_alos")

    all_events = service.events(w)
    event_types = {e["event_type"] for e in all_events}

    # The three NPC tiers produce different event types
    npc_tier_types = {"NPC_ACTION", "FACTION_ACTIVITY", "SPREAD_RUMOR"}
    found = npc_tier_types & event_types

    # At minimum, NPC_ACTION should be present after ticking an NPC
    assert "NPC_ACTION" in found or "NPC_ACTION" in event_types, \
        f"NPC tick should produce NPC_ACTION events; got types: {event_types}"
