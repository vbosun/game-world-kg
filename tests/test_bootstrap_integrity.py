from __future__ import annotations

from game_world_kg.bootstrap import WorldBootstrapper
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.service import GameWorldService, _world_state_hash
from game_world_kg.worldspec import WorldSpec, WorldSpecValidator, sample_world_spec


def test_bootstrap_is_idempotent_for_same_spec_hash() -> None:
    """Second bootstrap of the same spec must return idempotent=True without duplicating events."""
    conn = connect(":memory:")
    init_db(conn)

    spec = sample_world_spec("village")

    # First bootstrap — fresh
    with transaction(conn):
        result1 = WorldBootstrapper(conn).bootstrap(spec)
    assert result1.idempotent is False
    assert len(result1.event_ids) > 5, "Bootstrap should produce events"

    # Second bootstrap — must be idempotent
    with transaction(conn):
        result2 = WorldBootstrapper(conn).bootstrap(spec)
    assert result2.idempotent is True
    assert result2.spec_hash == result1.spec_hash
    assert result2.world_spec_id == result1.world_spec_id
    assert len(result2.event_ids) == len(result1.event_ids)

    # Only one completed bootstrap_run row
    rows = conn.execute(
        "SELECT * FROM bootstrap_runs WHERE world_id = ? AND spec_hash = ? AND status = 'completed'",
        (spec.world_id, result1.spec_hash),
    ).fetchall()
    assert len(rows) == 1


def test_replay_after_bootstrap_preserves_state_hash() -> None:
    """Replay immediately after bootstrap must produce identical state hash."""
    conn = connect(":memory:")
    init_db(conn)

    spec = sample_world_spec("village")
    with transaction(conn):
        WorldBootstrapper(conn).bootstrap(spec)

    service = GameWorldService(conn)
    world_id = spec.world_id

    before_hash = _world_state_hash(conn, world_id)
    service.replay(world_id)
    after_hash = _world_state_hash(conn, world_id)

    assert before_hash == after_hash, "Replay must restore the identical state"
