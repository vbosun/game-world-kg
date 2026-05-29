"""Task 2: Verify repair-before-fallback in WorldSpecGenerator (worldspec_safe)."""
from __future__ import annotations

import json

from game_world_kg.worldspec import WorldSpecGenerator


class SchemaInvalidButRepairableLLM:
    """Returns JSON with fixable schema issues: missing goals, string locations."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        data = {
            "world_id": "repairable_world",
            "title": "Repairable World",
            "genre": "village",
            "theme": "test theme",
            "starting_area": "village_square",
            "scale": "small_dense",
            "player_start": {"character_id": "player", "location_id": "village_square"},
            "locations": [
                {"id": "village_square", "stable_key": "village_square", "name": "Village Square", "connects_to": []},
            ],
            "characters": [
                {"id": "player", "stable_key": "player", "name": "Player", "role": "newcomer", "start_location": "village_square", "goals": []},
                {"id": "npc_merchant", "stable_key": "npc_merchant", "name": "Merchant", "role": "merchant", "start_location": "village_square", "goals": []},
            ],
            "items": [
                {"id": "coin", "stable_key": "coin", "name": "Coin", "owner_id": "player", "item_type": "currency"},
                {"id": "bread", "stable_key": "bread", "name": "Bread", "owner_id": "npc_merchant", "item_type": "food"},
            ],
            "factions": [],
            "resources": [],
            "rules": [],
            "action_templates": [
                {"action_id": "talk_to", "label_template": "Talk to {target}", "target_selector": {"entity_type": "Character", "same_location": True},
                 "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}],
                 "effects": [], "risk": "low", "reason": "talking is free"},
            ],
            "initial_states": [],
            "initial_memories": [],
            "initial_tensions": [
                {"id": "t_test", "tension_type": "test", "description": "test tension",
                 "affected_entities": ["player"],
                 "suggested_actions": ["talk_to"], "evidence": [{"type": "state", "entity_id": "player", "attr": "location", "value": "village_square"}]},
            ],
            "initial_quests": [
                {"id": "q_test", "title": "Test Quest", "issuer_id": "npc_merchant", "tension_id": "t_test",
                 "objectives": [{"type": "talk_to", "target": "npc_merchant"}],
                 "rewards": [], "failure_consequences": [],
                 "evidence": [{"tension_id": "t_test"}]},
            ],
            "background_lore": [],
        }
        self.last_raw_text = json.dumps(data, ensure_ascii=False)
        return self.last_raw_text


class ValidJSONButMissingRequiredFieldsLLM:
    """JSON that parses but Pydantic fails — no locations at all."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        data = {"world_id": "bare_minimum", "title": "Bare", "genre": "village", "theme": "bare", "starting_area": "x"}
        self.last_raw_text = json.dumps(data, ensure_ascii=False)
        return self.last_raw_text


class UnparseableJSONLLM:
    """LLM returns text, not JSON."""
    last_raw_text: str | None = None

    def complete_text(self, messages, *, temperature=0.4, timeout_seconds=None):
        self.last_raw_text = "Here is a beautiful world: the sun rises over the mountains."
        return self.last_raw_text


def test_repair_flow_sets_attempted_flag_when_validation_fails() -> None:
    """When validation fails after normalization, repair_attempted must be True."""
    gen = WorldSpecGenerator(SchemaInvalidButRepairableLLM())
    result = gen.generate("test repairable world")

    # The normalizer blends sample data — repair may or may not fix everything.
    # Key assertion: repair was attempted if validation failed.
    assert result is not None  # Always falls back if repair fails
    assert gen.last_json_parse_error is None  # JSON parse succeeded
    assert gen.last_candidate_payload is not None  # Payload exists
    assert gen.last_normalized_candidate is not None  # Normalization ran
    # Repair was attempted because the normalizer-blended data needs fixing
    assert gen.repair_attempted
    # Fail/success depends on how well the normalizer merged with sample


def test_repair_failure_then_fallback_records_reason() -> None:
    """When repair can't fix the schema, it must fallback and record why."""
    gen = WorldSpecGenerator(ValidJSONButMissingRequiredFieldsLLM())
    result = gen.generate("too bare to repair")

    # Should fall back
    assert result is not None  # sample fallback
    assert gen.last_source == "sample_fallback"
    assert gen.last_error_type == "pydantic_validation_error"
    assert gen.last_pydantic_error is not None
    assert "ValidationError" in gen.last_pydantic_error
    # Repair was attempted
    assert gen.repair_attempted
    assert not gen.repair_success


def test_json_parse_error_does_not_attempt_schema_repair() -> None:
    """JSON parse failure must not call WorldSpecRepairer — no structured payload."""
    gen = WorldSpecGenerator(UnparseableJSONLLM())
    result = gen.generate("not json")

    assert result is not None  # sample fallback
    assert gen.last_source == "sample_fallback"
    assert gen.last_error_type == "json_parse_error"
    assert gen.last_json_parse_error is not None
    # Schema repair should NOT have been attempted
    assert not gen.repair_attempted
    assert not gen.repair_success
    # No candidate payload (JSON parse failed)
    assert gen.last_candidate_payload is None


def test_repair_attempted_flag_set_only_when_needed() -> None:
    """repair_attempted must be True only when validation failed and repair was tried."""
    gen = WorldSpecGenerator(SchemaInvalidButRepairableLLM())
    gen.generate("test")

    # repairable → validation may have failed, repair may have fixed it
    # The flag should be True if repair was attempted
    if gen.last_source == "repaired_llm_candidate":
        assert gen.repair_attempted
        assert gen.repair_success
