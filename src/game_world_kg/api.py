from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .db import connect, init_db, transaction
from .evaluation import run_evaluation
from .llm import build_llm_client_from_env
from .service import GameWorldService
from .seed import DEMO_WORLD_ID, seed_demo_world

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
    resolved_path = db_path or os.getenv("GAME_WORLD_KG_DB", "game_world_kg.sqlite3")
    conn = connect(Path(resolved_path))
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn, build_llm_client_from_env())

    @app.post("/worlds")
    def create_world() -> dict[str, Any]:
        return service.create_world()

    @app.get("/worlds/{world_id}/state")
    def get_state(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.state(world_id))

    @app.get("/worlds/{world_id}/graph")
    def get_graph(world_id: str) -> dict[str, Any]:
        return _handle(lambda: service.graph(world_id))

    @app.get("/worlds/{world_id}/events")
    def get_events(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.events(world_id))

    @app.get("/worlds/{world_id}/affordances")
    def get_affordances(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.affordances(world_id))

    @app.get("/worlds/{world_id}/quests")
    def get_quests(world_id: str) -> list[dict[str, Any]]:
        return _handle(lambda: service.quests(world_id))

    @app.get("/worlds/{world_id}/memories")
    def get_memories(world_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        return _handle(lambda: service.memories(world_id, owner_id))

    @app.get("/worlds/{world_id}/memories/{owner_id}/recall")
    def recall_memory(world_id: str, owner_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _handle(lambda: service.recall_memory(world_id, owner_id, query, limit))

    @app.get("/worlds/{world_id}/neighbors/{entity_id}")
    def get_neighbors(world_id: str, entity_id: str, rel_type: str | None = None) -> list[dict[str, Any]]:
        return _handle(lambda: service.neighbors(world_id, entity_id, rel_type))

    @app.post("/worlds/{world_id}/npc/{npc_id}/dialogue")
    def npc_dialogue(world_id: str, npc_id: str, request: DialogueRequest) -> dict[str, Any]:
        return _handle(lambda: service.npc_dialogue(world_id, npc_id, request.question))

    @app.post("/worlds/{world_id}/turn")
    def post_turn(world_id: str, request: TurnRequest) -> dict[str, Any]:
        return _handle(lambda: service.turn(world_id, request.player_input))

    @app.post("/worlds/{world_id}/replay")
    def post_replay(world_id: str, request: ReplayRequest) -> dict[str, Any]:
        return _handle(lambda: service.replay(world_id, request.to_turn))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "demo_world_id": DEMO_WORLD_ID}

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
