from __future__ import annotations

from typing import Any

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


class MisleadingLLM:
    def __init__(self) -> None:
        self.json_calls = 0
        self.text_calls = 0

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        self.json_calls += 1
        return {"action_id": "unlock_gate_with_key", "target_id": "iron_gate", "confidence": 1.0, "reason": "misleading"}

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.4, timeout_seconds: float | None = None) -> str:
        self.text_calls += 1
        return "绑定行动已执行。"


def _service(llm: Any | None = None) -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn, llm)


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def test_play_state_shape_is_roleplay_by_default() -> None:
    state = _service().play_state(DEMO_WORLD_ID)

    assert {"scene", "affordances", "player", "quests", "tensions", "relationships", "timeline"}.issubset(state)
    assert state["scene"]["summary"]
    assert isinstance(state["timeline"], list)
    assert not _contains_key(state, {"payload", "truth_scope", "source_event_id", "evidence_refs"})


def test_selected_action_id_deterministically_bypasses_action_parser() -> None:
    llm = MisleadingLLM()
    service = _service(llm)

    result = service.play_turn(DEMO_WORLD_ID, "我其实想乱说一通", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    assert result["turn"]["accepted"] is True
    assert result["turn"]["action_id"] == "show_pass_token"
    assert result["bound_action"]["action_id"] == "show_pass_token"
    assert llm.json_calls == 0
    assert service.state(DEMO_WORLD_ID)["pass_token"]["holder"] == "guard_alos"


def test_selected_action_must_be_current_affordance() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "强行开门", selected_action_id="unlock_gate_with_key", selected_target_id="iron_gate")

    assert result["turn"]["accepted"] is False
    assert result["turn"]["action_id"] == "__unparsed__"
    assert service.events(DEMO_WORLD_ID)[-1]["event_type"] == "ACTION_REJECTED"


def test_unknown_free_input_writes_action_rejected() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "我召唤一座不存在的空中城")

    assert result["changes"][0]["type"] == "rule_rejection"
    assert service.events(DEMO_WORLD_ID)[-1]["event_type"] == "ACTION_REJECTED"


def test_feedback_changes_are_event_and_state_diff_driven() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "交出通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")
    change_types = {change["type"] for change in result["changes"]}

    assert {"resource_change", "relationship_change"}.issubset(change_types)
    assert any(change.get("entity_id") == "guard_alos" and change.get("attr") == "trust.player" for change in result["changes"])


def test_roleplay_mode_hides_debug_private_fields_but_dev_mode_exposes_them() -> None:
    service = _service()
    service.play_turn(DEMO_WORLD_ID, "交出通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    roleplay = service.play_state(DEMO_WORLD_ID)
    dev_timeline = service.play_timeline(DEMO_WORLD_ID, mode="dev")

    assert not _contains_key(roleplay, {"payload", "truth_scope", "source_event_id", "evidence_refs"})
    assert any("payload" in item for item in dev_timeline)


def test_play_turn_triggers_foreground_npc_activity_when_accepted() -> None:
    service = _service()

    result = service.play_turn(DEMO_WORLD_ID, "交出通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    assert result["npc_activity"]["npc_count"] >= 1
    assert any(item["acted"] for item in result["npc_activity"]["results"])
    assert result["world_reactions"]
    assert service.events(DEMO_WORLD_ID)[-1]["event_type"] == "NPC_ACTION"
