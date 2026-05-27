from __future__ import annotations

import json
from typing import Any

from .worldspec import SUPPORTED_EFFECTS, SUPPORTED_PREDICATES


ACTION_TEMPLATE_VALID_EXAMPLE: dict[str, Any] = {
    "action_id": "ask_about_topic",
    "label_template": "向{target}询问{topic}",
    "target_selector": {"entity_type": "Character", "same_location": True},
    "arg_schema": {"topic": "string"},
    "preconditions": [{"type": "same_location", "a": "player", "b": "$target"}],
    "effects": [{"type": "add_conversation_event", "actor": "player", "target": "$target", "topic": "$topic"}],
    "risk": "low",
}

ACTION_TEMPLATE_INVALID_EXAMPLE: dict[str, Any] = {
    "id": "serve_guest",
    "title": "接待客人",
    "description": "完成一次服务。",
    "effects": ["delta_resource: gold,+10"],
}

EFFECT_VALID_EXAMPLE: dict[str, Any] = {"type": "set_state", "entity": "player", "attr": "ready", "value": True}
EFFECT_INVALID_EXAMPLE = "set_state: player, state=ready"

QUEST_OBJECTIVE_VALID_EXAMPLE: dict[str, Any] = {"type": "collect_evidence", "target": "ledger_clue"}
QUEST_OBJECTIVE_INVALID_EXAMPLE = "完成一次接待并获得声望"

MEMORY_SCOPE_VALID_EXAMPLE: dict[str, Any] = {
    "owner_id": "npc_mara",
    "memory_text": "玩家曾帮我修补过木筏。",
    "truth_scope": "npc",
    "scope_key": "npc_mara",
    "salience": 0.7,
    "confidence": 0.8,
}

MEMORY_SCOPE_INVALID_EXAMPLE: dict[str, Any] = {
    "owner_id": "npc_mara",
    "memory_text": "玩家一定偷了钥匙。",
    "truth_scope": "canonical",
    "scope_key": "world",
}


def build_full_worldspec_prompt(
    intent: dict[str, str],
    schema_notes: dict[str, Any] | None = None,
    examples: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    notes = schema_notes or _default_schema_notes()
    prompt_examples = examples or _default_examples()
    return [
        {
            "role": "system",
            "content": (
                "You are compiling an executable WorldSpec DSL, not writing game setting prose. "
                "Output one strictly valid JSON object only: no markdown, comments, or trailing commas. "
                "Every action must be executable by RuleEngine. All effects must be structured objects. "
                "Do not output natural-language rules as executable rules. Do not output string effects. "
                "Do not output string quest objectives. NPC beliefs must not use canonical memory scope. "
                "If a mechanic cannot be expressed with supported predicates/effects, omit it. "
                "WorldSpec is a candidate only; never bootstrap or mutate canonical state."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "intent": intent,
                    "schema_notes": notes,
                    "scale_constraints": {
                        "locations": "6-10",
                        "characters": "5-8",
                        "items": "8-15",
                        "factions": "2-4",
                        "action_templates": "8-15",
                        "initial_tensions": "3-5",
                        "initial_quests": "2-4",
                    },
                    "positive_examples": prompt_examples["valid"],
                    "negative_examples": prompt_examples["invalid"],
                    "rejection_rules": [
                        "action_templates require action_id and label_template; id/title are aliases only.",
                        "effects and preconditions must be objects with supported type values.",
                        "quest objectives must be objects with type and target.",
                        "rules must be structured objects; never free-text executable rules.",
                        "subjective NPC belief, suspicion, rumor, or uncertainty must use npc/faction/rumor/player scope.",
                        "All references must point to generated entities; do not invent dangling ids.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _default_schema_notes() -> dict[str, Any]:
    return {
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


def _default_examples() -> dict[str, Any]:
    return {
        "valid": {
            "action_template": ACTION_TEMPLATE_VALID_EXAMPLE,
            "effect": EFFECT_VALID_EXAMPLE,
            "quest_objective": QUEST_OBJECTIVE_VALID_EXAMPLE,
            "memory_scope": MEMORY_SCOPE_VALID_EXAMPLE,
        },
        "invalid": {
            "action_template": {
                "example": ACTION_TEMPLATE_INVALID_EXAMPLE,
                "reject_because": "missing action_id/label_template; effects are strings and cannot execute",
            },
            "effect": {
                "example": EFFECT_INVALID_EXAMPLE,
                "reject_because": "effect must be an object with a supported type",
            },
            "quest_objective": {
                "example": QUEST_OBJECTIVE_INVALID_EXAMPLE,
                "reject_because": "objective must be a structured object, not prose",
            },
            "memory_scope": {
                "example": MEMORY_SCOPE_INVALID_EXAMPLE,
                "reject_because": "NPC belief or suspicion must not contaminate canonical memory",
            },
        },
    }
