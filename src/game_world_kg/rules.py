from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .action_template import ActionResolver
from .affordance import AffordanceEngine
from .events import EventLog, EventRecord
from .projector import StateProjector, delta


@dataclass(frozen=True)
class RuleResult:
    action_id: str
    accepted: bool
    reason: str
    narration: str
    events: list[EventRecord]


class RuleEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.state = StateProjector(conn)

    def resolve_turn(
        self,
        world_id: str,
        turn_id: str,
        turn_index: int,
        player_input: str,
        action_id: str | None = None,
        target_id: str | None = None,
        extractor: str = "rule_parser_v1",
        confidence: float = 0.9,
        evidence_source_id: str | None = None,
        evidence_span: list[int] | None = None,
    ) -> RuleResult:
        runtime_mode = self._runtime_mode(world_id)
        if action_id is None and runtime_mode != "template_only":
            action_id, target_id = self.parse_action_candidate(player_input)
        if action_id is None:
            return self._reject("__unparsed__", "无法从当前可行动作中解析出合法行动。")
        evidence = [{"source_id": evidence_source_id or turn_id, "span": evidence_span or [0, len(player_input)], "extractor": extractor, "confidence": confidence}]
        templated = ActionResolver(self.conn).resolve(world_id, turn_id, turn_index, action_id, evidence, target_id=target_id)
        if templated is not None:
            return RuleResult(
                templated.action_id,
                templated.accepted,
                templated.reason,
                templated.narration,
                templated.events,
            )
        if runtime_mode == "template_only":
            return self._reject(action_id, "action template not found")
        if action_id == "show_pass_token":
            return self._show_pass_token(world_id, turn_id, turn_index, evidence)
        if action_id == "unlock_gate_with_key":
            return self._unlock_gate_with_key(world_id, turn_id, turn_index, evidence)
        if action_id == "ask_guard_open_gate":
            return self._ask_guard_open_gate(world_id, turn_id, turn_index, evidence)
        if action_id == "bribe_guard":
            return self._bribe_guard(world_id, turn_id, turn_index, evidence)
        if action_id == "steal_silver_key":
            return self._steal_silver_key(world_id, turn_id, turn_index, evidence)
        if action_id == "rumor_player_stole_key":
            return self._rumor_player_stole_key(world_id, turn_id, turn_index, evidence)
        if action_id == "guard_suspects_player":
            return self._guard_suspects_player(world_id, turn_id, turn_index, evidence)
        return RuleResult(
            action_id="talk_to_guard",
            accepted=True,
            reason="守卫在当前地点，可进行对话。",
            narration="守卫阿洛斯看向你，等待你说明来意。",
            events=[],
        )

    @staticmethod
    def parse_action(text: str) -> str:
        return RuleEngine.parse_action_candidate(text)[0]

    @staticmethod
    def parse_action_candidate(text: str) -> tuple[str, str | None]:
        target_id = RuleEngine.parse_location_target(text)
        if target_id is not None and any(word in text for word in ["去", "前往", "走到", "到", "进入", "进", "移动"]):
            if target_id != "inner_city" or "进入内城" not in text:
                return "move_to_location", target_id
        if "有人说" in text or "谣言" in text or "传闻" in text:
            if "偷" in text and "钥匙" in text:
                return "rumor_player_stole_key", None
        if any(word in text for word in ["澄清", "解释", "可疑旅人"]) and any(word in text for word in ["谣言", "传闻", "银钥匙", "钥匙"]):
            return "clarify_rumor", None
        if any(word in text for word in ["询问", "打听", "问"]) and any(word in text for word in ["谣言", "传闻", "米拉"]):
            return "ask_about_rumor", None
        if any(word in text for word in ["检查", "调查", "查看"]) and "仓库" in text:
            return "inspect_warehouse", None
        if any(word in text for word in ["请求", "申请", "权限", "钥匙"]) and "仓库" in text:
            return "request_warehouse_access", None
        if any(word in text for word in ["交易", "协商", "买粮", "粮食"]) and any(word in text for word in ["伯林", "商人", "粮"]):
            return "trade_grain", None
        if "怀疑" in text and "钥匙" in text:
            return "guard_suspects_player", None
        if "通行令" in text and any(word in text for word in ["出示", "递", "交给", "给守卫"]):
            return "show_pass_token", None
        if "钥匙" in text and any(word in text for word in ["开门", "打开", "开铁门"]):
            return "unlock_gate_with_key", None
        if "放行" in text or "进去" in text or "进入内城" in text:
            if "进入内城" in text:
                return "enter_inner_city", None
            return "ask_guard_open_gate", None
        if "贿赂" in text or "钱袋" in text:
            return "bribe_guard", None
        if "偷" in text and "钥匙" in text:
            return "steal_silver_key", None
        if "米拉" in text:
            return "talk_to_mira", None
        if "伯林" in text or "商人" in text:
            return "talk_to_borin", None
        if "村长" in text:
            return "talk_to_chief", None
        if "仓库管理员" in text:
            return "talk_to_warehouse_keeper", None
        if "守卫" in text or "阿洛斯" in text:
            return "talk_to_guard", None
        return "talk_to_guard", None

    @staticmethod
    def parse_location_target(text: str) -> str | None:
        aliases = {
            "village_gate": ["村口", "城门", "门口"],
            "village_square": ["村广场", "广场"],
            "tavern": ["酒馆", "旅店"],
            "market_stall": ["市集", "摊位", "市场"],
            "well": ["井边", "水井", "井"],
            "warehouse": ["仓库"],
            "guard_room": ["守卫室", "岗亭"],
            "inner_city": ["内城"],
        }
        for location_id, words in aliases.items():
            if any(word in text for word in words):
                return location_id
        return None

    def _show_pass_token(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        if not self._same_location(world_id, "player", "guard_alos"):
            return self._reject("show_pass_token", "守卫不在当前位置，不能出示通行令。")
        if self.state.get_state(world_id, "pass_token", "holder") != "player":
            return self._reject("show_pass_token", "玩家没有通行令，规则拒绝该行动。")
        trust_old = self.state.get_state(world_id, "guard_alos", "trust.player") or 0
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                (
                    "TRANSFER_ITEM",
                    "player",
                    {"item_id": "pass_token", "from": "player", "to": "guard_alos"},
                    ["player", "guard_alos", "pass_token"],
                    [delta("pass_token", "holder", "player", "guard_alos")],
                ),
                (
                    "CHANGE_RELATION",
                    "system",
                    {"src": "guard_alos", "rel": "TRUSTS", "dst": "player", "delta": 2, "value": trust_old + 2},
                    ["guard_alos", "player"],
                    [delta("guard_alos", "trust.player", trust_old, trust_old + 2, 2)],
                ),
                (
                    "ADD_MEMORY",
                    "system",
                    {
                        "owner_id": "guard_alos",
                        "memory_text": "玩家主动出示了合法通行令。",
                        "truth_scope": "npc",
                        "salience": 0.8,
                        "valence": 0.2,
                    },
                    ["guard_alos", "player", "pass_token"],
                    [],
                ),
            ],
            evidence,
        )
        return RuleResult("show_pass_token", True, "玩家持有通行令且守卫在场。", "守卫接过通行令，仔细看了看，神色缓和下来。", events)

    def _unlock_gate_with_key(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        if self.state.get_state(world_id, "silver_key", "holder") != "player":
            return self._reject("unlock_gate_with_key", "玩家没有银钥匙，不能用钥匙打开铁门。")
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                (
                    "SET_STATE",
                    "player",
                    {"entity_id": "iron_gate", "attr": "locked", "value": False},
                    ["player", "iron_gate", "silver_key"],
                    [delta("iron_gate", "locked", True, False)],
                ),
                (
                    "SET_STATE",
                    "player",
                    {"entity_id": "iron_gate", "attr": "open", "value": True},
                    ["player", "iron_gate", "silver_key"],
                    [delta("iron_gate", "open", False, True)],
                ),
            ],
            evidence,
        )
        return RuleResult("unlock_gate_with_key", True, "玩家持有银钥匙。", "银钥匙转动锁芯，铁门缓缓打开。", events)

    def _ask_guard_open_gate(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        trust = self.state.get_state(world_id, "guard_alos", "trust.player") or 0
        if trust < 5:
            return self._reject("ask_guard_open_gate", "守卫信任不足 5，不会主动放行。")
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                ("SET_STATE", "guard_alos", {"entity_id": "iron_gate", "attr": "locked", "value": False}, ["guard_alos", "iron_gate"], [delta("iron_gate", "locked", True, False)]),
                ("SET_STATE", "guard_alos", {"entity_id": "iron_gate", "attr": "open", "value": True}, ["guard_alos", "iron_gate"], [delta("iron_gate", "open", False, True)]),
            ],
            evidence,
        )
        return RuleResult("ask_guard_open_gate", True, "守卫信任达到 5。", "阿洛斯点点头，替你拉开了铁门。", events)

    def _bribe_guard(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        if not self._same_location(world_id, "player", "guard_alos"):
            return self._reject("bribe_guard", "守卫不在当前位置，不能贿赂。")
        gold = self.state.get_state(world_id, "player", "gold") or 0
        if gold <= 0:
            return self._reject("bribe_guard", "玩家没有钱袋，不能贿赂。")
        trust_old = self.state.get_state(world_id, "guard_alos", "trust.player") or 0
        reputation_old = self.state.get_state(world_id, "player", "reputation") or 0
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                ("DELTA_RESOURCE", "player", {"entity_id": "player", "attr": "gold", "delta": -1}, ["player"], [delta("player", "gold", gold, gold - 1, -1)]),
                ("DELTA_RESOURCE", "system", {"entity_id": "player", "attr": "reputation", "delta": -1}, ["player"], [delta("player", "reputation", reputation_old, reputation_old - 1, -1)]),
                ("CHANGE_RELATION", "system", {"src": "guard_alos", "rel": "TRUSTS", "dst": "player", "delta": 1, "value": trust_old + 1}, ["guard_alos", "player"], [delta("guard_alos", "trust.player", trust_old, trust_old + 1, 1)]),
            ],
            evidence,
        )
        return RuleResult("bribe_guard", True, "玩家有钱袋且守卫在场。", "阿洛斯收下硬币，却用更低的声音提醒你别让村长看见。", events)

    def _steal_silver_key(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        hostility_old = self.state.get_state(world_id, "guard_alos", "hostility.player") or 0
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                ("CHANGE_RELATION", "system", {"src": "guard_alos", "rel": "OPPOSES", "dst": "player", "delta": 2, "value": hostility_old + 2}, ["guard_alos", "player"], [delta("guard_alos", "hostility.player", hostility_old, hostility_old + 2, 2)]),
                ("ADD_MEMORY", "system", {"owner_id": "guard_alos", "memory_text": "玩家试图偷取银钥匙。", "truth_scope": "npc", "salience": 0.9, "valence": -0.8}, ["guard_alos", "player", "silver_key"], []),
            ],
            evidence,
        )
        return RuleResult("steal_silver_key", True, "MVP 固定结算：偷钥匙失败并触发敌意。", "你刚伸手，阿洛斯便按住了你的手腕，眼神立刻冷了下来。", events)

    def _rumor_player_stole_key(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                (
                    "ADD_MEMORY",
                    "system",
                    {
                        "owner_id": "village",
                        "memory_text": "村里有人说玩家偷了钥匙。",
                        "truth_scope": "rumor",
                        "salience": 0.6,
                        "valence": -0.4,
                        "confidence": 0.7,
                    },
                    ["player", "silver_key"],
                    [],
                )
            ],
            evidence,
        )
        return RuleResult("rumor_player_stole_key", True, "谣言进入 rumor 记忆，不修改 canonical。", "流言在村口散开，但它并没有改变钥匙真正的归属。", events)

    def _guard_suspects_player(self, world_id: str, turn_id: str, turn_index: int, evidence: list[dict[str, Any]]) -> RuleResult:
        events = self._append_and_apply(
            world_id,
            turn_id,
            turn_index,
            [
                (
                    "ADD_MEMORY",
                    "system",
                    {
                        "owner_id": "guard_alos",
                        "memory_text": "守卫怀疑玩家和银钥匙失窃有关。",
                        "truth_scope": "npc",
                        "salience": 0.7,
                        "valence": -0.5,
                        "confidence": 0.8,
                    },
                    ["guard_alos", "player", "silver_key"],
                    [],
                )
            ],
            evidence,
        )
        return RuleResult("guard_suspects_player", True, "主观怀疑进入 npc 记忆，不修改 canonical。", "阿洛斯只是保留怀疑，钥匙的真实归属没有变化。", events)

    def _append_and_apply(
        self,
        world_id: str,
        turn_id: str,
        turn_index: int,
        specs: list[tuple[str, str, dict[str, Any], list[str], list[Any]]],
        evidence: list[dict[str, Any]],
    ) -> list[EventRecord]:
        log = EventLog(self.conn)
        events: list[EventRecord] = []
        for event_type, actor_id, payload, participants, state_deltas in specs:
            event = log.append(
                world_id,
                turn_id,
                turn_index,
                event_type,
                actor_id,
                payload,
                participants=participants,
                state_deltas=state_deltas,
                evidence_refs=evidence,
            )
            self.state.apply_event(event)
            events.append(event)
        return events

    def _same_location(self, world_id: str, a: str, b: str) -> bool:
        return self.state.get_state(world_id, a, "location") == self.state.get_state(world_id, b, "location")

    def _runtime_mode(self, world_id: str) -> str:
        row = self.conn.execute("SELECT runtime_mode FROM worlds WHERE id = ?", (world_id,)).fetchone()
        return row["runtime_mode"] if row and row["runtime_mode"] else "legacy_demo"

    @staticmethod
    def _reject(action_id: str, reason: str) -> RuleResult:
        return RuleResult(action_id, False, reason, f"{reason}", [])


def current_affordances(conn: sqlite3.Connection, world_id: str) -> list[dict[str, Any]]:
    return AffordanceEngine(conn).list_for_player(world_id)
