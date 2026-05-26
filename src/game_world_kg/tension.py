from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "tension_id": self.tension_id,
            "type": self.type,
            "reason": self.reason,
            "evidence": self.evidence,
            "affected_entities": self.affected_entities,
            "suggested_actions": self.suggested_actions,
        }


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
                )
            )

        return [tension.as_dict() for tension in tensions]


def _state_evidence(entity_id: str, attr: str, value: Any) -> dict[str, Any]:
    return {"source_type": "state", "entity_id": entity_id, "attr": attr, "value": value}


def _memory_evidence(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": "memory",
        "memory_id": memory["id"],
        "source_event_id": memory["source_event_id"],
        "truth_scope": memory["truth_scope"],
    }
