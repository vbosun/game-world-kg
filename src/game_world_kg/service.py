from __future__ import annotations

import sqlite3
from typing import Any

from .affordance import AffordanceEngine
from .db import transaction
from .events import EventLog
from .graph import WorldGraph
from .llm import ActionParser, LLMClient, Narrator
from .projector import StateProjector
from .rules import RuleEngine
from .seed import DEMO_WORLD_ID, seed_demo_world


class GameWorldService:
    def __init__(self, conn: sqlite3.Connection, llm_client: LLMClient | None = None) -> None:
        self.conn = conn
        self.action_parser = ActionParser(llm_client)
        self.narrator = Narrator(llm_client)

    def create_world(self) -> dict[str, Any]:
        with transaction(self.conn):
            world_id = seed_demo_world(self.conn, DEMO_WORLD_ID)
        return self.get_world(world_id)

    def get_world(self, world_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
        if row is None:
            raise KeyError(world_id)
        return {"id": row["id"], "name": row["name"], "description": row["description"], "created_at": row["created_at"]}

    def state(self, world_id: str) -> dict[str, dict[str, Any]]:
        self._require_world(world_id)
        return WorldGraph(self.conn).state(world_id)

    def graph(self, world_id: str) -> dict[str, list[dict[str, Any]]]:
        self._require_world(world_id)
        return WorldGraph(self.conn).graph(world_id)

    def events(self, world_id: str) -> list[dict[str, Any]]:
        self._require_world(world_id)
        return WorldGraph(self.conn).events(world_id)

    def memories(self, world_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        self._require_world(world_id)
        return WorldGraph(self.conn).memories(world_id, owner_id)

    def affordances(self, world_id: str) -> list[dict[str, Any]]:
        self._require_world(world_id)
        return AffordanceEngine(self.conn).list_for_player(world_id)

    def turn(self, world_id: str, player_input: str) -> dict[str, Any]:
        self._require_world(world_id)
        with transaction(self.conn):
            log = EventLog(self.conn)
            turn_id = log.create_turn(world_id, player_input)
            turn = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            state_before = self.state(world_id)
            affordances_before = AffordanceEngine(self.conn).list_for_player(world_id)
            candidate = self.action_parser.parse(player_input, state_before, affordances_before)
            result = RuleEngine(self.conn).resolve_turn(
                world_id,
                turn_id,
                turn["turn_index"],
                player_input,
                action_id=candidate.action_id if candidate else None,
                extractor="llm_action_parser_v1" if candidate else "rule_parser_v1",
                confidence=candidate.confidence if candidate else 0.9,
            )
            event_payloads = [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "actor_id": event.actor_id,
                    "participants": event.participants,
                    "payload": event.payload,
                }
                for event in result.events
            ]
            affordances = AffordanceEngine(self.conn).list_for_player(world_id)
            narration = self.narrator.narrate(player_input, result, event_payloads, self.state(world_id), affordances)
            self.conn.execute("UPDATE turns SET narration = ? WHERE id = ?", (narration, turn_id))
        return {
            "turn_id": turn_id,
            "turn_index": turn["turn_index"],
            "accepted": result.accepted,
            "action_id": result.action_id,
            "reason": result.reason,
            "narration": narration,
            "events": event_payloads,
            "affordances": affordances,
        }

    def replay(self, world_id: str, to_turn: int | None = None) -> dict[str, Any]:
        self._require_world(world_id)
        with transaction(self.conn):
            StateProjector(self.conn).replay_to_turn(world_id, to_turn)
        return {
            "world_id": world_id,
            "to_turn": to_turn,
            "state": self.state(world_id),
            "graph": self.graph(world_id),
            "memories": self.memories(world_id),
        }

    def _require_world(self, world_id: str) -> None:
        if self.conn.execute("SELECT 1 FROM worlds WHERE id = ?", (world_id,)).fetchone() is None:
            raise KeyError(world_id)
