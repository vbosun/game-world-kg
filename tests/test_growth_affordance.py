from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_trust_growth_unlocks_ask_guard_open_gate() -> None:
    """After showing pass token (+2 trust, 3→5), ask_guard_open_gate must become available."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID

    # Initial state: trust is 3
    state = service.state(w)
    assert state["guard_alos"]["trust.player"] == 3

    # ask_guard_open_gate should NOT be available yet (requires trust >= 5)
    affordance_ids = [a["action_id"] for a in service.affordances(w)]
    assert "ask_guard_open_gate" not in affordance_ids

    # Execute show_pass_token — increases trust by +2
    result = service.turn_bound(w, "出示通行令", "show_pass_token")
    assert result["accepted"] is True

    # Trust is now 5
    state = service.state(w)
    assert state["guard_alos"]["trust.player"] == 5

    # ask_guard_open_gate should NOW be available
    affordance_ids = [a["action_id"] for a in service.affordances(w)]
    assert "ask_guard_open_gate" in affordance_ids
