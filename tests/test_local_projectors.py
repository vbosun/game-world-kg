from __future__ import annotations

from pathlib import Path

from game_world_kg.config import StorageConfig
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def test_storage_config_creates_local_demo_directories(tmp_path: Path) -> None:
    storage = StorageConfig(
        sqlite_path=tmp_path / "game.sqlite3",
        kuzu_path=tmp_path / "kuzu",
        chroma_path=tmp_path / "chroma",
    )

    storage.ensure_dirs()

    assert storage.sqlite_path.parent.exists()
    assert storage.kuzu_path.exists()
    assert storage.chroma_path.exists()


def test_projector_rebuild_materializes_kuzu_and_chroma_views(tmp_path: Path) -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(
        conn,
        storage=StorageConfig(
            sqlite_path=tmp_path / "game.sqlite3",
            kuzu_path=tmp_path / "kuzu",
            chroma_path=tmp_path / "chroma",
        ),
    )

    result = service.rebuild_projectors(DEMO_WORLD_ID)

    assert {item["projector"] for item in result["projection_status"]} == {"chroma_vector", "kuzu_graph"}
    graph = service.kuzu_graph(DEMO_WORLD_ID)
    assert any(node["id"] == "player" for node in graph["nodes"])
    assert any(edge["src_id"] == "player" and edge["rel_type"] == "LOCATED_AT" for edge in graph["edges"])
    evidence_hits = service.search_evidence(DEMO_WORLD_ID, "seed_demo_world")
    assert evidence_hits


def test_projector_run_consumes_outbox_after_new_turn(tmp_path: Path) -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(
        conn,
        storage=StorageConfig(
            sqlite_path=tmp_path / "game.sqlite3",
            kuzu_path=tmp_path / "kuzu",
            chroma_path=tmp_path / "chroma",
        ),
    )

    service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")
    pending_before = conn.execute("SELECT COUNT(*) AS count FROM outbox WHERE status = 'pending'").fetchone()["count"]
    result = service.run_projectors(DEMO_WORLD_ID)

    assert pending_before > 0
    assert sum(item["processed"] for item in result["projectors"]) == pending_before
    pending_after = conn.execute("SELECT COUNT(*) AS count FROM outbox WHERE status = 'pending'").fetchone()["count"]
    assert pending_after == 0
    memories = service.search_memories(DEMO_WORLD_ID, "guard_alos", "通行令")
    assert any("通行令" in item["text"] for item in memories)
