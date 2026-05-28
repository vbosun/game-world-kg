from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .db import from_json

if TYPE_CHECKING:
    from .service import GameWorldService


@dataclass(frozen=True)
class Tension:
    tension_id: str
    type: str
    reason: str
    evidence: list[dict[str, Any]]
    affected_entities: list[str]
    suggested_actions: list[str]
    priority: float = 0.5
    stake: str = ""
    deadline_turn: int | None = None
    sponsors: list[str] = ()
    blockers: list[str] = ()
    player_touchpoints: list[str] = ()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tension_id": self.tension_id,
            "type": self.type,
            "reason": self.reason,
            "evidence": self.evidence,
            "affected_entities": self.affected_entities,
            "suggested_actions": self.suggested_actions,
            "priority": self.priority,
        }
        if self.stake:
            result["stake"] = self.stake
        if self.deadline_turn is not None:
            result["deadline_turn"] = self.deadline_turn
        if self.sponsors:
            result["sponsors"] = list(self.sponsors)
        if self.blockers:
            result["blockers"] = list(self.blockers)
        if self.player_touchpoints:
            result["player_touchpoints"] = list(self.player_touchpoints)
        return result


class TensionScanner:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service

    def scan(self, world_id: str) -> list[dict[str, Any]]:
        state = self.service.state(world_id)
        memories = self.service.memories(world_id)
        tensions: list[Tension] = []

        gate_open = state.get("iron_gate", {}).get("open") is True
        if "iron_gate" in state and not gate_open:
            tensions.append(
                Tension(
                    tension_id="tension_locked_iron_gate",
                    type="locked_location",
                    reason="铁门仍未打开，玩家无法进入内城。",
                    evidence=[
                        _state_evidence("iron_gate", "open", gate_open),
                        _state_evidence("iron_gate", "locked", state.get("iron_gate", {}).get("locked")),
                    ],
                    affected_entities=["player", "iron_gate", "inner_city"],
                    suggested_actions=["show_pass_token", "request_access", "ask_guard_open_gate", "unlock_gate_with_key"],
                    priority=0.9,
                    stake="无法进入内城意味着主线剧情无法推进，玩家将被困在村口区域。",
                    sponsors=["village_chief", "merchant_borin"],
                    blockers=["guard_alos"],
                    player_touchpoints=["show_pass_token", "unlock_gate_with_key", "bribe_guard"],
                )
            )

        trust = state.get("guard_alos", {}).get("trust.player")
        if trust is not None and trust < 5:
            tensions.append(
                Tension(
                    tension_id="tension_guard_trust_low",
                    type="trust_below_threshold",
                    reason="守卫信任不足，无法主动放行。",
                    evidence=[_state_evidence("guard_alos", "trust.player", trust)],
                    affected_entities=["guard_alos", "player", "iron_gate"],
                    suggested_actions=["show_pass_token", "bribe_guard", "talk_to_guard"],
                    priority=0.7,
                    stake="守卫阿洛斯是通往内城的关键看门人，信任度决定了玩家能否和平进入。",
                    sponsors=["village_chief"],
                    blockers=[],
                    player_touchpoints=["show_pass_token", "talk_to_guard", "ask_guard_open_gate"],
                )
            )

        rumor_memories = [
            memory
            for memory in memories
            if memory["truth_scope"] == "rumor" and ("偷了钥匙" in memory["memory_text"] or "银钥匙" in memory["memory_text"])
        ]
        rumor_resolved = state.get("silver_key", {}).get("rumor.rumor_resolved") is True
        if rumor_memories and not rumor_resolved:
            tensions.append(
                Tension(
                    tension_id="tension_key_theft_rumor",
                    type="rumor_unresolved",
                    reason="村里存在玩家与银钥匙失窃有关的传闻。",
                    evidence=[_memory_evidence(memory) for memory in rumor_memories],
                    affected_entities=["player", "silver_key", "guard_alos", "tavern_public"],
                    suggested_actions=["ask_about_rumor", "clarify_rumor", "talk_to_mira"],
                    priority=0.6,
                    stake="谣言会降低 NPC 对玩家的信任，并可能触发守卫的敌意行为。",
                    sponsors=["mira"],
                    blockers=["guard_alos"],
                    player_touchpoints=["ask_about_rumor", "clarify_rumor", "talk_to_mira"],
                )
            )

        warehouse_state = state.get("warehouse", {})
        if warehouse_state.get("locked") is True:
            tensions.append(
                Tension(
                    tension_id="tension_warehouse_locked",
                    type="quest_dependency_missing",
                    reason="仓库仍上锁，粮食和账本调查无法继续。",
                    evidence=[_state_evidence("warehouse", "locked", True)],
                    affected_entities=["warehouse", "warehouse_keeper", "ledger_book", "grain_bag"],
                    suggested_actions=["request_warehouse_access", "inspect_warehouse"],
                    priority=0.65,
                    stake="仓库中的账本和粮食是解决粮食短缺和商人信任问题的关键证据。",
                    sponsors=["merchant_borin", "village_chief"],
                    blockers=["warehouse_keeper"],
                    player_touchpoints=["request_warehouse_access", "inspect_warehouse"],
                )
            )

        grain_stock = warehouse_state.get("grain_stock")
        grain_trade_completed = state.get("grain_bag", {}).get("trade_completed") is True
        if grain_stock is not None and grain_stock <= 12 and not grain_trade_completed:
            tensions.append(
                Tension(
                    tension_id="tension_grain_trade_blocked",
                    type="resource_shortage",
                    reason="仓库粮食紧张，商人交易需要村长和仓库线索支持。",
                    evidence=[_state_evidence("warehouse", "grain_stock", grain_stock)],
                    affected_entities=["warehouse", "grain_bag", "merchant_borin", "village_chief"],
                    suggested_actions=["trade_grain", "talk_to_chief", "inspect_warehouse"],
                    priority=0.55,
                    stake="粮食短缺会影响整个村庄的稳定，商人的去留取决于此问题的解决。",
                    deadline_turn=30,
                    sponsors=["merchant_borin"],
                    blockers=["warehouse_keeper"],
                    player_touchpoints=["trade_grain", "talk_to_chief", "inspect_warehouse"],
                )
            )

        generated = [tension.as_dict() for tension in tensions]
        known = {item["tension_id"] for item in generated}
        for row in self.service.conn.execute(
            """
            SELECT properties_json FROM nodes
            WHERE world_id = ? AND entity_type = 'Tension' AND valid_to_turn IS NULL
            ORDER BY id
            """,
            (world_id,),
        ).fetchall():
            payload = from_json(row["properties_json"], {})
            tension_id = payload.get("id")
            if not tension_id or tension_id in known:
                continue
            generated.append(
                {
                    "tension_id": tension_id,
                    "type": payload.get("tension_type", "worldspec"),
                    "reason": payload.get("description", ""),
                    "description": payload.get("description", ""),
                    "evidence": payload.get("evidence", []),
                    "affected_entities": payload.get("affected_entities", []),
                    "suggested_actions": payload.get("suggested_actions", []),
                    "priority": payload.get("priority", 0.5),
                    "stake": payload.get("stake", ""),
                    "deadline_turn": payload.get("deadline_turn"),
                    "sponsors": payload.get("sponsors", []),
                    "blockers": payload.get("blockers", []),
                    "player_touchpoints": payload.get("player_touchpoints", []),
                }
            )
            known.add(tension_id)
        return generated


def _state_evidence(entity_id: str, attr: str, value: Any) -> dict[str, Any]:
    return {"source_type": "state", "entity_id": entity_id, "attr": attr, "value": value}


def _memory_evidence(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": "memory",
        "memory_id": memory["id"],
        "source_event_id": memory["source_event_id"],
        "truth_scope": memory["truth_scope"],
    }
