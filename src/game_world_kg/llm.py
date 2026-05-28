from __future__ import annotations

import json
import http.client
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
        self.last_raw_text: str | None = None

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        text = self.complete_text(messages, temperature=temperature, timeout_seconds=timeout_seconds)
        self.last_raw_text = text
        return _loads_json_object(text)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4, timeout_seconds: float | None = None) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, http.client.IncompleteRead) as exc:
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


class AnthropicClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.last_raw_text: str | None = None

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        text = self.complete_text(messages, temperature=temperature, timeout_seconds=timeout_seconds)
        self.last_raw_text = text
        return _loads_json_object(text)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4, timeout_seconds: float | None = None) -> str:
        system, anthropic_messages = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        request = urllib.request.Request(
            f"{self.config.base_url}/messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            timeout = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"Anthropic HTTP {exc.code}: {error_body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, http.client.IncompleteRead) as exc:
            raise LLMError(str(exc)) from exc
        try:
            parts = [item.get("text", "") for item in body["content"] if item.get("type") == "text"]
            text = "".join(parts)
            if not text:
                raise LLMError("empty Anthropic text response")
            return text
        except (KeyError, TypeError) as exc:
            raise LLMError("invalid Anthropic response") from exc

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
        }
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
                    "如果没有 affordance 匹配玩家输入，返回 confidence <= 0.2，且不要发明 action_id。"
                    "绝不能输出 affordances 中不存在的 action_id。"
                    "如果目标含糊，降低 confidence，而不是发明 target_id。"
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
                    "Only describe events and state changes present in rule_result/events."
                    "不得添加新的状态变化、物品转移、开门结果或 NPC 知识。"
                    "不得暗示隐藏后果、隐藏知识、物品栏变化、关系变化或任务进度，除非它们明确出现在 events 中。"
                    "如果 accepted 为 false，要明确行动被规则拦截。"
                    "如果行动被拒绝，把拒绝描述为世界规则或当前状态限制，不要说成模型无能。"
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


def build_llm_client_from_env() -> LLMClient | None:
    config = LLMConfig.from_env()
    if not config.enabled:
        return None
    if config.provider == "anthropic" and not config.api_key:
        return None
    if config.provider == "anthropic":
        return AnthropicClient(config)
    if config.provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleClient(config)
    raise LLMError(f"unsupported LLM provider: {config.provider}")


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
    extracted = stripped[start : end + 1]
    try:
        value = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise LLMError(_json_error_context(extracted, exc)) from exc
    if not isinstance(value, dict):
        raise LLMError("LLM response JSON was not an object")
    return value


def _json_error_context(text: str, error: json.JSONDecodeError, window: int = 3) -> str:
    lines = text.splitlines() or [text]
    line_index = max(0, error.lineno - 1)
    start = max(0, line_index - window)
    end = min(len(lines), line_index + window + 1)
    context = "\n".join(f"{idx + 1}: {lines[idx]}" for idx in range(start, end))
    prefix = text[:160].replace("\n", "\\n")
    suffix = text[-160:].replace("\n", "\\n")
    return (
        f"LLM response contained invalid JSON: {error.msg} "
        f"at line {error.lineno}, column {error.colno}, char {error.pos}.\n"
        f"Context:\n{context}\n"
        f"Extracted prefix: {prefix}\n"
        f"Extracted suffix: {suffix}"
    )


def _to_anthropic_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system_parts: list[str] = []
    converted: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"] = f"{converted[-1]['content']}\n\n{content}"
        else:
            converted.append({"role": role, "content": content})
    if not converted:
        converted.append({"role": "user", "content": ""})
    return "\n\n".join(part for part in system_parts if part), converted
