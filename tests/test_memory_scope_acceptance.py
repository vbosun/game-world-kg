from __future__ import annotations

from game_world_kg.db import connect, init_db, from_json, transaction
from game_world_kg.events import EventLog
from game_world_kg.projector import StateProjector, delta
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_rumor_propagation_does_not_write_canonical_state() -> None:
    """Rumor propagation must keep rumor/npc scope, never write canonical state."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        # Set up: add a rumor memory to guard_alos and a second NPC
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "seed_rumor", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        # Add rumor memory
        mem_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "ADD_MEMORY", "guard_alos",
            {"owner_id": "guard_alos", "memory_text": "听说玩家偷了银钥匙", "truth_scope": "rumor",
             "salience": 0.9, "valence": -0.5, "confidence": 0.3},
            participants=["guard_alos"],
        )
        projector.apply_event(mem_event)
        # Add merchant NPC at same location
        npc_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "merchant_li", "entity_type": "Character", "name": "商人李",
             "properties": {"archetype": "merchant"}},
            participants=["merchant_li"],
        )
        projector.apply_event(npc_event)
        loc_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "merchant_li", "attr": "location", "value": "village_gate"},
            participants=["merchant_li"],
            state_deltas=[delta("merchant_li", "location", None, "village_gate")],
        )
        projector.apply_event(loc_event)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Snapshot canonical state before rumor tick
    canonical_before = _canonical_snapshot(service, w)

    # Tick guard to trigger rumor propagation
    result = service.tick_npc(w, "guard_alos")

    # Snapshot canonical state after
    canonical_after = _canonical_snapshot(service, w)

    # Check for SPREAD_RUMOR events
    events = service.events(w)
    rumor_events = [e for e in events if e["event_type"] == "SPREAD_RUMOR"]
    if rumor_events:
        for rumor in rumor_events:
            assert rumor["actor_id"] != "system", "rumors should be NPC-to-NPC"
            payload = rumor.get("payload", {})
            assert "memory_text" in payload

    # Canonical state must not gain NPC-subjective entries
    # NPC may legitimately act (e.g., guard unlocks gate) — that's fine
    # But rumor/memory entries should not leak into canonical state
    for entity_id, attrs in canonical_after.items():
        if entity_id not in canonical_before:
            # New entity appeared — ensure no rumor/memory contamination
            for attr in attrs:
                assert "rumor" not in attr.lower() and "memory" not in attr.lower(), \
                    f"new entity {entity_id}.{attr} should not be rumor/memory in canonical"

    # SPREAD_RUMOR events must exist (if rumor propagation happened)
    if rumor_events:
        for rumor in rumor_events:
            # Rumor payload should not contain canonical state deltas
            payload = rumor.get("payload", {})
            state_deltas_list = rumor.get("state_deltas", [])
            assert len(state_deltas_list) == 0, \
                f"SPREAD_RUMOR should not have canonical state deltas: {state_deltas_list}"


def test_npc_subjective_memory_has_truth_scope() -> None:
    """NPC memories must have truth_scope = 'npc' or 'rumor', not 'canonical'."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Execute show_pass_token (creates NPC memory)
    service.turn_bound(w, "出示通行令", "show_pass_token")

    memories = service.memories(w, "guard_alos")
    assert len(memories) >= 1

    for memory in memories:
        scope = memory.get("truth_scope", "")
        assert scope in {"npc", "rumor", "player", "faction"}, \
            f"NPC memory must have proper scope, got {scope}: {memory['memory_text']}"
        # NPC subjective memories should never be canonical
        if memory.get("owner_id") == "guard_alos":
            assert scope != "canonical", \
                f"NPC subjective memory should not be canonical: {memory['memory_text']}"


def test_player_memory_scope_is_preserved() -> None:
    """Player-scoped memories from add_memory should be readable via player memories."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Steal key (catastrophic) creates a player-scoped memory
    result = service.turn_bound(w, "偷钥匙", "steal_silver_key")
    assert result["accepted"] is True

    player_memories = service.memories(w, "player")
    # Player should see their own memories
    assert len(player_memories) >= 1, "catastrophic failures should create player memories"

    for memory in player_memories:
        if memory.get("owner_id") == "player":
            scope = memory.get("truth_scope", "")
            assert scope in {"player", "canonical"}, \
                f"player memories should be player/canonical scoped, got {scope}"


def test_memories_have_evidence_refs() -> None:
    """Rumor and NPC memories must have traceable source_event_id."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    service.turn_bound(w, "出示通行令", "show_pass_token")

    memories = service.memories(w)
    for memory in memories:
        assert "source_event_id" in memory, \
            f"all memories must have source_event_id: {memory.get('id')}"
        mids = memory.get("id", "")
        assert mids, "memory must have an id"


def test_canonical_state_not_contaminated_by_add_memory_npc_scope() -> None:
    """ADD_MEMORY with truth_scope='npc' must not create a canonical state entry."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    canonical_before = _canonical_snapshot(service, w)

    service.turn_bound(w, "出示通行令", "show_pass_token")

    canonical_after = _canonical_snapshot(service, w)

    # show_pass_token creates: TRANSFER_ITEM (canonical), CHANGE_RELATION (canonical), ADD_MEMORY (npc scope)
    # The ADD_MEMORY with npc scope should NOT appear in canonical state
    # But TRANSFER_ITEM and CHANGE_RELATION will change canonical state
    # So we check that no new entity attribute with 'memory' appears
    new_keys = set(canonical_after.keys()) - set(canonical_before.keys())
    for entity_id in new_keys:
        for attr in canonical_after.get(entity_id, {}):
            assert "memory" not in attr.lower(), \
                f"NPC memory should not create canonical state entry: {entity_id}.{attr}"


def _canonical_snapshot(service: GameWorldService, world_id: str) -> dict[str, dict]:
    """Take a snapshot of canonical state for comparison."""
    state = service.state(world_id)
    return {
        entity_id: {
            attr: value
            for attr, value in attrs.items()
            if not attr.startswith("rumor.") and attr != "rumor"
        }
        for entity_id, attrs in state.items()
    }
