from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


Scale = Literal["small_dense"]

SUPPORTED_PREDICATES = {
    "same_location",
    "has_item",
    "state_equals",
    "state_not_equals",
    "relation_at_least",
    "resource_at_least",
    "connected_location",
    "scope_allowed",
}
SUPPORTED_EFFECTS = {
    "transfer_item",
    "move_entity",
    "change_relation",
    "set_state",
    "delta_resource",
    "add_memory",
    "add_conversation_event",
}


class PlayerStartSpec(BaseModel):
    character_id: str = "player"
    location_id: str


class LocationSpec(BaseModel):
    id: str
    stable_key: str
    name: str
    description: str = ""
    location_type: str = "place"
    connects_to: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CharacterGoalSpec(BaseModel):
    goal_id: str
    priority: float = Field(ge=0, le=1)
    desired_state: dict[str, Any] | None = None
    risk_tolerance: float = Field(default=0.3, ge=0, le=1)


class CharacterSpec(BaseModel):
    id: str
    stable_key: str
    name: str
    role: str
    start_location: str
    faction_id: str | None = None
    goals: list[CharacterGoalSpec] = Field(default_factory=list)
    personality: dict[str, float] = Field(default_factory=dict)
    initial_beliefs: list[str] = Field(default_factory=list)


class ItemSpec(BaseModel):
    id: str
    stable_key: str
    name: str
    item_type: str = "item"
    owner_id: str | None = None
    location_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class FactionRelationSpec(BaseModel):
    target: str
    relation: str
    value: float = 0


class FactionSpec(BaseModel):
    id: str
    stable_key: str
    name: str
    faction_type: str = "faction"
    goals: list[str] = Field(default_factory=list)
    relations: list[FactionRelationSpec] = Field(default_factory=list)


class ActionTemplateSpec(BaseModel):
    action_id: str
    label_template: str
    target_selector: dict[str, Any] = Field(default_factory=dict)
    arg_schema: dict[str, str] = Field(default_factory=dict)
    preconditions: list[dict[str, Any]] = Field(default_factory=list)
    effects: list[dict[str, Any]] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    reason: str = ""


class InitialStateSpec(BaseModel):
    entity: str
    attr: str
    value: Any
    scope: str = "canonical"


class InitialMemorySpec(BaseModel):
    owner_id: str
    memory_text: str
    truth_scope: Literal["canonical", "player", "npc", "faction", "rumor", "candidate", "rejected"] = "npc"
    scope_key: str | None = None
    salience: float = Field(default=0.5, ge=0, le=1)
    valence: float = Field(default=0, ge=-1, le=1)
    confidence: float = Field(default=1, ge=0, le=1)


class EvidenceSpec(BaseModel):
    type: str
    entity: str | None = None
    attr: str | None = None
    value: Any = None
    memory_id: str | None = None
    text: str | None = None


class TensionSpec(BaseModel):
    id: str
    tension_type: str
    description: str
    affected_entities: list[str]
    evidence: list[EvidenceSpec]
    suggested_actions: list[str] = Field(default_factory=list)
    priority: float = Field(default=0.5, ge=0, le=1)


class QuestObjectiveSpec(BaseModel):
    type: str
    target: str


class QuestRewardSpec(BaseModel):
    type: str
    entity: str | None = None
    attr: str | None = None
    delta: int | float | None = None
    target: str | None = None


class QuestSpec(BaseModel):
    id: str
    title: str
    issuer_id: str
    tension_id: str
    objectives: list[QuestObjectiveSpec]
    rewards: list[QuestRewardSpec] = Field(default_factory=list)
    failure_consequences: list[QuestRewardSpec] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class WorldSpec(BaseModel):
    world_id: str
    title: str
    genre: str
    theme: str
    starting_area: str
    scale: Scale = "small_dense"
    player_start: PlayerStartSpec
    ontology_extensions: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[LocationSpec]
    characters: list[CharacterSpec]
    items: list[ItemSpec]
    factions: list[FactionSpec]
    resources: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    action_templates: list[ActionTemplateSpec]
    initial_states: list[InitialStateSpec] = Field(default_factory=list)
    initial_memories: list[InitialMemorySpec] = Field(default_factory=list)
    initial_tensions: list[TensionSpec]
    initial_quests: list[QuestSpec]
    background_lore: list[str] = Field(default_factory=list)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def spec_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


class WorldSpecValidator:
    def validate(self, candidate: WorldSpec | dict[str, Any]) -> dict[str, Any]:
        issues: list[ValidationIssue] = []
        try:
            spec = candidate if isinstance(candidate, WorldSpec) else WorldSpec.model_validate(candidate)
        except ValidationError as exc:
            return {"valid": False, "issues": [{"code": "schema", "path": ".".join(str(part) for part in err["loc"]), "message": err["msg"]} for err in exc.errors()]}

        entities = {"player"}
        location_ids = {item.id for item in spec.locations}
        character_ids = {item.id for item in spec.characters}
        item_ids = {item.id for item in spec.items}
        faction_ids = {item.id for item in spec.factions}
        tension_ids = {item.id for item in spec.initial_tensions}
        action_ids = {item.action_id for item in spec.action_templates}
        entities.update(location_ids | character_ids | item_ids | faction_ids | tension_ids)

        _check_unique(issues, "locations", [item.id for item in spec.locations], "id")
        _check_unique(issues, "characters", [item.id for item in spec.characters], "id")
        _check_unique(issues, "items", [item.id for item in spec.items], "id")
        _check_unique(issues, "factions", [item.id for item in spec.factions], "id")
        _check_unique(issues, "stable_key", [item.stable_key for item in [*spec.locations, *spec.characters, *spec.items, *spec.factions]], "stable_key")
        _check_unique(issues, "actions", [item.action_id for item in spec.action_templates], "action_id")

        if spec.player_start.location_id not in location_ids:
            issues.append(ValidationIssue("dangling_ref", "player_start.location_id", "player_start location must exist"))
        if spec.starting_area not in location_ids:
            issues.append(ValidationIssue("dangling_ref", "starting_area", "starting_area must reference a location"))
        _check_range(issues, "locations", len(spec.locations), 6, 10)
        _check_range(issues, "characters", len(spec.characters), 5, 8)
        _check_range(issues, "items", len(spec.items), 8, 15)
        _check_range(issues, "factions", len(spec.factions), 2, 4)
        _check_range(issues, "action_templates", len(spec.action_templates), 8, 15)
        _check_range(issues, "initial_tensions", len(spec.initial_tensions), 3, 5)
        _check_range(issues, "initial_quests", len(spec.initial_quests), 2, 4)

        for location in spec.locations:
            for target in location.connects_to:
                if target not in location_ids:
                    issues.append(ValidationIssue("dangling_ref", f"locations.{location.id}.connects_to", f"unknown location: {target}"))
        if location_ids and spec.player_start.location_id in location_ids:
            reachable = _reachable_locations(spec.player_start.location_id, spec.locations)
            for location_id in sorted(location_ids - reachable):
                issues.append(ValidationIssue("map_disconnected", "locations", f"location is not reachable: {location_id}"))

        for character in spec.characters:
            if character.start_location not in location_ids:
                issues.append(ValidationIssue("dangling_ref", f"characters.{character.id}.start_location", "character start_location must exist"))
            if character.faction_id and character.faction_id not in faction_ids:
                issues.append(ValidationIssue("dangling_ref", f"characters.{character.id}.faction_id", "character faction must exist"))
            if not character.goals:
                issues.append(ValidationIssue("missing_goal", f"characters.{character.id}.goals", "NPC must have at least one planner goal"))
        for item in spec.items:
            if not item.owner_id and not item.location_id:
                issues.append(ValidationIssue("missing_owner", f"items.{item.id}", "item must have owner_id or location_id"))
            if item.owner_id and item.owner_id not in entities:
                issues.append(ValidationIssue("dangling_ref", f"items.{item.id}.owner_id", "item owner must exist"))
            if item.location_id and item.location_id not in location_ids:
                issues.append(ValidationIssue("dangling_ref", f"items.{item.id}.location_id", "item location must exist"))
        for faction in spec.factions:
            for relation in faction.relations:
                if relation.target not in faction_ids:
                    issues.append(ValidationIssue("dangling_ref", f"factions.{faction.id}.relations", "faction relation target must exist"))

        for template in spec.action_templates:
            variables = {"actor", "target"} | set(template.arg_schema)
            for index, predicate in enumerate(template.preconditions):
                if predicate.get("type") not in SUPPORTED_PREDICATES:
                    issues.append(ValidationIssue("unsupported_predicate", f"action_templates.{template.action_id}.preconditions.{index}", str(predicate.get("type"))))
                _check_variables(issues, f"action_templates.{template.action_id}.preconditions.{index}", predicate, variables)
            for index, effect in enumerate(template.effects):
                if effect.get("type") not in SUPPORTED_EFFECTS:
                    issues.append(ValidationIssue("unsupported_effect", f"action_templates.{template.action_id}.effects.{index}", str(effect.get("type"))))
                _check_variables(issues, f"action_templates.{template.action_id}.effects.{index}", effect, variables)

        for state in spec.initial_states:
            if state.entity not in entities:
                issues.append(ValidationIssue("dangling_ref", f"initial_states.{state.entity}.{state.attr}", "state entity must exist"))
        for memory in spec.initial_memories:
            if memory.owner_id not in entities:
                issues.append(ValidationIssue("dangling_ref", f"initial_memories.{memory.owner_id}", "memory owner must exist"))
            if memory.truth_scope == "canonical":
                issues.append(ValidationIssue("scope_violation", f"initial_memories.{memory.owner_id}", "initial NPC beliefs must not enter canonical memory"))
        for tension in spec.initial_tensions:
            if not tension.evidence:
                issues.append(ValidationIssue("missing_evidence", f"initial_tensions.{tension.id}", "tension must have evidence"))
            for entity_id in tension.affected_entities:
                if entity_id not in entities:
                    issues.append(ValidationIssue("dangling_ref", f"initial_tensions.{tension.id}.affected_entities", f"unknown entity: {entity_id}"))
            for action_id in tension.suggested_actions:
                if action_id not in action_ids:
                    issues.append(ValidationIssue("dangling_ref", f"initial_tensions.{tension.id}.suggested_actions", f"unknown action: {action_id}"))
        for quest in spec.initial_quests:
            if quest.issuer_id not in character_ids:
                issues.append(ValidationIssue("dangling_ref", f"initial_quests.{quest.id}.issuer_id", "quest issuer must be a character"))
            if quest.tension_id not in tension_ids:
                issues.append(ValidationIssue("dangling_ref", f"initial_quests.{quest.id}.tension_id", "quest tension must exist"))
            if not quest.objectives:
                issues.append(ValidationIssue("missing_objective", f"initial_quests.{quest.id}.objectives", "quest must have objectives"))
            if not quest.evidence:
                issues.append(ValidationIssue("missing_evidence", f"initial_quests.{quest.id}.evidence", "quest must trace to evidence"))
            for objective in quest.objectives:
                if objective.target not in entities:
                    issues.append(ValidationIssue("dangling_ref", f"initial_quests.{quest.id}.objectives", f"unknown objective target: {objective.target}"))
            for effect in [*quest.rewards, *quest.failure_consequences]:
                target = effect.entity or effect.target
                if target and target not in entities:
                    issues.append(ValidationIssue("dangling_ref", f"initial_quests.{quest.id}.effects", f"unknown effect target: {target}"))

        return {
            "valid": not issues,
            "issues": [issue.as_dict() for issue in issues],
            "world_id": spec.world_id,
            "spec_hash": spec.spec_hash(),
        }


class WorldIntentExtractor:
    def extract(self, idea: str) -> dict[str, str]:
        genre = "cultivation" if any(word in idea for word in ["修仙", "外门", "宗门", "妖兽"]) else "village"
        if any(word in idea for word in ["海", "海洋", "岛", "船"]):
            genre = "ocean"
        title = "青木镇外门风波" if genre == "cultivation" else ("潮汐群岛失衡" if genre == "ocean" else "边村铁门风波")
        return {"idea": idea, "genre": genre, "title": title}


class WorldSpecGenerator:
    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client

    def generate(self, idea: str) -> WorldSpec:
        intent = WorldIntentExtractor().extract(idea)
        if self.llm_client is not None:
            spec = self._generate_with_llm(intent)
            if spec is not None:
                return spec
        return sample_world_spec(intent["genre"], idea)

    def _generate_with_llm(self, intent: dict[str, str]) -> WorldSpec | None:
        try:
            payload = self.llm_client.complete_json(
                [
                    {"role": "system", "content": "Generate a strict JSON WorldSpec for a small_dense game world. Use only supported predicate/effect types."},
                    {"role": "user", "content": json.dumps(intent, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            return WorldSpec.model_validate(payload)
        except Exception:
            return None


class WorldSpecRepairer:
    def repair(self, candidate: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        fixed = json.loads(json.dumps(candidate, ensure_ascii=False))
        locations = {item["id"] for item in fixed.get("locations", [])}
        if fixed.get("player_start", {}).get("location_id") not in locations and fixed.get("locations"):
            fixed.setdefault("player_start", {})["location_id"] = fixed["locations"][0]["id"]
        action_ids = {item["action_id"] for item in fixed.get("action_templates", [])}
        for tension in fixed.get("initial_tensions", []):
            tension["suggested_actions"] = [item for item in tension.get("suggested_actions", []) if item in action_ids]
            if not tension.get("evidence"):
                first = tension.get("affected_entities", ["player"])[0]
                tension["evidence"] = [{"type": "state", "entity": first, "attr": "status", "value": "unresolved"}]
        return fixed


def sample_world_spec(genre: str = "cultivation", idea: str = "") -> WorldSpec:
    if genre == "ocean":
        return _ocean_spec(idea)
    if genre == "village":
        return _village_spec(idea)
    return _cultivation_spec(idea)


def _base_actions() -> list[dict[str, Any]]:
    return [
        {
            "action_id": "move_to_location",
            "label_template": "前往{target}",
            "target_selector": {"entity_type": "Location", "connected_to_actor": True},
            "preconditions": [{"type": "connected_location", "actor": "$actor", "target": "$target"}],
            "effects": [{"type": "move_entity", "entity": "$actor", "to": "$target"}],
            "risk": "low",
            "reason": "目标地点与当前位置相连。",
        },
        {
            "action_id": "talk_to",
            "label_template": "和{target}交谈",
            "target_selector": {"entity_type": "Character", "same_location": True},
            "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}],
            "effects": [{"type": "add_memory", "owner": "$target", "memory_text": "玩家主动与我交谈。", "truth_scope": "npc", "salience": 0.4}],
            "risk": "low",
            "reason": "对方在当前位置。",
        },
        {
            "action_id": "ask_about_topic",
            "label_template": "向{target}询问线索",
            "target_selector": {"entity_type": "Character", "same_location": True},
            "arg_schema": {"topic": "string"},
            "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}],
            "effects": [{"type": "add_memory", "owner": "$actor", "memory_text": "我询问了当前局势的线索。", "truth_scope": "player", "salience": 0.5}],
            "risk": "low",
            "reason": "询问不会直接改变 canonical。",
        },
        {
            "action_id": "inspect",
            "label_template": "调查{target}",
            "target_selector": {"entity_type": "Location", "same_location": True},
            "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}],
            "effects": [{"type": "add_memory", "owner": "$actor", "memory_text": "我调查了当前位置。", "truth_scope": "player", "salience": 0.5}],
            "risk": "low",
            "reason": "调查只增加玩家记忆。",
        },
        {
            "action_id": "observe",
            "label_template": "观察周围",
            "target_selector": {},
            "preconditions": [{"type": "scope_allowed", "scope": "player"}],
            "effects": [{"type": "add_memory", "owner": "$actor", "memory_text": "我停下脚步观察了周围局势。", "truth_scope": "player", "salience": 0.4}],
            "risk": "low",
            "reason": "观察只增加行动者自己的记忆。",
        },
        {
            "action_id": "trade",
            "label_template": "和{target}交易",
            "target_selector": {"entity_type": "Character", "same_location": True},
            "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}, {"type": "resource_at_least", "entity": "$actor", "attr": "gold", "value": 1}],
            "effects": [{"type": "delta_resource", "entity": "$actor", "attr": "gold", "delta": -1}],
            "risk": "low",
            "reason": "交易消耗少量资源。",
        },
        {
            "action_id": "request_help",
            "label_template": "请求{target}帮助",
            "target_selector": {"entity_type": "Character", "same_location": True},
            "preconditions": [{"type": "same_location", "a": "$actor", "b": "$target"}],
            "effects": [{"type": "change_relation", "src": "$target", "rel": "TRUSTS", "dst": "$actor", "delta": 1}],
            "risk": "low",
            "reason": "请求帮助会影响关系。",
        },
        {
            "action_id": "spread_rumor",
            "label_template": "散布传闻",
            "target_selector": {"entity_type": "Character", "same_location": True},
            "preconditions": [{"type": "scope_allowed", "scope": "rumor"}],
            "effects": [{"type": "add_memory", "owner": "village", "memory_text": "出现了新的未证实传闻。", "truth_scope": "rumor", "confidence": 0.5}],
            "risk": "medium",
            "reason": "传闻只进入 rumor scope。",
        },
        {
            "action_id": "patrol",
            "label_template": "{target}巡逻",
            "target_selector": {"entity_type": "Location", "connected_to_actor": True},
            "preconditions": [{"type": "connected_location", "actor": "$actor", "target": "$target"}],
            "effects": [{"type": "move_entity", "entity": "$actor", "to": "$target"}],
            "risk": "low",
            "reason": "NPC 可在相邻地点巡逻。",
        },
        {
            "action_id": "report_to_faction",
            "label_template": "向势力报告",
            "target_selector": {"entity_type": "Faction"},
            "preconditions": [{"type": "scope_allowed", "scope": "faction"}],
            "effects": [{"type": "add_memory", "owner": "$target", "memory_text": "成员报告了当前局势。", "truth_scope": "faction"}],
            "risk": "low",
            "reason": "报告进入 faction scope。",
        },
    ]


def _cultivation_spec(idea: str) -> WorldSpec:
    data = {
        "world_id": _world_id("demo_cultivation_town", idea),
        "title": "青木镇外门风波",
        "genre": "cultivation",
        "theme": idea or "外门弟子成长与后山异常",
        "starting_area": "town_gate",
        "player_start": {"character_id": "player", "location_id": "town_gate"},
        "locations": [
            {"id": "town_gate", "stable_key": "town_gate", "name": "镇门", "description": "青木镇通往外门的门楼。", "location_type": "gate", "connects_to": ["market", "sect_yard"], "tags": ["start"]},
            {"id": "market", "stable_key": "market", "name": "市集", "description": "药材和杂货摊聚集。", "location_type": "market", "connects_to": ["town_gate", "herb_shop", "well_square"], "tags": ["trade"]},
            {"id": "herb_shop", "stable_key": "herb_shop", "name": "药铺", "description": "灵草短缺使药铺气氛紧张。", "location_type": "shop", "connects_to": ["market"], "tags": ["healing"]},
            {"id": "sect_yard", "stable_key": "sect_yard", "name": "外门院", "description": "新弟子报道和领取任务的院落。", "location_type": "sect", "connects_to": ["town_gate", "training_field"], "tags": ["quest_hub"]},
            {"id": "training_field", "stable_key": "training_field", "name": "练功场", "description": "外门弟子切磋的空地。", "location_type": "field", "connects_to": ["sect_yard", "forest_edge"], "tags": ["training"]},
            {"id": "forest_edge", "stable_key": "forest_edge", "name": "林缘", "description": "通向后山的小路开始变得荒凉。", "location_type": "wilds", "connects_to": ["training_field", "back_mountain"], "tags": ["danger"]},
            {"id": "back_mountain", "stable_key": "back_mountain", "name": "后山", "description": "妖兽异常出没，灵草越来越少。", "location_type": "wilds", "connects_to": ["forest_edge"], "tags": ["danger", "resource"]},
            {"id": "well_square", "stable_key": "well_square", "name": "井场", "description": "镇民交换消息的地方。", "location_type": "square", "connects_to": ["market"], "tags": ["rumor"]},
        ],
        "factions": [
            {"id": "outer_sect", "stable_key": "outer_sect", "name": "青木宗外门", "faction_type": "sect", "goals": ["maintain_order", "train_disciples"], "relations": [{"target": "townsfolk", "relation": "protects", "value": 0.6}]},
            {"id": "townsfolk", "stable_key": "townsfolk", "name": "青木镇民", "faction_type": "civilian", "goals": ["survive", "keep_trade_open"], "relations": [{"target": "outer_sect", "relation": "depends_on", "value": 0.4}]},
        ],
        "characters": [
            {"id": "sect_senior", "stable_key": "sect_senior", "name": "执事韩岳", "role": "sect_senior", "start_location": "sect_yard", "faction_id": "outer_sect", "goals": [{"goal_id": "stabilize_back_mountain", "priority": 0.9}], "personality": {"strict": 0.7}, "initial_beliefs": ["后山异常不能让镇民恐慌。"]},
            {"id": "herb_master", "stable_key": "herb_master", "name": "药铺老板许青", "role": "herb_shop_owner", "start_location": "herb_shop", "faction_id": "townsfolk", "goals": [{"goal_id": "restore_herb_supply", "priority": 0.9}], "personality": {"cautious": 0.7, "helpful": 0.6}, "initial_beliefs": ["后山灵草变少可能和妖兽异常有关。"]},
            {"id": "patrol_disciple", "stable_key": "patrol_disciple", "name": "巡山弟子林澈", "role": "patrol", "start_location": "forest_edge", "faction_id": "outer_sect", "goals": [{"goal_id": "watch_forest_edge", "priority": 0.7}], "personality": {"brave": 0.6}, "initial_beliefs": ["昨夜林缘有陌生爪印。"]},
            {"id": "market_auntie", "stable_key": "market_auntie", "name": "摊主阿禾", "role": "merchant", "start_location": "market", "faction_id": "townsfolk", "goals": [{"goal_id": "keep_market_supplied", "priority": 0.6}], "personality": {"talkative": 0.8}, "initial_beliefs": ["药铺涨价会让镇民不满。"]},
            {"id": "well_gossip", "stable_key": "well_gossip", "name": "井边老人", "role": "rumor_keeper", "start_location": "well_square", "faction_id": "townsfolk", "goals": [{"goal_id": "collect_news", "priority": 0.5}], "personality": {"curious": 0.9}, "initial_beliefs": ["有人听到后山夜里有低吼。"]},
            {"id": "young_disciple", "stable_key": "young_disciple", "name": "外门弟子苏小满", "role": "peer", "start_location": "training_field", "faction_id": "outer_sect", "goals": [{"goal_id": "prove_self", "priority": 0.6}], "personality": {"helpful": 0.5}, "initial_beliefs": ["新弟子应该先熟悉镇上局势。"]},
        ],
        "items": [
            {"id": "outer_token", "stable_key": "outer_token", "name": "外门令牌", "item_type": "permit", "owner_id": "player", "tags": ["identity"]},
            {"id": "spirit_herb", "stable_key": "spirit_herb", "name": "灵草", "item_type": "resource", "location_id": "back_mountain", "tags": ["quest"]},
            {"id": "monster_trace", "stable_key": "monster_trace", "name": "妖兽爪痕", "item_type": "evidence", "location_id": "forest_edge", "tags": ["evidence"]},
            {"id": "healing_pill", "stable_key": "healing_pill", "name": "回春丹", "item_type": "medicine", "owner_id": "herb_master", "tags": ["healing"]},
            {"id": "patrol_bell", "stable_key": "patrol_bell", "name": "巡山铃", "item_type": "tool", "owner_id": "patrol_disciple", "tags": ["warning"]},
            {"id": "market_grain", "stable_key": "market_grain", "name": "镇民口粮", "item_type": "resource", "location_id": "market", "tags": ["trade"]},
            {"id": "sect_notice", "stable_key": "sect_notice", "name": "宗门告示", "item_type": "notice", "location_id": "sect_yard", "tags": ["quest"]},
            {"id": "old_map", "stable_key": "old_map", "name": "旧山路图", "item_type": "map", "owner_id": "well_gossip", "tags": ["clue"]},
        ],
        "resources": [{"entity": "player", "attr": "gold", "value": 3}, {"entity": "player", "attr": "sect_contribution", "value": 0}],
        "action_templates": _base_actions(),
        "initial_states": [
            {"entity": "player", "attr": "location", "value": "town_gate"},
            {"entity": "player", "attr": "gold", "value": 3},
            {"entity": "player", "attr": "sect_contribution", "value": 0},
            {"entity": "herb_shop", "attr": "herb_stock", "value": "low"},
            {"entity": "back_mountain", "attr": "danger_level", "value": "high"},
            {"entity": "forest_edge", "attr": "monster_trace_visible", "value": True},
        ],
        "initial_memories": [],
        "initial_tensions": [
            {"id": "herb_shortage", "tension_type": "resource_shortage", "description": "药铺缺少灵草，镇民买药困难。", "affected_entities": ["herb_shop", "spirit_herb", "herb_master"], "evidence": [{"type": "state", "entity": "herb_shop", "attr": "herb_stock", "value": "low"}], "suggested_actions": ["ask_about_topic", "trade"], "priority": 0.8},
            {"id": "monster_abnormal", "tension_type": "hostility_rising", "description": "后山妖兽活动异常，巡山路线变危险。", "affected_entities": ["back_mountain", "monster_trace", "patrol_disciple"], "evidence": [{"type": "state", "entity": "back_mountain", "attr": "danger_level", "value": "high"}], "suggested_actions": ["inspect", "request_help"], "priority": 0.9},
            {"id": "rumor_spreading", "tension_type": "rumor_unresolved", "description": "镇民对后山异响议论纷纷。", "affected_entities": ["well_square", "well_gossip", "townsfolk"], "evidence": [{"type": "state", "entity": "forest_edge", "attr": "monster_trace_visible", "value": True}], "suggested_actions": ["ask_about_topic", "spread_rumor"], "priority": 0.5},
        ],
        "initial_quests": [
            {"id": "investigate_back_mountain", "title": "调查后山异常", "issuer_id": "sect_senior", "tension_id": "monster_abnormal", "objectives": [{"type": "visit_location", "target": "back_mountain"}, {"type": "collect_evidence", "target": "monster_trace"}], "rewards": [{"type": "delta_resource", "entity": "player", "attr": "sect_contribution", "delta": 5}], "failure_consequences": [{"type": "increase_tension", "target": "monster_abnormal", "delta": 1}], "evidence": [{"tension_id": "monster_abnormal"}]},
            {"id": "restore_herb_supply", "title": "恢复灵草供应", "issuer_id": "herb_master", "tension_id": "herb_shortage", "objectives": [{"type": "collect_item", "target": "spirit_herb"}], "rewards": [{"type": "delta_resource", "entity": "player", "attr": "gold", "delta": 2}], "failure_consequences": [{"type": "increase_tension", "target": "herb_shortage", "delta": 1}], "evidence": [{"tension_id": "herb_shortage"}]},
        ],
        "background_lore": ["青木镇依附青木宗外门而生。", "后山灵草是镇上药铺的主要来源。"],
    }
    data["initial_memories"] = _belief_memories(data["characters"])
    return WorldSpec.model_validate(data)


def _ocean_spec(idea: str) -> WorldSpec:
    spec = _cultivation_spec(idea)
    data = spec.model_dump(mode="json")
    data.update({"world_id": _world_id("demo_tide_islands", idea), "title": "潮汐群岛失衡", "genre": "ocean", "theme": idea or "海岛贸易与潮汐异常"})
    return WorldSpec.model_validate(data)


def _village_spec(idea: str) -> WorldSpec:
    spec = _cultivation_spec(idea)
    data = spec.model_dump(mode="json")
    data.update({"world_id": _world_id("demo_border_village", idea), "title": "边村铁门风波", "genre": "village", "theme": idea or "边境村庄的信任与粮食矛盾"})
    return WorldSpec.model_validate(data)


def _belief_memories(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memories: list[dict[str, Any]] = []
    for character in characters:
        for belief in character.get("initial_beliefs", []):
            memories.append({"owner_id": character["id"], "memory_text": belief, "truth_scope": "npc", "scope_key": character["id"], "salience": 0.6, "confidence": 0.8})
    return memories


def _world_id(prefix: str, idea: str) -> str:
    if not idea:
        return prefix
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", idea.lower()).strip("_")[:16]
    if slug:
        return f"{prefix}_{hashlib.sha1(idea.encode('utf-8')).hexdigest()[:8]}"
    return prefix


def _check_unique(issues: list[ValidationIssue], path: str, values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            issues.append(ValidationIssue("duplicate", path, f"duplicate {label}: {value}"))
        seen.add(value)


def _check_range(issues: list[ValidationIssue], path: str, value: int, minimum: int, maximum: int) -> None:
    if value < minimum or value > maximum:
        issues.append(ValidationIssue("small_dense_range", path, f"expected {minimum}-{maximum}, got {value}"))


def _reachable_locations(start: str, locations: list[LocationSpec]) -> set[str]:
    graph: dict[str, set[str]] = {item.id: set(item.connects_to) for item in locations}
    for source, targets in list(graph.items()):
        for target in targets:
            graph.setdefault(target, set()).add(source)
    visited: set[str] = set()
    stack = [start]
    while stack:
        item = stack.pop()
        if item in visited:
            continue
        visited.add(item)
        stack.extend(sorted(graph.get(item, set()) - visited))
    return visited


def _check_variables(issues: list[ValidationIssue], path: str, payload: dict[str, Any], variables: set[str]) -> None:
    for value in payload.values():
        if isinstance(value, str) and value.startswith("$") and value[1:] not in variables:
            issues.append(ValidationIssue("unbound_variable", path, f"unknown variable: {value}"))
