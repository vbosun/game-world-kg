from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .config import JsonRepairConfig
from .llm import AnthropicClient, LLMClient, LLMError, OpenAICompatibleClient


@dataclass
class JsonRepairAttempt:
    attempt: int
    error: str
    start_line: int
    end_line: int
    fragment_before: str
    fragment_after: str | None
    changed: bool
    success_after_replace: bool | None
    repair_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JsonRepairResult:
    success: bool
    parsed_json: dict[str, Any] | None
    repaired_text: str | None
    error: str | None
    attempts: list[JsonRepairAttempt]
    json_repair_used: bool
    json_repair_mode: str


def extract_json_candidate(raw_text: str) -> str:
    stripped = raw_text.strip().lstrip("\ufeff")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, count=1, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped, count=1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def cheap_sanitize_json_text(text: str) -> str:
    candidate = extract_json_candidate(text).strip().lstrip("\ufeff")
    return re.sub(r",\s*([}\]])", r"\1", candidate)


def format_json_error(text: str, exc: json.JSONDecodeError) -> str:
    lines = text.splitlines() or [text]
    line_index = max(0, exc.lineno - 1)
    start = max(0, line_index - 3)
    end = min(len(lines), line_index + 4)
    context = "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))
    return f"{exc.msg} at line {exc.lineno}, column {exc.colno}, char {exc.pos}.\nContext:\n{context}"


def extract_error_window(text: str, lineno: int, before: int, after: int) -> tuple[int, int, str]:
    lines = text.splitlines()
    line_index = max(0, lineno - 1)
    start = max(0, line_index - before)
    end = min(len(lines), line_index + after + 1)
    return start, end, "\n".join(lines[start:end])


def replace_error_window(text: str, start: int, end: int, repaired_fragment: str) -> str:
    lines = text.splitlines()
    replacement = repaired_fragment.strip("\n").splitlines()
    return "\n".join([*lines[:start], *replacement, *lines[end:]])


class LocalizedJsonRepairer:
    def __init__(self, client: LLMClient | None, config: JsonRepairConfig) -> None:
        self.client = client
        self.config = config

    def parse_or_repair(self, raw_text: str) -> JsonRepairResult:
        text = cheap_sanitize_json_text(extract_json_candidate(raw_text))
        attempts: list[JsonRepairAttempt] = []
        repair_available = self.config.enabled and self.client is not None and self.config.mode == "localized"

        for attempt_index in range(self.config.max_attempts + 1):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                error = format_json_error(text, exc)
                if not repair_available or attempt_index >= self.config.max_attempts:
                    return JsonRepairResult(False, None, text, error, attempts, bool(attempts), self.config.mode)
                start, end, fragment = extract_error_window(
                    text,
                    lineno=exc.lineno,
                    before=self.config.window_lines,
                    after=self.config.window_lines,
                )
                try:
                    repaired_fragment = self.repair_fragment(fragment, error, start + 1, end)
                except Exception as repair_exc:
                    attempts.append(
                        JsonRepairAttempt(
                            attempt=attempt_index + 1,
                            error=error,
                            start_line=start + 1,
                            end_line=end,
                            fragment_before=fragment,
                            fragment_after=None,
                            changed=False,
                            success_after_replace=None,
                            repair_error=f"{type(repair_exc).__name__}: {repair_exc}",
                        )
                    )
                    return JsonRepairResult(False, None, text, error, attempts, True, self.config.mode)
                new_text = replace_error_window(text, start, end, repaired_fragment)
                changed = new_text != text
                success_after_replace: bool | None = None
                if changed:
                    try:
                        json.loads(new_text)
                        success_after_replace = True
                    except json.JSONDecodeError:
                        success_after_replace = False
                attempts.append(
                    JsonRepairAttempt(
                        attempt=attempt_index + 1,
                        error=error,
                        start_line=start + 1,
                        end_line=end,
                        fragment_before=fragment,
                        fragment_after=repaired_fragment,
                        changed=changed,
                        success_after_replace=success_after_replace,
                    )
                )
                if not changed:
                    return JsonRepairResult(False, None, text, "repair produced no change", attempts, True, self.config.mode)
                text = new_text
                continue
            if not isinstance(parsed, dict):
                return JsonRepairResult(False, None, text, "JSON response was not an object", attempts, bool(attempts), self.config.mode)
            return JsonRepairResult(True, parsed, text if attempts else None, None, attempts, bool(attempts), self.config.mode)
        return JsonRepairResult(False, None, text, "max attempts exceeded", attempts, bool(attempts), self.config.mode)

    def repair_fragment(self, fragment: str, error: str, start_line: int, end_line: int) -> str:
        if self.client is None:
            raise LLMError("JSON repair client is not configured")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a local JSON syntax patcher.\n\n"
                    "You will receive a small broken JSON fragment from a larger JSON object.\n\n"
                    "Task:\n"
                    "Fix only this fragment so it becomes valid JSON when inserted back into the original document.\n\n"
                    "Rules:\n"
                    "- Preserve all keys, values, ids, names, Chinese text, and ordering.\n"
                    "- Do not add new world content.\n"
                    "- Do not remove fields.\n"
                    "- Do not rewrite schema.\n"
                    "- Do not fix WorldSpec validation.\n"
                    "- Do not add missing required fields.\n"
                    "- Do not convert string effects into objects.\n"
                    "- Do not convert natural-language objectives into objects.\n"
                    "- Only fix JSON syntax: missing commas, trailing commas, unescaped quotes, broken braces/brackets, markdown fences, or comments.\n"
                    "- Return only the repaired fragment.\n"
                    "- No markdown.\n"
                    "- No explanation."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "json_error": error,
                        "fragment_start_line": start_line,
                        "fragment_end_line": end_line,
                        "fragment": fragment,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        return self.client.complete_text(
            messages,
            temperature=self.config.temperature,
            timeout_seconds=self.config.timeout_seconds,
        ).strip("\n")


def build_json_repair_client_from_env() -> LLMClient | None:
    config = JsonRepairConfig.from_env()
    if not config.enabled:
        return None
    llm_config = config.to_llm_config()
    if config.provider == "openai_compatible":
        return OpenAICompatibleClient(llm_config)
    if config.provider == "anthropic":
        return AnthropicClient(llm_config)
    raise LLMError(f"unsupported JSON repair provider: {config.provider}")
