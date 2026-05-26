from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import StorageConfig
from .db import connect, init_db, transaction
from .evaluation import run_evaluation
from .llm import build_llm_client_from_env
from .service import GameWorldService
from .seed import DEMO_WORLD_ID, seed_demo_world
from .seed_village import DEMO_VILLAGE_WORLD_ID, seed_village_world

PACKAGE_DIR = Path(__file__).resolve().parent
DEBUG_HTML_PATH = PACKAGE_DIR / "static" / "debug.html"


class TurnRequest(BaseModel):
    player_input: str


class ReplayRequest(BaseModel):
    to_turn: int | None = None


class DialogueRequest(BaseModel):
    question: str


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Game World KG MVP")
    storage = StorageConfig.from_env()
    resolved_path = db_path or os.getenv("GAME_WORLD_KG_DB", str(storage.sqlite_path))
    if resolved_path != ":memory:":
        storage = StorageConfig(sqlite_path=Path(resolved_path), kuzu_path=storage.kuzu_path, chroma_path=storage.chroma_path)
    storage.ensure_dirs()
    conn = connect(Path(resolved_path))
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        seed_village_world(conn)
    service = GameWorldService(conn, build_llm_client_from_env(), storage)

    @app.post("/worlds")
    def create_world() -> dict[str, Any]:
        return service.create_world()

    @app.get("/worlds/{world_id}/state")
    def get_state(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.state(world_id))

    @app.get("/worlds/{world_id}/graph")
    def get_graph(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.graph(world_id))

    @app.get("/worlds/{world_id}/kuzu/graph")
    def get_kuzu_graph(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.kuzu_graph(world_id))

    @app.get("/worlds/{world_id}/events")
    def get_events(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.events(world_id))

    @app.get("/worlds/{world_id}/affordances")
    def get_affordances(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.affordances(world_id))

    @app.get("/worlds/{world_id}/quests")
    def get_quests(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.quests(world_id))

    @app.get("/worlds/{world_id}/tensions")
    def get_tensions(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.tensions(world_id))

    @app.get("/worlds/{world_id}/explain/state/{entity_id}/{attr}")
    def explain_state(world_id: str, entity_id: str, attr: str, scope: str = "canonical") -> dict[str, Any]:
        return _handle(lambda: service.explain_state(world_id, entity_id, attr, scope))

    @app.get("/worlds/{world_id}/explain/event/{event_id}")
    def explain_event(world_id: str, event_id: str) -> dict[str, Any]:
        return _handle(lambda: service.explain_event(world_id, event_id))

    @app.get("/worlds/{world_id}/explain/quest/{quest_id}")
    def explain_quest(world_id: str, quest_id: str) -> dict[str, Any]:
        return _handle(lambda: service.explain_quest(world_id, quest_id))

    @app.get("/worlds/{world_id}/explain/memory/{memory_id}")
    def explain_memory(world_id: str, memory_id: str) -> dict[str, Any]:
        return _handle(lambda: service.explain_memory(world_id, memory_id))

    @app.get("/worlds/{world_id}/memories")
    def get_memories(world_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        return _handle(lambda: service.memories(world_id, owner_id))

    @app.get("/worlds/{world_id}/memories/{owner_id}/recall")
    def recall_memory(world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _handle(lambda: service.recall_memory(world_id, owner_id, query, limit))

    @app.get("/worlds/{world_id}/neighbors/{entity_id}")
    def get_neighbors(world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        return _handle(lambda: service.neighbors(world_id, entity_id, rel_type))

    @app.get("/worlds/{world_id}/kuzu/neighbors/{entity_id}")
    def get_kuzu_neighbors(world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        return _handle(lambda: service.kuzu_neighbors(world_id, entity_id, rel_type))

    @app.get("/worlds/{world_id}/chroma/search/evidence")
    def search_evidence(world_id: str, query: str, scope: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        return _handle(lambda: service.search_evidence(world_id, query, scope, limit))

    @app.get("/worlds/{world_id}/chroma/search/memories")
    def search_memories(world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _handle(lambda: service.search_memories(world_id, owner_id, query, limit))

    @app.post("/worlds/{world_id}/npc/{npc_id}/dialogue")
    def npc_dialogue(world_id: str, npc_id: str, request: DialogueRequest) -> dict[str, Any]:
        return _handle(lambda: service.npc_dialogue(world_id, npc_id, request.question))

    @app.post("/worlds/{world_id}/turn")
    def post_turn(world_id: str, request: TurnRequest) -> dict[str, Any]:
        return _handle(lambda: service.turn(world_id, request.player_input))

    @app.post("/worlds/{world_id}/replay")
    def post_replay(world_id: str, request: ReplayRequest) -> dict[str, Any]:
        return _handle(lambda: service.replay(world_id, request.to_turn))

    @app.post("/worlds/{world_id}/projectors/run")
    def post_projectors_run(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.run_projectors(world_id))

    @app.post("/worlds/{world_id}/projectors/rebuild")
    def post_projectors_rebuild(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.rebuild_projectors(world_id))

    @app.get("/worlds/{world_id}/projectors/status")
    def get_projectors_status(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.projection_status(world_id))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "demo_world_id": DEMO_WORLD_ID, "demo_village_world_id": DEMO_VILLAGE_WORLD_ID}

    @app.get("/evaluation")
    def evaluation() -> dict[str, Any]:
        return run_evaluation()

    @app.get("/debug", response_class=HTMLResponse)
    def debug_panel() -> str:
        return DEBUG_HTML_PATH.read_text(encoding="utf-8")

    return app


def _handle(call):
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"world not found: {exc.args[0]}") from exc


app = create_app()
