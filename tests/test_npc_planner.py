from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_background_event_uses_created_turn_index() -> None:
    """FACTION_ACTIVITY event.turn_index must match the actual turns.turn_index."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)

    service = GameWorldService(conn)

    # Tick the world at a turn where background fires (turn_index % 5 == 0)
    # First, advance to turn 4 via player actions so turn 5 triggers background
    affordances = service.affordances(DEMO_WORLD_ID)
    for i in range(4):
        move = next((a for a in affordances if a["action_id"] == "talk_to_guard"), affordances[0])
        service.turn_bound(DEMO_WORLD_ID, f"turn {i}", move["action_id"], move.get("target_id"))

    # Now trigger a world tick which should include background (turn 5)
    result = service.tick_world(DEMO_WORLD_ID, limit=3)
    background = result.get("background")

    if background is not None:
        event_data = background.get("event", {})
        event_turn_id = event_data.get("id")
        assert event_turn_id is not None, "Background event should have an id"

        # Verify turn_index from turns table matches event payload
        row = conn.execute("SELECT turn_index FROM turns WHERE id = ?", (event_turn_id,)).fetchone()
        assert row is not None, "Background event's turn_id must exist in turns table"
        assert row["turn_index"] == event_data["payload"]["turn_index"], (
            f"event turn_index {event_data['payload']['turn_index']} != turns row {row['turn_index']}"
        )
