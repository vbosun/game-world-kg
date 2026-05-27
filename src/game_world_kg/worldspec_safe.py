from __future__ import annotations

import json
from typing import Any

from .worldspec import WorldIntentExtractor, WorldSpec, WorldSpecValidator
from .worldspec_prompt_templates import build_full_worldspec_prompt
from .worldspec_runtime import WorldSpecNormalizer, WorldSpecRepairer, sample_world_spec


OCEAN_CONTAMINATION_KEYS = {
    "town_gate",
    "market",
    "herb_shop",
    "sect_yard",
    "back_mountain",
    "outer_sect",
    "spirit_herb",
    "monster_abnormal",
}


class WorldSpecGenerator:
    """LLM WorldSpec generator with normalize -> repair -> validate hardening.

    This class intentionally does not call the legacy WorldSpecGenerator._generate_with_llm,
    because the legacy path validates with Pydantic before alias normalization can run.
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client
        self.normalizer = WorldSpecNormalizer()
        self.last_source = "sample_fallback"
        self.last_candidate_payload: dict[str, Any] | None = None
        self.last_normalized_candidate: dict[str, Any] | None = None
        self.last_raw_response: str | None = None
        self.last_validation_report: dict[str, Any] | None = None
        self.last_repair_attempts: list[dict[str, Any]] = []
        self.last_error: str | None = None
        self.last_warnings: list[str] = []
        self.requested_genre: str | None = None

    def generate(self, idea: str) -> WorldSpec:
        intent = WorldIntentExtractor().extract(idea)
        self.requested_genre = intent["genre"]
        if self.llm_client is not None:
            spec = self._generate_with_llm(intent)
            if spec is not None:
                return spec
        self.last_source = "sample_fallback"
        spec = sample_world_spec(intent["genre"], idea)
        self._record_warnings(intent["genre"], spec.model_dump(mode="json"))
        return spec

    def _generate_with_llm(self, intent: dict[str, str]) -> WorldSpec | None:
        try:
            timeout_seconds = getattr(getattr(self.llm_client, "config", None), "worldgen_timeout_seconds", None)
            timeout_kwargs = {"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}
            payload = self.llm_client.complete_json(_worldspec_messages(intent), temperature=0.2, **timeout_kwargs)
            self.last_raw_response = getattr(self.llm_client, "last_raw_text", None)
            self.last_candidate_payload = payload
            normalized = self.normalizer.normalize(payload)
            self.last_normalized_candidate = normalized
            report = _safe_validate(normalized)
            self.last_repair_attempts = [report]
            self.last_validation_report = report
            source = "llm_candidate"
            if not report["valid"]:
                normalized = WorldSpecRepairer().repair(normalized, report)
                self.last_normalized_candidate = normalized
                report = _safe_validate(normalized)
                self.last_repair_attempts.append(report)
                source = "repaired_llm_candidate"
                self.last_validation_report = report
            if not report["valid"]:
                self.last_error = "ValidationError: " + json.dumps(report, ensure_ascii=False)
                return None
            spec = WorldSpec.model_validate(normalized)
            self.last_source = source
            self._record_warnings(intent["genre"], spec.model_dump(mode="json"))
            return spec
        except Exception as exc:
            self.last_raw_response = getattr(self.llm_client, "last_raw_text", None)
            if self.last_candidate_payload is not None:
                self.last_error = f"ValidationError: {type(exc).__name__}: {exc}"
            else:
                self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def _record_warnings(self, requested_genre: str, spec_payload: dict[str, Any]) -> None:
        self.last_warnings = []
        if requested_genre == "ocean" and _contains_keys(spec_payload, OCEAN_CONTAMINATION_KEYS):
            self.last_warnings.append("genre_contamination_detected")


def normalize_worldspec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return WorldSpecNormalizer().normalize(payload)


def _safe_validate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return WorldSpecValidator().validate(payload)
    except Exception as exc:
        return {
            "valid": False,
            "issues": [
                {
                    "code": "schema_validation_exception",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }


def _worldspec_messages(intent: dict[str, str]) -> list[dict[str, str]]:
    return build_full_worldspec_prompt(intent)


def _contains_keys(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(k in keys or _contains_keys(v, keys) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_keys(item, keys) for item in value)
    return isinstance(value, str) and value in keys
