from __future__ import annotations

import json

from game_world_kg.config import JsonRepairConfig
from game_world_kg.json_repair import (
    LocalizedJsonRepairer,
    extract_error_window,
    extract_json_candidate,
    replace_error_window,
)
from game_world_kg.worldspec import WorldSpecValidator, sample_world_spec
from game_world_kg.worldspec_safe import WorldSpecGenerator


class FakeRepairClient:
    def __init__(self, fragments: list[str]) -> None:
        self.fragments = fragments
        self.calls: list[list[dict[str, str]]] = []

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        self.calls.append(messages)
        return self.fragments.pop(0)

    def complete_json(self, messages, *, temperature=0, timeout_seconds=None):
        raise AssertionError("JSON repair client should only use complete_text")


class EchoRepairClient:
    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        return json.loads(messages[1]["content"])["fragment"]

    def complete_json(self, messages, *, temperature=0, timeout_seconds=None):
        raise AssertionError("JSON repair client should only use complete_text")


class RawWorldSpecLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.last_raw_text = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        self.last_raw_text = self.raw
        return self.raw

    def complete_json(self, messages, *, temperature=0, timeout_seconds=None):
        raise AssertionError("WorldSpec generator should parse raw text itself")


def _config(max_attempts: int = 2, window_lines: int = 1) -> JsonRepairConfig:
    return JsonRepairConfig(enabled=True, max_attempts=max_attempts, window_lines=window_lines)


def test_extract_json_candidate_removes_markdown_fence() -> None:
    raw = "```json\n{\"ok\": true}\n```"

    assert extract_json_candidate(raw) == '{"ok": true}'


def test_extract_json_candidate_strips_prose_before_after_json() -> None:
    raw = "Here is the JSON:\n{\"ok\": true}\nDone."

    assert extract_json_candidate(raw) == '{"ok": true}'


def test_extract_error_window_returns_expected_lines() -> None:
    text = "\n".join(f"line {index}" for index in range(1, 8))

    start, end, fragment = extract_error_window(text, lineno=4, before=1, after=2)

    assert start == 2
    assert end == 6
    assert fragment == "line 3\nline 4\nline 5\nline 6"


def test_replace_error_window_replaces_only_window() -> None:
    text = "a\nbroken\nc"

    assert replace_error_window(text, 1, 2, "fixed") == "a\nfixed\nc"


def test_localized_repair_sends_only_fragment_not_full_json() -> None:
    raw = '{\n  "a": 1\n  "b": 2,\n  "tail": "keep",\n  "deep_tail": "outside"\n}'
    repair = FakeRepairClient(['  "a": 1,\n  "b": 2,\n  "tail": "keep",'])

    result = LocalizedJsonRepairer(repair, _config(window_lines=1)).parse_or_repair(raw)
    user_payload = json.loads(repair.calls[0][1]["content"])

    assert result.success is True
    assert user_payload["fragment"] == '  "a": 1\n  "b": 2,\n  "tail": "keep",'
    assert "deep_tail" not in user_payload["fragment"]


def test_localized_repair_success_after_one_attempt() -> None:
    raw = '{\n  "a": 1\n  "b": 2\n}'
    repair = FakeRepairClient(['  "a": 1,\n  "b": 2\n}'])

    result = LocalizedJsonRepairer(repair, _config()).parse_or_repair(raw)

    assert result.success is True
    assert result.parsed_json == {"a": 1, "b": 2}
    assert result.json_repair_used is True
    assert result.attempts[0].changed is True
    assert result.attempts[0].success_after_replace is True


def test_localized_repair_loops_to_second_error() -> None:
    raw = '{\n  "a": 1,\n  "b": {"x": 1 "y": 2},\n  "c": [1 2]\n}'
    repair = FakeRepairClient(['  "b": {"x": 1, "y": 2},', '  "c": [1, 2]'])

    result = LocalizedJsonRepairer(repair, _config(max_attempts=2, window_lines=0)).parse_or_repair(raw)

    assert result.success is True
    assert result.parsed_json == {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}
    assert len(result.attempts) == 2
    assert result.attempts[0].success_after_replace is False
    assert result.attempts[1].success_after_replace is True


def test_localized_repair_stops_after_max_attempts() -> None:
    raw = '{\n  "a": 1\n  "b": 2\n}'
    repair = FakeRepairClient(['  "a": 1\n  "b": 2'])

    result = LocalizedJsonRepairer(repair, _config(max_attempts=1)).parse_or_repair(raw)

    assert result.success is False
    assert len(result.attempts) == 1


def test_localized_repair_stops_when_no_change() -> None:
    raw = '{\n  "a": 1\n  "b": 2\n}'
    repair = EchoRepairClient()

    result = LocalizedJsonRepairer(repair, _config()).parse_or_repair(raw)

    assert result.success is False
    assert result.error == "repair produced no change"
    assert result.attempts[0].changed is False


def test_json_repair_does_not_handle_validation_error(monkeypatch) -> None:
    payload = sample_world_spec("village").model_dump(mode="json")
    payload["action_templates"][0]["effects"] = ["not an object"]
    repair = FakeRepairClient(["unused"])
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_ENABLED", "true")
    monkeypatch.setattr("game_world_kg.worldspec_safe.build_json_repair_client_from_env", lambda: repair)

    spec = WorldSpecGenerator(RawWorldSpecLLM(json.dumps(payload, ensure_ascii=False))).generate("边境村庄")

    assert spec.world_id.startswith("demo_border_village_")
    assert repair.calls == []


def test_json_repair_prompt_forbids_schema_repair() -> None:
    repair = FakeRepairClient(['{"ok": true}'])
    repairer = LocalizedJsonRepairer(repair, _config())

    repairer.repair_fragment('{"ok": true}', "error", 1, 1)
    system = repair.calls[0][0]["content"]

    assert "Do not fix WorldSpec validation." in system
    assert "Do not add missing required fields." in system
    assert "Do not convert string effects into objects." in system


def test_valid_json_with_schema_error_enters_validator_without_repair() -> None:
    payload = sample_world_spec("village").model_dump(mode="json")
    payload["action_templates"][0]["effects"] = ["not an object"]

    report = WorldSpecValidator().validate(payload)

    assert report["valid"] is False
    assert any(issue["code"] == "action_effect_must_be_object" for issue in report["issues"])
