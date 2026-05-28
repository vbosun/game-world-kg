from __future__ import annotations

from typing import Any


class FeedbackRenderer:
    def render(self, turn_result: dict[str, Any], before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
        changes = self.changes(turn_result.get("events", []), before, after)
        return {
            "accepted": turn_result.get("accepted", False),
            "action_id": turn_result.get("action_id"),
            "narration": turn_result.get("narration", ""),
            "reason": turn_result.get("reason", ""),
            "changes": changes,
            "next_hooks": self.next_hooks(turn_result.get("affordances", []), changes),
        }

    def rejection(self, player_input: str, affordances: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        suggestions = affordances[:3]
        paths = [item["label"] for item in suggestions]
        hint = "、".join(paths) if paths else "先观察周围，寻找可以落地的行动"
        return {
            "accepted": False,
            "action_id": "__unparsed__",
            "narration": f"你现在不能这样做：{reason}。你可以先尝试：{hint}。",
            "reason": reason,
            "changes": [{"type": "rule_rejection", "label": "行动被规则拦截", "detail": player_input, "next_paths": paths}],
            "next_hooks": [{"type": "available_action", "label": item["label"], "action_id": item["action_id"], "target_id": item.get("target_id")} for item in suggestions],
        }

    def changes(self, events: list[dict[str, Any]], before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for event in events:
            event_type = event.get("event_type", "")
            payload = event.get("payload", {})
            if event_type == "MOVE_ENTITY":
                changes.append({"type": "location_change", "entity_id": payload.get("entity_id"), "from": payload.get("from"), "to": payload.get("to"), "label": "位置变化"})
            elif event_type == "TRANSFER_ITEM":
                changes.append({"type": "resource_change", "item_id": payload.get("item_id"), "from": payload.get("from"), "to": payload.get("to"), "label": "资源归属变化"})
            elif event_type == "CHANGE_RELATION":
                changes.append({"type": "relationship_change", "src": payload.get("src"), "dst": payload.get("dst"), "rel": payload.get("rel"), "delta": payload.get("delta"), "value": payload.get("value"), "label": "关系变化"})
            elif event_type == "ADD_MEMORY":
                changes.append({"type": "knowledge_change", "owner_id": payload.get("owner_id"), "truth_scope": payload.get("truth_scope"), "memory_text": payload.get("memory_text"), "label": "记忆或传闻变化"})
            elif event_type == "SET_STATE":
                changes.append({"type": "state_change", "entity_id": payload.get("entity_id"), "attr": payload.get("attr"), "value": payload.get("value"), "scope": payload.get("scope", "canonical"), "label": "状态变化"})
            elif event_type == "DELTA_RESOURCE":
                changes.append({"type": "resource_change", "entity_id": payload.get("entity_id"), "attr": payload.get("attr"), "delta": payload.get("delta"), "scope": payload.get("scope", "canonical"), "label": "资源变化"})
            elif event_type == "ACTION_REJECTED":
                changes.append({"type": "rule_rejection", "label": "行动被规则拦截", "detail": payload.get("reason")})
            elif event_type == "PLAYER_GROWTH":
                changes.append({"type": "growth", "label": "成长", "attr": payload.get("attr"), "delta": payload.get("delta"), "new_value": payload.get("new_value")})
            elif event_type == "WITNESS_ATTEMPT":
                changes.append({"type": "witness", "label": "被目击", "witness_id": event.get("actor_id"), "memory": payload.get("memory_text")})
            else:
                changes.append({"type": "world_event", "event_type": event_type, "label": "世界事件", "payload": payload})

        for entity_id, values in after.items():
            before_values = before.get(entity_id, {})
            for attr, new_value in values.items():
                if before_values.get(attr) == new_value:
                    continue
                if any(change.get("entity_id") == entity_id and change.get("attr") == attr for change in changes):
                    continue
                changes.append({"type": _change_type(attr), "entity_id": entity_id, "attr": attr, "from": before_values.get(attr), "to": new_value, "label": "投影状态变化"})

        if not changes:
            changes.append({"type": "no_state_change", "label": "局势保持", "detail": "这次行动没有改写 canonical 状态，但仍消耗了一个回合。"})
        return changes

    @staticmethod
    def next_hooks(affordances: list[dict[str, Any]], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hooks = [{"type": "available_action", "label": item["label"], "action_id": item["action_id"], "target_id": item.get("target_id")} for item in affordances[:4]]
        if any(change["type"] in {"relationship_change", "knowledge_change", "permission_change"} for change in changes):
            hooks.insert(0, {"type": "new_opportunity", "label": "关系或线索已经变化，看看任务和关系面板。"})
        return hooks


def _change_type(attr: str) -> str:
    if attr.startswith("permission") or attr == "permissions":
        return "permission_change"
    if attr.startswith("identity") or attr == "identity_tags":
        return "identity_change"
    if attr.startswith("knowledge") or attr == "known_clues":
        return "knowledge_change"
    if attr.startswith("skill."):
        return "growth"
    if ".player" in attr:
        return "relationship_change"
    return "state_change"
