from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from .seed import DEMO_WORLD_ID
from .tension import TensionScanner

if TYPE_CHECKING:
    from .service import GameWorldService


@dataclass(frozen=True)
class QuestCandidate:
    quest_id: str
    title: str
    reason: str
    depends_on: list[str]
    required_state: list[dict[str, Any]]
    reward: dict[str, Any]
    failure_consequence: dict[str, Any]
    evidence: list[dict[str, Any]]
    tension_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "quest_id": self.quest_id,
            "title": self.title,
            "reason": self.reason,
            "depends_on": self.depends_on,
            "required_state": self.required_state,
            "reward": self.reward,
            "failure_consequence": self.failure_consequence,
            "evidence": self.evidence,
        }
        if self.tension_id is not None:
            payload["tension_id"] = self.tension_id
        return payload


class QuestGenerator:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service

    def generate(self, world_id: str = DEMO_WORLD_ID) -> list[dict[str, Any]]:
        affordances = self.service.affordances(world_id)
        quests: list[QuestCandidate] = []
        for tension in TensionScanner(self.service).scan(world_id):
            quest = _quest_from_tension(tension, affordances)
            if quest is not None:
                quests.append(quest)

        return [quest.as_dict() for quest in quests]


class QuestValidator:
    def __init__(self, service: GameWorldService) -> None:
        self.service = service

    def validate(self, quest: dict[str, Any], world_id: str = DEMO_WORLD_ID) -> dict[str, Any]:
        state = self.service.state(world_id)
        graph = self.service.graph(world_id)
        entity_ids = {node["id"] for node in graph["nodes"]}
        entity_ids.update(state.keys())

        dependency_valid = bool(quest["depends_on"]) and all(isinstance(item, str) and item for item in quest["depends_on"])
        traceable = bool(quest["evidence"]) and all(_evidence_is_traceable(item) for item in quest["evidence"])
        completable = all(_required_state_is_grounded(item, entity_ids) for item in quest["required_state"])
        reward_valid = _effect_is_grounded(quest["reward"], entity_ids)
        failure_valid = _effect_is_grounded(quest["failure_consequence"], entity_ids)
        return {
            "quest_id": quest["quest_id"],
            "dependency_valid": dependency_valid,
            "traceable": traceable,
            "completable": completable,
            "reward_valid": reward_valid,
            "failure_valid": failure_valid,
            "valid": dependency_valid and traceable and completable and reward_valid and failure_valid,
        }


def _state_evidence(entity_id: str, attr: str, value: Any) -> dict[str, Any]:
    return {"source_type": "state", "entity_id": entity_id, "attr": attr, "value": value}


def _memory_evidence(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": "memory",
        "memory_id": memory["id"],
        "source_event_id": memory["source_event_id"],
        "truth_scope": memory["truth_scope"],
    }


def _affordance_evidence(action_id: str, affordances: list[dict[str, Any]]) -> dict[str, Any]:
    found = next((item for item in affordances if item["action_id"] == action_id), None)
    return {
        "source_type": "affordance",
        "action_id": action_id,
        "available": found is not None,
        "reason": found["reason"] if found else "",
    }


def _quest_from_tension(tension: dict[str, Any], affordances: list[dict[str, Any]]) -> QuestCandidate | None:
    tension_id = tension["tension_id"]
    if tension_id == "tension_guard_trust_low":
        trust_evidence = tension["evidence"][0]
        return QuestCandidate(
            quest_id="quest_gain_guard_trust",
            title="取得守卫信任",
            reason=tension["reason"],
            depends_on=["guard_alos.trust.player < 5"],
            required_state=[{"entity_id": "guard_alos", "attr": "trust.player", "operator": ">=", "value": 5}],
            reward={"unlock_affordance": "ask_guard_open_gate"},
            failure_consequence={"relation_delta": {"entity_id": "guard_alos", "attr": "hostility.player", "delta": 1}},
            evidence=[trust_evidence],
            tension_id=tension_id,
        )
    if tension_id == "tension_locked_iron_gate":
        route = next((action for action in ["show_pass_token", "request_access", "ask_guard_open_gate", "unlock_gate_with_key"] if any(item["action_id"] == action for item in affordances)), "show_pass_token")
        return QuestCandidate(
            quest_id="quest_find_legal_entry",
            title="寻找合法通行方式",
            reason="铁门仍未打开，玩家需要钥匙、通行令或守卫放行。",
            depends_on=["iron_gate.open == false"],
            required_state=[{"entity_id": "iron_gate", "attr": "open", "operator": "==", "value": True}],
            reward={"location_access": "inner_city"},
            failure_consequence={"state": {"entity_id": "iron_gate", "attr": "open", "value": False}},
            evidence=tension["evidence"] + [_affordance_evidence(route, affordances)],
            tension_id=tension_id,
        )
    if tension_id == "tension_key_theft_rumor":
        return QuestCandidate(
            quest_id="quest_clear_key_theft_rumor",
            title="澄清偷钥匙传闻",
            reason="村里存在玩家偷钥匙的传闻，可能影响 NPC 行为。",
            depends_on=[item["memory_id"] for item in tension["evidence"] if item.get("source_type") == "memory"],
            required_state=[{"memory_scope": "rumor", "operator": "resolved", "topic": "key_theft"}],
            reward={"relation_delta": {"entity_id": "guard_alos", "attr": "trust.player", "delta": 1}},
            failure_consequence={"relation_delta": {"entity_id": "guard_alos", "attr": "hostility.player", "delta": 1}},
            evidence=tension["evidence"],
            tension_id=tension_id,
        )
    if tension_id == "tension_warehouse_locked":
        return QuestCandidate(
            quest_id="quest_access_warehouse",
            title="取得仓库调查权限",
            reason=tension["reason"],
            depends_on=["warehouse.locked == true"],
            required_state=[{"entity_id": "warehouse", "attr": "locked", "operator": "==", "value": False}],
            reward={"unlock_affordance": "inspect_warehouse"},
            failure_consequence={"state": {"entity_id": "warehouse", "attr": "locked", "value": True}},
            evidence=tension["evidence"],
            tension_id=tension_id,
        )
    if tension_id == "tension_grain_trade_blocked":
        return QuestCandidate(
            quest_id="quest_investigate_grain_trade",
            title="调查粮食交易阻滞",
            reason=tension["reason"],
            depends_on=["warehouse.grain_stock <= 12"],
            required_state=[{"entity_id": "warehouse", "attr": "grain_stock", "operator": ">", "value": 12}],
            reward={"relation_delta": {"entity_id": "village_chief", "attr": "trust.merchant_borin", "delta": 1}},
            failure_consequence={"relation_delta": {"entity_id": "merchant_borin", "attr": "trust.player", "delta": -1}},
            evidence=tension["evidence"],
            tension_id=tension_id,
        )
    return None


def _evidence_is_traceable(evidence: dict[str, Any]) -> bool:
    if evidence.get("source_type") == "state":
        return bool(evidence.get("entity_id") and evidence.get("attr"))
    if evidence.get("source_type") == "memory":
        return bool(evidence.get("memory_id") and evidence.get("truth_scope"))
    if evidence.get("source_type") == "affordance":
        return bool(evidence.get("action_id"))
    return False


def _required_state_is_grounded(required_state: dict[str, Any], entity_ids: set[str]) -> bool:
    entity_id = required_state.get("entity_id")
    if entity_id is not None:
        return entity_id in entity_ids and bool(required_state.get("attr"))
    return bool(required_state.get("memory_scope"))


def _effect_is_grounded(effect: dict[str, Any], entity_ids: set[str]) -> bool:
    if "unlock_affordance" in effect:
        return bool(effect["unlock_affordance"])
    if "location_access" in effect:
        return effect["location_access"] in entity_ids
    nested = effect.get("relation_delta") or effect.get("state")
    if nested:
        return nested.get("entity_id") in entity_ids and bool(nested.get("attr"))
    return False
