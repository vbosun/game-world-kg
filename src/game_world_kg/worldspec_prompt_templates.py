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

SCALE_INVALID_EXAMPLE: dict[str, str] = {"scale": "small"}

CHARACTER_GOAL_VALID_EXAMPLE: dict[str, Any] = {
    "goal_id": "gain_freedom",
    "priority": 0.9,
    "desired_state": None,
    "risk_tolerance": 0.4,
}
CHARACTER_GOAL_INVALID_EXAMPLE: dict[str, list[str]] = {"goals": ["逃离这里"]}

TENSION_VALID_EXAMPLE: dict[str, Any] = {
    "id": "debt_control",
    "tension_type": "resource_pressure",
    "description": "玩家受到债务和看管限制，必须寻找脱身机会。",
    "affected_entities": ["player", "house_manager", "ledger"],
    "evidence": [{"type": "state", "entity": "player", "attr": "debt_status", "value": "bound"}],
    "suggested_actions": ["ask_about_topic", "inspect_object"],
    "priority": 0.8,
}
TENSION_INVALID_EXAMPLE: dict[str, Any] = {
    "id": "debt_control",
    "tension_type": "resource_pressure",
    "affected_entities": ["player"],
    "evidence": [],
}

FACTION_VALID_EXAMPLE: dict[str, Any] = {
    "id": "house_staff",
    "stable_key": "house_staff",
    "name": "馆中管事",
    "faction_type": "organization",
    "goals": ["maintain_control", "protect_income"],
    "relations": [
        {"target": "rival_guild", "relation": "opposes", "value": -0.6},
        {"target": "merchant_alliance", "relation": "allies", "value": 0.7},
    ],
}
FACTION_INVALID_EXAMPLE: dict[str, Any] = {"id": "house_staff", "name": "馆中管事", "members": ["npc_a", "npc_b"]}

RESOURCE_VALID_EXAMPLE: dict[str, Any] = {"entity": "player", "attr": "silver", "value": 2}
RESOURCE_INVALID_EXAMPLE = "player has 2 silver"

INITIAL_STATE_VALID_EXAMPLE: dict[str, Any] = {"entity": "player", "attr": "location", "value": "start_room"}
INITIAL_STATE_INVALID_EXAMPLE = "player is in start room"

BACKGROUND_LORE_VALID_EXAMPLE = [
    "这座小世界围绕债务、看管、情报和脱身路线展开。",
    "不同势力都在争夺账本、名声和出入许可。",
]
BACKGROUND_LORE_INVALID_EXAMPLE = "这是一段单个字符串背景设定。"


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
                'The scale must be exactly "small_dense". '
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
                        'scale must be exactly "small_dense".',
                        "background_lore must be list[str], not a single string.",
                        "action_templates require action_id and label_template; id/title are aliases only.",
                        "effects and preconditions must be objects with supported type values.",
                        "quest objectives must be objects with type and target.",
                        "rules must be structured objects; never free-text executable rules.",
                        "subjective NPC belief, suspicion, rumor, or uncertainty must use npc/faction/rumor/player scope.",
                        "All references must point to generated entities; do not invent dangling ids.",
                    ],
                    "final_self_check": [
                        'scale is exactly "small_dense".',
                        "all count constraints are satisfied.",
                        "every character goal has goal_id and priority.",
                        "every tension has description.",
                        "background_lore is an array of strings.",
                        "every faction has faction_type, goals, and relations.",
                        "every resource has entity, attr, value.",
                        "every initial_state has entity, attr, value.",
                        "every action_template has action_id and label_template.",
                        "every precondition and effect is an object.",
                        "no effect is a string.",
                        "no quest objective is a string.",
                        "no executable rule is free text.",
                        "no NPC belief uses canonical scope.",
                        "every referenced id exists.",
                        "Only output the final JSON object.",
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
            "scale": ['exact literal "small_dense"'],
            "location": ["id", "stable_key", "name", "description", "connects_to"],
            "character": ["id", "stable_key", "name", "role", "start_location", "goals"],
            "character_goal": ["goal_id", "priority", "desired_state", "risk_tolerance"],
            "item": ["id", "stable_key", "name", "item_type", "owner_id or location_id"],
            "faction": ["id", "stable_key", "name", "faction_type", "goals", "relations"],
            "faction_relation": ["target", "relation", "value"],
            "resource": ["entity", "attr", "value"],
            "initial_state": ["entity", "attr", "value"],
            "tension": ["id", "tension_type", "description", "affected_entities", "evidence", "suggested_actions", "priority"],
            "quest": ["id", "title", "issuer_id", "tension_id", "objectives", "evidence"],
            "background_lore": ["list[str]"],
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
            "character_goal": CHARACTER_GOAL_VALID_EXAMPLE,
            "tension": TENSION_VALID_EXAMPLE,
            "faction": FACTION_VALID_EXAMPLE,
            "resource": RESOURCE_VALID_EXAMPLE,
            "initial_state": INITIAL_STATE_VALID_EXAMPLE,
            "background_lore": BACKGROUND_LORE_VALID_EXAMPLE,
        },
        "invalid": {
            "scale": {
                "example": SCALE_INVALID_EXAMPLE,
                "reject_because": 'scale must be exactly "small_dense"',
            },
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
            "character_goal": {
                "example": CHARACTER_GOAL_INVALID_EXAMPLE,
                "reject_because": "goals must be object[] and each item must include goal_id and priority",
            },
            "tension": {
                "example": TENSION_INVALID_EXAMPLE,
                "reject_because": "tension must include description and executable evidence",
            },
            "faction": {
                "example": FACTION_INVALID_EXAMPLE,
                "reject_because": "faction must include faction_type, goals, and relations",
            },
            "resource": {
                "example": RESOURCE_INVALID_EXAMPLE,
                "reject_because": "resource must be a structured object with entity, attr, value",
            },
            "initial_state": {
                "example": INITIAL_STATE_INVALID_EXAMPLE,
                "reject_because": "initial_state must be a structured object with entity, attr, value",
            },
            "background_lore": {
                "example": BACKGROUND_LORE_INVALID_EXAMPLE,
                "reject_because": "background_lore must be list[str], not a single string",
            },
        },
    }
