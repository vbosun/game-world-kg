from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from .config import LLMConfig
from .rules import RuleResult


LEGACY_ACTION_IDS = {
    "move_to_location",
    "talk_to_guard",
    "show_pass_token",
    "unlock_gate_with_key",
    "ask_guard_open_gate",
    "bribe_guard",
    "steal_silver_key",
    "enter_inner_city",
    "request_access",
    "ask_about_rumor",
    "clarify_rumor",
    "inspect_warehouse",
    "request_warehouse_access",
    "trade_grain",
    "talk_to_mira",
    "talk_to_borin",
    "talk_to_chief",
    "talk_to_warehouse_keeper",
    "rumor_player_stole_key",
    "guard_suspects_player",
}
ALLOWED_ACTION_IDS = LEGACY_ACTION_IDS


class ActionCandidate(BaseModel):
    action_id: str
    target_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = ""

    def valid_action_id(self) -> str | None:
        if self.action_id in LEGACY_ACTION_IDS:
            return self.action_id
        return None


class LLMClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        ...

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4, timeout_seconds: float | None = None) -> str:
        ...


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        text = self.complete_text(messages, temperature=temperature, timeout_seconds=timeout_seconds)
        return _loads_json_object(text)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4, timeout_seconds: float | None = None) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            timeout = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(str(exc)) from exc
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("invalid OpenAI-compatible response") from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


class LLMError(RuntimeError):
    pass


@dataclass
class ActionParser:
    client: LLMClient | None

    def parse(self, player_input: str, state_summary: dict[str, Any], affordances: list[dict[str, Any]], *, require_current_affordance: bool = False) -> ActionCandidate | None:
        if self.client is None:
            return None
        available = {(item["action_id"], item.get("target_id") or None) for item in affordances}
        available_action_ids = {item[0] for item in available}
        messages = [
            {
                "role": "system",
                "content": (
                    "你是游戏行动解析器。只输出 JSON 对象，不要解释。"
                    "必须从 affordances 中选择当前可用的 action_id 和 target_id。"
                    f"当前可用 action_id 只能是: {', '.join(sorted(available_action_ids))}。"
                    "如果 affordance 有 target_id，必须原样复制 target_id。"
                    "不要决定行动是否合法，规则引擎会裁判。"
                    "格式: {\"action_id\":\"...\",\"target_id\":\"...\",\"confidence\":0.0,\"reason\":\"...\"}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "player_input": player_input,
                        "state_summary": state_summary,
                        "affordances": affordances,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            candidate = ActionCandidate.model_validate(self.client.complete_json(messages, temperature=0))
        except (LLMError, ValidationError):
            return None
        target = candidate.target_id or None
        if require_current_affordance and (candidate.action_id, target) not in available and candidate.action_id not in {action_id for action_id, target_id in available if target_id is None}:
            return None
        if not require_current_affordance and candidate.valid_action_id() is None:
            return None
        return candidate


@dataclass
class Narrator:
    client: LLMClient | None

    def narrate(
        self,
        player_input: str,
        rule_result: RuleResult,
        events: list[dict[str, Any]],
        state_summary: dict[str, Any],
        affordances: list[dict[str, Any]],
    ) -> str:
        if self.client is None:
            return rule_result.narration
        messages = [
            {
                "role": "system",
                "content": (
                    "你是游戏旁白。只能根据输入的规则结算结果写叙事反馈。"
                    "不得添加新的状态变化、物品转移、开门结果或 NPC 知识。"
                    "如果 accepted 为 false，要明确行动被规则拦截。"
                    "输出一小段中文叙事，不要输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "player_input": player_input,
                        "rule_result": {
                            "action_id": rule_result.action_id,
                            "accepted": rule_result.accepted,
                            "reason": rule_result.reason,
                            "fallback_narration": rule_result.narration,
                        },
                        "events": events,
                        "state_summary": state_summary,
                        "affordances": affordances,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            narration = self.client.complete_text(messages, temperature=0.4).strip()
        except LLMError:
            return rule_result.narration
        return narration or rule_result.narration


def build_llm_client_from_env() -> OpenAICompatibleClient | None:
    config = LLMConfig.from_env()
    if not config.enabled:
        return None
    return OpenAICompatibleClient(config)


def _loads_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError("LLM response did not contain a JSON object")
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise LLMError("LLM response JSON was not an object")
    return value
