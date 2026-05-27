from __future__ import annotations

import json
from typing import Any

from .worldspec import SUPPORTED_EFFECTS, SUPPORTED_PREDICATES, WorldIntentExtractor, WorldSpec, WorldSpecValidator
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
            payload = self.llm_client.complete_json(_worldspec_messages(intent), temperature=0.2)
            self.last_raw_response = getattr(self.llm_client, "last_raw_text", None)
            self.last_candidate_payload = payload
            normalized = self.normalizer.normalize(payload)
            self.last_normalized_candidate = normalized
            report = _safe_validate(normalized)
            source = "llm_candidate"
            if not report["valid"]:
                normalized = WorldSpecRepairer().repair(normalized, report)
                self.last_normalized_candidate = normalized
                report = _safe_validate(normalized)
                source = "repaired_llm_candidate"
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
    schema_notes = {
        "required": [
            "world_id",
            "title",
            "genre",
            "theme",
            "starting_area",
            "scale",
            "player_start",
            "locations",
            "characters",
            "items",
            "factions",
            "resources",
            "rules",
            "action_templates",
            "initial_states",
            "initial_memories",
            "initial_tensions",
            "initial_quests",
            "background_lore",
        ],
        "must_use": {
            "player_start": ["character_id", "location_id"],
            "location": ["id", "stable_key", "name", "description", "connects_to"],
            "character": ["id", "stable_key", "name", "role", "start_location", "goals"],
            "item": ["id", "stable_key", "name", "item_type", "owner_id or location_id"],
            "tension": ["id", "tension_type", "affected_entities", "evidence"],
            "quest": ["id", "title", "issuer_id", "tension_id", "objectives", "evidence"],
        },
        "supported_predicates": sorted(SUPPORTED_PREDICATES),
        "supported_effects": sorted(SUPPORTED_EFFECTS),
    }
    return [
        {
            "role": "system",
            "content": (
                "Generate one STRICTLY VALID JSON object only. No markdown, no comments, no trailing commas. "
                "Every object property must be comma-separated. Use double quotes for every string. "
                "The output must parse with JSON.parse. WorldSpec is a candidate only; do not mutate canonical state. "
                "Do not use canonical memory for NPC beliefs; use npc/faction/rumor/player scopes."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "intent": intent,
                    "schema_notes": schema_notes,
                    "scale_constraints": {
                        "locations": "6-10",
                        "characters": "5-8",
                        "items": "8-15",
                        "factions": "2-4",
                        "action_templates": "8-15",
                        "initial_tensions": "3-5",
                        "initial_quests": "2-4",
                    },
                    "minimal_shape_example": {
                        "player_start": {"character_id": "player", "location_id": "start_location_id"},
                        "locations": [
                            {
                                "id": "start_location_id",
                                "stable_key": "start_location_id",
                                "name": "Start",
                                "description": "...",
                                "connects_to": [],
                            }
                        ],
                        "characters": [
                            {
                                "id": "npc_id",
                                "stable_key": "npc_id",
                                "name": "NPC",
                                "role": "guide",
                                "start_location": "start_location_id",
                                "goals": [],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]


def _contains_keys(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(k in keys or _contains_keys(v, keys) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_keys(item, keys) for item in value)
    return isinstance(value, str) and value in keys
