from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .worldspec import WorldIntentExtractor, WorldSpec, WorldSpecValidator, sample_world_spec as base_sample_world_spec


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


class WorldSpecNormalizer:
    """Normalize common LLM WorldSpec aliases before strict validation.

    This deliberately keeps the strict Pydantic schema intact. It only maps
    common synonym fields into the project schema so raw LLM candidates can
    enter validate/repair instead of failing before diagnostics are available.
    """

    def normalize(self, candidate: dict[str, Any]) -> dict[str, Any]:
        fixed = json.loads(json.dumps(candidate, ensure_ascii=False))
        self._normalize_top_level(fixed)
        self._normalize_locations(fixed)
        self._normalize_stable_keys(fixed, "locations")
        self._normalize_stable_keys(fixed, "characters")
        self._normalize_stable_keys(fixed, "items")
        self._normalize_stable_keys(fixed, "factions")
        self._normalize_characters(fixed)
        self._normalize_items(fixed)
        self._normalize_action_templates(fixed)
        self._normalize_tensions(fixed)
        self._normalize_quests(fixed)
        return fixed

    def _normalize_top_level(self, fixed: dict[str, Any]) -> None:
        player_start = fixed.setdefault("player_start", {})
        if "location_id" not in player_start:
            for alias in ("location", "start_location", "locationId"):
                if alias in player_start:
                    player_start["location_id"] = player_start.pop(alias)
                    break
        player_start.setdefault("character_id", "player")

        if "initial_tensions" not in fixed and "tensions" in fixed:
            fixed["initial_tensions"] = fixed.pop("tensions")
        if "initial_quests" not in fixed and "quests" in fixed:
            fixed["initial_quests"] = fixed.pop("quests")
        if "initial_memories" not in fixed and "memories" in fixed:
            fixed["initial_memories"] = fixed.pop("memories")
        if "initial_states" not in fixed and "states" in fixed:
            fixed["initial_states"] = fixed.pop("states")
        if fixed.get("scale") == "small":
            fixed["scale"] = "small_dense"
        fixed.setdefault("scale", "small_dense")
        fixed.setdefault("ontology_extensions", [])
        fixed.setdefault("resources", [])
        fixed.setdefault("rules", [])
        fixed.setdefault("background_lore", [])

    def _normalize_locations(self, fixed: dict[str, Any]) -> None:
        for location in fixed.get("locations", []) or []:
            if not isinstance(location, dict):
                continue
            if "location_type" not in location and "type" in location:
                location["location_type"] = location.pop("type")
            location.setdefault("connects_to", [])
            location.setdefault("tags", [])

    def _normalize_stable_keys(self, fixed: dict[str, Any], key: str) -> None:
        for item in fixed.get(key, []) or []:
            if isinstance(item, dict) and "stable_key" not in item and item.get("id"):
                item["stable_key"] = item["id"]

    def _normalize_characters(self, fixed: dict[str, Any]) -> None:
        for character in fixed.get("characters", []) or []:
            if not isinstance(character, dict):
                continue
            if "start_location" not in character:
                for alias in ("location", "location_id", "start", "current_location"):
                    if alias in character:
                        character["start_location"] = character.pop(alias)
                        break
            character.setdefault("goals", [])
            character.setdefault("personality", {})
            character.setdefault("initial_beliefs", [])

    def _normalize_items(self, fixed: dict[str, Any]) -> None:
        for item in fixed.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            if "owner_id" not in item:
                for alias in ("owner", "holder", "holder_id"):
                    if alias in item:
                        item["owner_id"] = item.pop(alias)
                        break
            if "location_id" not in item:
                for alias in ("location", "place", "place_id"):
                    if alias in item:
                        item["location_id"] = item.pop(alias)
                        break
            item.setdefault("tags", [])

    def _normalize_action_templates(self, fixed: dict[str, Any]) -> None:
        for template in fixed.get("action_templates", []) or []:
            if not isinstance(template, dict):
                continue
            if "action_id" not in template and "id" in template:
                template["action_id"] = template.pop("id")
            if "label_template" not in template and "title" in template:
                template["label_template"] = template.pop("title")
            template.setdefault("target_selector", {})
            template.setdefault("arg_schema", {})
            template.setdefault("preconditions", [])
            template.setdefault("risk", "low")

    def _normalize_tensions(self, fixed: dict[str, Any]) -> None:
        for tension in fixed.get("initial_tensions", []) or []:
            if not isinstance(tension, dict):
                continue
            if "tension_type" not in tension:
                for alias in ("type", "kind"):
                    if alias in tension:
                        tension["tension_type"] = tension.pop(alias)
                        break
            if "affected_entities" not in tension:
                for alias in ("targets", "affected", "entities"):
                    if alias in tension:
                        tension["affected_entities"] = tension.pop(alias)
                        break
            if "suggested_actions" not in tension:
                for alias in ("actions", "available_actions", "suggested_action_ids"):
                    if alias in tension:
                        tension["suggested_actions"] = tension.pop(alias)
                        break
            if isinstance(tension.get("evidence"), str):
                tension["evidence"] = [{"type": "text", "text": tension["evidence"]}]
            tension.setdefault("affected_entities", [])
            tension.setdefault("evidence", [])
            tension.setdefault("suggested_actions", [])

    def _normalize_quests(self, fixed: dict[str, Any]) -> None:
        for quest in fixed.get("initial_quests", []) or []:
            if not isinstance(quest, dict):
                continue
            if "issuer_id" not in quest:
                for alias in ("issuer", "giver", "quest_giver"):
                    if alias in quest:
                        quest["issuer_id"] = quest.pop(alias)
                        break
            if "tension_id" not in quest:
                for alias in ("tension", "source_tension_id", "source_tension"):
                    if alias in quest:
                        quest["tension_id"] = quest.pop(alias)
                        break
            if "rewards" not in quest and "reward" in quest:
                reward = quest.pop("reward")
                quest["rewards"] = reward if isinstance(reward, list) else [reward]
            if "failure_consequences" not in quest and "failure_consequence" in quest:
                consequence = quest.pop("failure_consequence")
                quest["failure_consequences"] = consequence if isinstance(consequence, list) else [consequence]
            if isinstance(quest.get("evidence"), str):
                quest["evidence"] = [{"text": quest["evidence"]}]
            quest.setdefault("objectives", [])
            quest.setdefault("rewards", [])
            quest.setdefault("failure_consequences", [])
            quest.setdefault("evidence", [])


class WorldSpecRepairer:
    def __init__(self) -> None:
        from .worldspec import WorldSpecRepairer as BaseRepairer

        self._base = BaseRepairer()
        self._normalizer = WorldSpecNormalizer()

    def repair(self, candidate: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
        fixed = self._normalizer.normalize(candidate)
        genre = _genre_from_candidate(fixed)
        sample = sample_world_spec(genre, fixed.get("theme", "")).model_dump(mode="json")
        fixed = _repair_scale_with_sample(fixed, sample)
        repaired = self._base.repair(fixed, report or WorldSpecValidator().validate(fixed))
        return self._normalizer.normalize(repaired)


class WorldSpecGenerator:
    def __init__(self, llm_client: Any | None = None) -> None:
        from .worldspec import WorldSpecGenerator as BaseGenerator

        self.llm_client = llm_client
        self._base = BaseGenerator(llm_client)
        self._normalizer = WorldSpecNormalizer()
        self.last_source = "sample_fallback"
        self.last_candidate_payload: dict[str, Any] | None = None
        self.last_normalized_candidate: dict[str, Any] | None = None
        self.last_raw_response: str | None = None
        self.last_error: str | None = None
        self.last_warnings: list[str] = []

    def generate(self, idea: str) -> WorldSpec:
        intent = WorldIntentExtractor().extract(idea)
        requested_genre = intent["genre"]
        if self.llm_client is not None:
            spec = self._generate_with_llm(intent)
            if spec is not None:
                self.last_source = "llm_candidate"
                return spec
        self.last_source = "sample_fallback"
        spec = sample_world_spec(requested_genre, idea)
        self._record_warnings(requested_genre, spec.model_dump(mode="json"))
        return spec

    def _generate_with_llm(self, intent: dict[str, str]) -> WorldSpec | None:
        try:
            payload = self._base._generate_with_llm(intent)
            self.last_raw_response = getattr(self.llm_client, "last_raw_text", None)
            if payload is None:
                self.last_error = self._base.last_error
                return None
            candidate = payload.model_dump(mode="json") if isinstance(payload, WorldSpec) else payload
            self.last_candidate_payload = candidate
            normalized = self._normalizer.normalize(candidate)
            self.last_normalized_candidate = normalized
            report = WorldSpecValidator().validate(normalized)
            if not report["valid"]:
                normalized = WorldSpecRepairer().repair(normalized, report)
                report = WorldSpecValidator().validate(normalized)
            if not report["valid"]:
                self.last_error = json.dumps(report, ensure_ascii=False)
                return None
            spec = WorldSpec.model_validate(normalized)
            self._record_warnings(intent["genre"], spec.model_dump(mode="json"))
            return spec
        except Exception as exc:
            self.last_raw_response = getattr(self.llm_client, "last_raw_text", None)
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def _record_warnings(self, requested_genre: str, spec_payload: dict[str, Any]) -> None:
        self.last_warnings = []
        if requested_genre == "ocean" and _contains_keys(spec_payload, OCEAN_CONTAMINATION_KEYS):
            self.last_warnings.append("genre_contamination_detected")


def sample_world_spec(genre: str = "cultivation", idea: str = "") -> WorldSpec:
    if genre == "ocean":
        return _ocean_spec(idea)
    return base_sample_world_spec(genre, idea)


def _ocean_spec(idea: str = "") -> WorldSpec:
    data = {
        "world_id": _world_id("demo_tide_islands", idea),
        "title": _derive_ocean_title(idea),
        "genre": "ocean",
        "theme": idea or "海洋漂流、生存、船体成长与潮汐势力冲突",
        "starting_area": "wrecked_raft_beach",
        "scale": "small_dense",
        "player_start": {"character_id": "player", "location_id": "wrecked_raft_beach"},
        "ontology_extensions": [],
        "locations": [
            {"id": "wrecked_raft_beach", "stable_key": "wrecked_raft_beach", "name": "破木筏浅滩", "description": "玩家从破损木筏旁醒来，周围漂着木板和空桶。", "location_type": "beach", "connects_to": ["driftwood_lane", "freshwater_cove"], "tags": ["start", "salvage"]},
            {"id": "driftwood_lane", "stable_key": "driftwood_lane", "name": "漂木航道", "description": "漂浮木材聚集的潮道，适合捡拾船体材料。", "location_type": "sea_route", "connects_to": ["wrecked_raft_beach", "black_tide_cove", "lighthouse_island"], "tags": ["resource", "weather"]},
            {"id": "freshwater_cove", "stable_key": "freshwater_cove", "name": "淡水岩湾", "description": "岩缝里有少量淡水，是生存的关键地点。", "location_type": "cove", "connects_to": ["wrecked_raft_beach", "floating_isle"], "tags": ["water", "survival"]},
            {"id": "sunken_temple", "stable_key": "sunken_temple", "name": "沉没神庙", "description": "半沉在潮汐下的古老遗迹，藏有导航符标。", "location_type": "ruin", "connects_to": ["lighthouse_island", "black_tide_cove"], "tags": ["ruin", "mystery"]},
            {"id": "black_tide_cove", "stable_key": "black_tide_cove", "name": "黑潮暗湾", "description": "黑潮兄弟会出没的暗湾，交易和冲突都很危险。", "location_type": "pirate_cove", "connects_to": ["driftwood_lane", "sunken_temple"], "tags": ["danger", "faction"]},
            {"id": "lighthouse_island", "stable_key": "lighthouse_island", "name": "灯塔岛", "description": "灯塔修会守着旧灯塔，掌握天气和航向知识。", "location_type": "island", "connects_to": ["driftwood_lane", "sunken_temple", "floating_isle"], "tags": ["faction", "navigation"]},
            {"id": "floating_isle", "stable_key": "floating_isle", "name": "浮岛集市", "description": "浮岛部落和白帆联盟交换物资的移动集市。", "location_type": "floating_market", "connects_to": ["freshwater_cove", "lighthouse_island"], "tags": ["trade", "social"]},
        ],
        "characters": [
            {"id": "raftwright_mara", "stable_key": "raftwright_mara", "name": "筏匠玛拉", "role": "raftwright", "start_location": "wrecked_raft_beach", "faction_id": "white_sail_alliance", "goals": [{"goal_id": "repair_survivor_raft", "priority": 0.8, "risk_tolerance": 0.3}], "personality": {"practical": 0.8}, "initial_beliefs": ["船体越早修好，越能避开下一场风暴。"]},
            {"id": "water_keeper_nuo", "stable_key": "water_keeper_nuo", "name": "守水人诺", "role": "water_keeper", "start_location": "freshwater_cove", "faction_id": "floating_tribes", "goals": [{"goal_id": "protect_freshwater", "priority": 0.9, "risk_tolerance": 0.2}], "personality": {"guarded": 0.7}, "initial_beliefs": ["淡水比金币更能决定谁能活下去。"]},
            {"id": "beacon_monk_sai", "stable_key": "beacon_monk_sai", "name": "灯塔修士赛", "role": "beacon_monk", "start_location": "lighthouse_island", "faction_id": "lighthouse_order", "goals": [{"goal_id": "keep_beacon_lit", "priority": 0.8, "risk_tolerance": 0.3}], "personality": {"calm": 0.7}, "initial_beliefs": ["潮汐异常和沉没神庙的旧符标有关。"]},
            {"id": "blacktide_raider_kor", "stable_key": "blacktide_raider_kor", "name": "黑潮掠手科尔", "role": "raider", "start_location": "black_tide_cove", "faction_id": "black_tide_brotherhood", "goals": [{"goal_id": "control_salvage_route", "priority": 0.7, "risk_tolerance": 0.7}], "personality": {"aggressive": 0.8}, "initial_beliefs": ["漂木航道的残骸应该归黑潮兄弟会。"]},
            {"id": "sail_envoy_lian", "stable_key": "sail_envoy_lian", "name": "白帆使者莲", "role": "envoy", "start_location": "floating_isle", "faction_id": "white_sail_alliance", "goals": [{"goal_id": "secure_trade_routes", "priority": 0.7, "risk_tolerance": 0.4}], "personality": {"diplomatic": 0.8}, "initial_beliefs": ["一个可靠的漂流者可以成为群岛间的信使。"]},
            {"id": "tide_child_emi", "stable_key": "tide_child_emi", "name": "潮童艾米", "role": "scout", "start_location": "driftwood_lane", "faction_id": "floating_tribes", "goals": [{"goal_id": "map_safe_currents", "priority": 0.6, "risk_tolerance": 0.5}], "personality": {"curious": 0.9}, "initial_beliefs": ["风暴前，沉没神庙附近会出现蓝色潮光。"]},
        ],
        "items": [
            {"id": "broken_raft", "stable_key": "broken_raft", "name": "破木筏", "item_type": "ship", "owner_id": "player", "tags": ["growth", "survival"]},
            {"id": "freshwater_skin", "stable_key": "freshwater_skin", "name": "半袋淡水", "item_type": "water", "owner_id": "player", "tags": ["water"]},
            {"id": "salvage_planks", "stable_key": "salvage_planks", "name": "漂流木板", "item_type": "material", "location_id": "driftwood_lane", "tags": ["craft"]},
            {"id": "rain_catcher", "stable_key": "rain_catcher", "name": "接雨布", "item_type": "tool", "owner_id": "raftwright_mara", "tags": ["water", "craft"]},
            {"id": "beacon_lens", "stable_key": "beacon_lens", "name": "灯塔透镜", "item_type": "navigation", "location_id": "lighthouse_island", "tags": ["quest"]},
            {"id": "tide_charm", "stable_key": "tide_charm", "name": "潮汐护符", "item_type": "relic", "location_id": "sunken_temple", "tags": ["mystery"]},
            {"id": "black_sail_token", "stable_key": "black_sail_token", "name": "黑帆木牌", "item_type": "token", "owner_id": "blacktide_raider_kor", "tags": ["faction"]},
            {"id": "trade_crate", "stable_key": "trade_crate", "name": "白帆货箱", "item_type": "trade_good", "location_id": "floating_isle", "tags": ["trade"]},
        ],
        "factions": [
            {"id": "white_sail_alliance", "stable_key": "white_sail_alliance", "name": "白帆联盟", "faction_type": "trade", "goals": ["keep_routes_open", "protect_survivors"], "relations": [{"target": "black_tide_brotherhood", "relation": "opposes", "value": -0.5}]},
            {"id": "black_tide_brotherhood", "stable_key": "black_tide_brotherhood", "name": "黑潮兄弟会", "faction_type": "raiders", "goals": ["control_salvage", "profit_from_fear"], "relations": [{"target": "white_sail_alliance", "relation": "opposes", "value": -0.5}]},
            {"id": "lighthouse_order", "stable_key": "lighthouse_order", "name": "灯塔修会", "faction_type": "monastic", "goals": ["predict_weather", "keep_beacon_lit"], "relations": [{"target": "floating_tribes", "relation": "advises", "value": 0.4}]},
            {"id": "floating_tribes", "stable_key": "floating_tribes", "name": "浮岛部落", "faction_type": "tribe", "goals": ["protect_freshwater", "survive_tides"], "relations": [{"target": "lighthouse_order", "relation": "trusts", "value": 0.4}]},
        ],
        "resources": [{"entity": "player", "attr": "freshwater", "value": 2}, {"entity": "broken_raft", "attr": "hull", "value": 1}],
        "rules": [],
        "action_templates": base_sample_world_spec("cultivation").model_dump(mode="json")["action_templates"],
        "initial_states": [
            {"entity": "player", "attr": "location", "value": "wrecked_raft_beach"},
            {"entity": "player", "attr": "freshwater", "value": 2},
            {"entity": "broken_raft", "attr": "hull", "value": 1},
            {"entity": "freshwater_cove", "attr": "water_level", "value": "low"},
            {"entity": "driftwood_lane", "attr": "weather", "value": "unstable"},
            {"entity": "sunken_temple", "attr": "tide_locked", "value": True},
        ],
        "initial_memories": [],
        "initial_tensions": [
            {"id": "freshwater_shortage", "tension_type": "resource_shortage", "description": "淡水岩湾水量下降，各方开始争夺淡水。", "affected_entities": ["freshwater_cove", "freshwater_skin", "water_keeper_nuo"], "evidence": [{"type": "state", "entity": "freshwater_cove", "attr": "water_level", "value": "low"}], "suggested_actions": ["ask_about_topic", "trade", "request_help"], "priority": 0.9},
            {"id": "raft_needs_repair", "tension_type": "resource_shortage", "description": "玩家的破木筏无法承受下一场风暴。", "affected_entities": ["broken_raft", "salvage_planks", "raftwright_mara"], "evidence": [{"type": "state", "entity": "broken_raft", "attr": "hull", "value": 1}], "suggested_actions": ["inspect", "request_help"], "priority": 0.8},
            {"id": "black_tide_pressure", "tension_type": "hostility_rising", "description": "黑潮兄弟会想控制漂木航道的残骸资源。", "affected_entities": ["black_tide_cove", "blacktide_raider_kor", "driftwood_lane"], "evidence": [{"type": "state", "entity": "driftwood_lane", "attr": "weather", "value": "unstable"}], "suggested_actions": ["ask_about_topic", "spread_rumor"], "priority": 0.7},
        ],
        "initial_quests": [
            {"id": "repair_the_raft", "title": "修补破木筏", "issuer_id": "raftwright_mara", "tension_id": "raft_needs_repair", "objectives": [{"type": "collect_item", "target": "salvage_planks"}, {"type": "change_state", "target": "broken_raft"}], "rewards": [{"type": "grant_permission", "entity": "player", "attr": "sail_farther", "target": "driftwood_lane"}], "failure_consequences": [{"type": "increase_tension", "target": "raft_needs_repair", "delta": 1}], "evidence": [{"tension_id": "raft_needs_repair"}]},
            {"id": "secure_freshwater", "title": "确保淡水来源", "issuer_id": "water_keeper_nuo", "tension_id": "freshwater_shortage", "objectives": [{"type": "visit_location", "target": "freshwater_cove"}, {"type": "collect_item", "target": "rain_catcher"}], "rewards": [{"type": "delta_resource", "entity": "player", "attr": "freshwater", "delta": 2}], "failure_consequences": [{"type": "increase_tension", "target": "freshwater_shortage", "delta": 1}], "evidence": [{"tension_id": "freshwater_shortage"}]},
        ],
        "background_lore": ["陆地被海水吞没后，群岛靠漂流资源和淡水维持生存。", "潮汐异常让旧航线、沉没遗迹和海上势力关系同时失衡。"],
    }
    data["initial_memories"] = [
        {"owner_id": character["id"], "memory_text": belief, "truth_scope": "npc", "scope_key": character["id"], "salience": 0.6, "confidence": 0.8}
        for character in data["characters"]
        for belief in character.get("initial_beliefs", [])
    ]
    return WorldSpec.model_validate(data)


def _repair_scale_with_sample(fixed: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    fixed = json.loads(json.dumps(fixed, ensure_ascii=False))
    limits = {
        "locations": (6, 10),
        "characters": (5, 8),
        "items": (8, 15),
        "factions": (2, 4),
        "action_templates": (8, 15),
        "initial_tensions": (3, 5),
        "initial_quests": (2, 4),
    }
    for key, (minimum, maximum) in limits.items():
        current = fixed.setdefault(key, [])
        seen = {item.get("id") or item.get("action_id") for item in current if isinstance(item, dict)}
        for item in sample.get(key, []):
            item_key = item.get("id") or item.get("action_id")
            if len(current) >= minimum:
                break
            if item_key not in seen:
                current.append(json.loads(json.dumps(item, ensure_ascii=False)))
                seen.add(item_key)
        if len(current) > maximum:
            del current[maximum:]
    return fixed


def _genre_from_candidate(candidate: dict[str, Any]) -> str:
    genre = candidate.get("genre")
    if genre in {"ocean", "village", "cultivation"}:
        return genre
    return WorldIntentExtractor().extract(str(candidate.get("theme") or candidate.get("title") or ""))["genre"]


def _contains_keys(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(k in keys or _contains_keys(v, keys) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_keys(item, keys) for item in value)
    return isinstance(value, str) and value in keys


def _world_id(prefix: str, idea: str) -> str:
    import hashlib
    import re

    if not idea:
        return prefix
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", idea.lower()).strip("_")[:16]
    digest = hashlib.sha1(idea.encode("utf-8")).hexdigest()[:8]
    if slug:
        return f"{prefix}_{slug}_{digest}"
    return f"{prefix}_{digest}"


def _derive_ocean_title(idea: str) -> str:
    return "潮汐群岛失衡" if idea else "潮汐群岛失衡"
