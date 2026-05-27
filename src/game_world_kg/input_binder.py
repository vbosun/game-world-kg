from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BoundAction:
    action_id: str
    target_id: str | None
    label: str
    confidence: float
    reason: str


class InputBinder:
    def bind(self, player_input: str, affordances: list[dict[str, Any]], *, selected_action_id: str | None = None, selected_target_id: str | None = None) -> BoundAction | None:
        if selected_action_id:
            selected = self._find_selected(affordances, selected_action_id, selected_target_id)
            if selected is not None:
                return self._bound(selected, 1.0, "selected_current_affordance")
            return None

        text = _normalize(player_input)
        if not text:
            return None

        for affordance in affordances:
            label = _normalize(affordance.get("label", ""))
            action_id = _normalize(affordance.get("action_id", ""))
            target_id = _normalize(affordance.get("target_id", ""))
            if text == label or text == action_id or (target_id and text == target_id):
                return self._bound(affordance, 0.95, "exact_current_affordance")

        for affordance in affordances:
            label = _normalize(affordance.get("label", ""))
            target_id = _normalize(affordance.get("target_id", ""))
            if (label and (label in text or text in label)) or (target_id and target_id in text):
                return self._bound(affordance, 0.8, "fuzzy_current_affordance")

        return None

    @staticmethod
    def _find_selected(affordances: list[dict[str, Any]], action_id: str, target_id: str | None) -> dict[str, Any] | None:
        for affordance in affordances:
            if affordance.get("action_id") != action_id:
                continue
            if target_id is None or (affordance.get("target_id") or None) == target_id:
                return affordance
        return None

    @staticmethod
    def _bound(affordance: dict[str, Any], confidence: float, reason: str) -> BoundAction:
        return BoundAction(
            action_id=affordance["action_id"],
            target_id=affordance.get("target_id") or None,
            label=affordance.get("label") or affordance["action_id"],
            confidence=confidence,
            reason=reason,
        )


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "")
