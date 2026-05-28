from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.npc_planner import NPCPlanner
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_npc_action_explain_contains_goal_memory_or_tension() -> None:
    """NPC action explain must trace back to at least one of goal/memory/tension."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # Run one player turn to create some memories/tensions for the NPC
    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")

    # explain_npc_action should bind the action to at least one of goal/memory/tension
    explain = service.explain_npc_action(DEMO_WORLD_ID, "guard_alos")

    assert explain["npc_id"] == "guard_alos"
    assert explain["chosen_action"] is not None, "NPC should have a chosen action"

    # At least one of goal/memory/tension binding must be true
    has_binding = (
        explain["bound_to_goal"]
        or explain["bound_to_memory"]
        or explain["bound_to_tension"]
    )
    assert has_binding, (
        f"NPC action must be bound to at least one of goal/memory/tension.\n"
        f"bound_to_goal={explain['bound_to_goal']}\n"
        f"bound_to_memory={explain['bound_to_memory']}\n"
        f"bound_to_tension={explain['bound_to_tension']}\n"
        f"contributing_goals={explain['contributing_goals']}\n"
        f"contributing_tensions={explain['contributing_tensions']}\n"
        f"contributing_memories={explain['contributing_memories']}"
    )

    # Scoring breakdown should have all dimensions
    breakdown = explain["scoring_breakdown"]
    for key in ("goal_relevance", "tension_relevance", "memory_relevance"):
        assert key in breakdown, f"scoring_breakdown must contain {key}"

    # Context summary should show what's available
    summary = explain["context_summary"]
    assert summary["actions_count"] > 0, "NPC should have available actions"


def test_npc_explain_without_memories_still_has_context() -> None:
    """Even without memories, explain should report context and not crash."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    # Fresh world, no player actions yet — NPC has few memories
    explain = service.explain_npc_action(DEMO_WORLD_ID, "guard_alos")

    assert explain["npc_id"] == "guard_alos"
    assert explain["context_summary"]["actions_count"] > 0
    # At minimum should have some binding
    assert isinstance(explain["bound_to_goal"], bool)
    assert isinstance(explain["bound_to_memory"], bool)
    assert isinstance(explain["bound_to_tension"], bool)


def test_npc_tick_result_includes_scoring_breakdown() -> None:
    """NPC tick result must include scoring_breakdown for traceability."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    planner = NPCPlanner(conn, service)
    result = planner.tick_npc(DEMO_WORLD_ID, "guard_alos")

    assert "scoring_breakdown" in result
    breakdown = result["scoring_breakdown"]
    if result["acted"]:
        for key in ("goal_relevance", "tension_relevance", "memory_relevance"):
            assert key in breakdown, f"breakdown must contain {key}"
