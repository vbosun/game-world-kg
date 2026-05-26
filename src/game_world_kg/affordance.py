from __future__ import annotations

import sqlite3
from typing import Any

from .action_template import ActionTemplateEngine
from .projector import StateProjector


class AffordanceEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.state = StateProjector(conn)

    def list_for_player(self, world_id: str, actor_id: str = "player") -> list[dict[str, Any]]:
        templated = ActionTemplateEngine(self.conn).list_for_actor(world_id, actor_id)
        if templated:
            return templated

        player_location = self.state.get_state(world_id, actor_id, "location")
        guard_location = self.state.get_state(world_id, "guard_alos", "location")
        pass_holder = self.state.get_state(world_id, "pass_token", "holder")
        key_holder = self.state.get_state(world_id, "silver_key", "holder")
        trust = self.state.get_state(world_id, "guard_alos", "trust.player") or 0
        gold = self.state.get_state(world_id, actor_id, "gold") or 0
        gate_open = self.state.get_state(world_id, "iron_gate", "open") is True

        affordances: list[dict[str, Any]] = []
        if player_location == guard_location:
            affordances.append(self._action("talk_to_guard", "和守卫交谈", "guard_alos", "low", "守卫位于当前地点"))
            if pass_holder == actor_id:
                affordances.append(
                    self._action("show_pass_token", "向守卫出示通行令", "guard_alos", "low", "玩家持有通行令，守卫有检查权限")
                )
            if trust >= 5 and not gate_open:
                affordances.append(
                    self._action("ask_guard_open_gate", "请求守卫放行", "guard_alos", "low", "守卫信任达到放行阈值")
                )
            if gold > 0:
                affordances.append(self._action("bribe_guard", "贿赂守卫", "guard_alos", "medium", "玩家有钱袋，守卫在场"))
            affordances.append(self._action("steal_silver_key", "偷取银钥匙", "guard_alos", "high", "守卫携带或看管银钥匙"))

        if key_holder == actor_id and not gate_open:
            affordances.append(self._action("unlock_gate_with_key", "用银钥匙打开铁门", "iron_gate", "low", "玩家持有银钥匙"))

        if gate_open and player_location == "village_gate":
            affordances.append(self._action("enter_inner_city", "进入内城", "inner_city", "low", "铁门已经打开"))

        return affordances

    @staticmethod
    def _action(action_id: str, label: str, target_id: str, risk: str, reason: str) -> dict[str, str]:
        return {
            "action_id": action_id,
            "label": label,
            "target_id": target_id,
            "risk": risk,
            "reason": reason,
        }
