"""Task 1: Verify error classification in WorldSpecGenerator."""
from __future__ import annotations

from game_world_kg.llm import LLMError
from game_world_kg.worldspec import WorldSpecGenerator


class JSONParseErrorLLM:
    """Simulates LLM that returns unparseable text."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        self.last_raw_text = "This is not JSON, just random text."
        return self.last_raw_text


class PydanticValidationErrorLLM:
    """Simulates LLM that returns valid JSON but fails schema."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        self.last_raw_text = '{"world_id": "test_world", "title": "Test"}'
        return self.last_raw_text


class RuntimeErrorLLM:
    """Simulates LLM that raises a non-LLM error."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        raise ConnectionError("network timeout")


def test_llm_json_parse_error_is_classified() -> None:
    """LLMError → error_type = 'json_parse_error'."""
    gen = WorldSpecGenerator(JSONParseErrorLLM())
    result = gen.generate("test idea")
    assert result is not None  # Falls back to sample
    assert gen.last_error_type == "json_parse_error"
    assert gen.last_json_parse_error is not None
    assert "not JSON" in gen.last_json_parse_error or "Expecting value" in gen.last_json_parse_error
    assert gen.last_pydantic_error is None


def test_pydantic_validation_error_is_classified() -> None:
    """Pydantic ValidationError → error_type = 'pydantic_validation_error'."""
    gen = WorldSpecGenerator(PydanticValidationErrorLLM())
    result = gen.generate("test idea")
    assert result is not None  # Falls back to sample
    assert gen.last_error_type == "pydantic_validation_error"
    assert gen.last_pydantic_error is not None
    assert gen.last_json_parse_error is None
    assert gen.last_candidate_payload is not None  # Payload was parsed


def test_runtime_error_is_classified() -> None:
    """Non-LLM, non-Pydantic error → error_type = 'runtime_error'."""
    gen = WorldSpecGenerator(RuntimeErrorLLM())
    result = gen.generate("test idea")
    assert result is not None
    assert gen.last_error_type == "runtime_error"
    assert "ConnectionError" in gen.last_error


def test_generation_trace_records_error_type() -> None:
    """After LLM failure, generator fields must all be populated consistently."""
    gen = WorldSpecGenerator(JSONParseErrorLLM())
    gen.generate("test idea")

    assert gen.last_source == "sample_fallback"
    assert gen.last_error_type == "json_parse_error"
    assert gen.last_error is not None
    assert gen.last_json_parse_error is not None
    # Fields for successful path should be None
    assert gen.last_pydantic_error is None
    assert not gen.repair_attempted
    assert not gen.repair_success
