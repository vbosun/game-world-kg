from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.drama import (
    PlayerInterestTracker,
    _classify_semantic,
    _is_main_candidate,
    _is_side_candidate,
)
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_is_main_candidate_detects_strong_signals() -> None:
    """Main candidate must have stake, sponsors, player_touchpoints, or urgent deadline."""
    # Has stake
    assert _is_main_candidate({"stake": "high stakes"}, current_turn=0)
    # Has sponsors
    assert _is_main_candidate({"sponsors": ["npc_1"]}, current_turn=0)
    # Has player_touchpoints
    assert _is_main_candidate({"player_touchpoints": ["action_a"]}, current_turn=0)
    # Urgent deadline (within 5 turns)
    assert _is_main_candidate({"deadline_turn": 3}, current_turn=0)
    assert not _is_main_candidate({"deadline_turn": 10}, current_turn=0)
    # No strong signals
    assert not _is_main_candidate({}, current_turn=0)
    assert not _is_main_candidate({"priority": 0.9}, current_turn=0)


def test_is_side_candidate_detects_player_connections() -> None:
    """Side candidate must have sponsors, player_touchpoints, or player-interest overlap."""
    interest = PlayerInterestTracker(
        recent_locations=["village_gate"],
        recent_npcs=["guard_alos"],
        recent_quests=[],
    )
    assert _is_side_candidate({"sponsors": ["npc_1"]}, interest)
    assert _is_side_candidate({"player_touchpoints": ["action_a"]}, interest)
    assert _is_side_candidate({"affected_entities": ["village_gate"]}, interest)
    assert _is_side_candidate({"affected_entities": ["guard_alos"]}, interest)
    assert not _is_side_candidate({"affected_entities": ["far_away_npc"]}, interest)
    assert not _is_side_candidate({}, interest)


def test_classify_semantic_picks_main_by_signals_not_just_score() -> None:
    """A lower-scored tension with semantic signals beats a higher-scored one without."""
    interest = PlayerInterestTracker(
        recent_locations=[],
        recent_npcs=[],
        recent_quests=[],
    )
    # High score but no semantic signals
    high_score_no_signal = {
        "tension_id": "t_high_score",
        "type": "generic",
        "reason": "high score, no signal",
        "foreground_score": 0.95,
        "priority": 0.8,
    }
    # Lower score but has stake (semantic signal for main)
    low_score_with_stake = {
        "tension_id": "t_with_stake",
        "type": "hostility_rising",
        "reason": "lower score but has stake",
        "foreground_score": 0.6,
        "priority": 0.6,
        "stake": "critical plot point",
    }

    scored = [high_score_no_signal, low_score_with_stake]
    main, side, ambient = _classify_semantic(scored, interest, current_turn=0)

    assert main is not None
    assert main["tension_id"] == "t_with_stake"
    assert side is None or side["tension_id"] != "t_with_stake"


def test_classify_semantic_fallback_to_positional() -> None:
    """When no tension has semantic signals, fall back to positional (scored order)."""
    interest = PlayerInterestTracker(recent_locations=[], recent_npcs=[], recent_quests=[])
    scored = [
        {"tension_id": "t_a", "type": "generic", "reason": "a", "foreground_score": 0.9, "priority": 0.8},
        {"tension_id": "t_b", "type": "generic", "reason": "b", "foreground_score": 0.7, "priority": 0.6},
        {"tension_id": "t_c", "type": "generic", "reason": "c", "foreground_score": 0.5, "priority": 0.4},
    ]
    main, side, ambient = _classify_semantic(scored, interest, current_turn=0)

    assert main is not None
    assert main["tension_id"] == "t_a"  # highest scored
    assert side is not None
    assert side["tension_id"] == "t_b"  # second highest
    assert len(ambient) == 1
    assert ambient[0]["tension_id"] == "t_c"


def test_tension_deadline_changes_drama_priority() -> None:
    """A tension with an urgent deadline should be classified as main."""
    interest = PlayerInterestTracker(recent_locations=[], recent_npcs=[], recent_quests=[])
    current_turn = 20

    # Far deadline — not main candidate
    far_deadline = {
        "tension_id": "t_far",
        "type": "generic",
        "reason": "far deadline",
        "foreground_score": 0.8,
        "priority": 0.7,
        "deadline_turn": 30,
    }
    # Urgent deadline (within 5 turns) — main candidate
    urgent_deadline = {
        "tension_id": "t_urgent",
        "type": "generic",
        "reason": "urgent deadline",
        "foreground_score": 0.5,
        "priority": 0.5,
        "deadline_turn": 22,
    }

    scored = [far_deadline, urgent_deadline]
    main, side, ambient = _classify_semantic(scored, interest, current_turn)

    # The urgent deadline (2 turns away) should be picked as main
    # even though it has lower score
    assert main is not None
    assert main["tension_id"] == "t_urgent"
    # The far deadline (10 turns away) becomes side or ambient
    all_other_ids = {t["tension_id"] for t in ([side] if side else []) + ambient}
    assert "t_far" in all_other_ids


def test_drama_main_side_ambient_are_semantically_distinct() -> None:
    """In demo world, main/side/ambient should have different characteristics."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    drama = service.drama_foreground(DEMO_WORLD_ID)

    main = drama["main_tension"]
    side = drama["side_tension"]
    ambient = drama["ambient_noise"]

    # Main must exist and have at least one strong semantic signal
    assert main is not None, "main_tension must not be None"
    main_has_signal = (
        bool(main.get("stake"))
        or bool(main.get("sponsors"))
        or bool(main.get("player_touchpoints"))
        or (
            main.get("deadline_turn") is not None
            and isinstance(main["deadline_turn"], (int, float))
        )
    )
    assert main_has_signal, f"main_tension should have at least one semantic signal: {main}"

    # Main should have the highest foreground score among all tensions
    main_score = main.get("foreground_score", 0)
    if side:
        assert main_score >= side.get("foreground_score", 0), "main should score >= side"

    # Side and ambient should be distinct from main
    main_id = main.get("tension_id") or main.get("id")
    if side:
        side_id = side.get("tension_id") or side.get("id")
        assert main_id != side_id, "main and side must be different tensions"

    # Ambient entries should not be main or side
    ambient_ids = {entry["tension_id"] for entry in ambient}
    assert main_id not in ambient_ids
    if side:
        side_id = side.get("tension_id") or side.get("id")
        assert side_id not in ambient_ids

    # Verify the semantic classification contract: main > side > ambient is non-overlapping
    all_ids: set[str] = {main_id}
    if side:
        all_ids.add(side.get("tension_id") or side.get("id"))
    all_ids |= ambient_ids
    # Every tension in the world is assigned to exactly one category
    tensions = service.tensions(DEMO_WORLD_ID)
    tension_ids = {t.get("tension_id") or t.get("id") for t in tensions}
    # All tension ids should appear in our classification
    for tid in tension_ids:
        assert tid in all_ids, f"tension {tid} not found in any drama category"
