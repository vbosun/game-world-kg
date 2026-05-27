from __future__ import annotations

import inspect

from game_world_kg.action_template import ActionTemplateStore, PredicateEvaluator
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.projector import StateProjector, delta
from game_world_kg.rules import RuleEngine
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService
from game_world_kg.worldspec import WorldSpecRepairer, WorldSpecValidator, sample_world_spec


def _worldspec_service() -> tuple[GameWorldService, str]:
    conn = connect(":memory:")
    init_db(conn)
    service = GameWorldService(conn)
    generated = service.generate_worldspec("我想玩一个修仙小镇，主角刚入外门，后山妖兽异常。")
    bootstrap = service.bootstrap_worldspec(generated["spec"])
    assert bootstrap["accepted"] is True
    return service, generated["world_id"]


def test_bootstrap_uses_explicit_turn_and_player_starts_after_bootstrap() -> None:
    service, world_id = _worldspec_service()

    turns = service.conn.execute("SELECT * FROM turns WHERE world_id = ? ORDER BY turn_index", (world_id,)).fetchall()
    bootstrap_events = [event for event in service.events(world_id) if event["event_type"] == "WORLD_CREATED"]
    result = service.turn(world_id, "完全未知的行动文本")

    assert turns[0]["turn_index"] == 0
    assert turns[0]["player_input"].startswith("bootstrap:")
    assert bootstrap_events[0]["turn_id"] == turns[0]["id"]
    assert result["turn_index"] == 1
    assert result["accepted"] is False


def test_replay_preserves_bootstrap_then_player_order_and_restores_action_templates() -> None:
    service, world_id = _worldspec_service()
    before = len(ActionTemplateStore(service.conn).list_enabled(world_id))
    service.turn(world_id, "观察周围")

    with transaction(service.conn):
        service.conn.execute("DELETE FROM action_templates WHERE world_id = ?", (world_id,))
    assert ActionTemplateStore(service.conn).list_enabled(world_id) == []
    replayed = service.replay(world_id)
    events = service.events(world_id)

    assert events[0]["turn_index"] == 0
    assert events[0]["event_type"] == "WORLD_CREATED"
    assert len(ActionTemplateStore(service.conn).list_enabled(world_id)) == before
    assert replayed["state"]["player"]["location"] == "town_gate"


def test_template_only_rejects_unknown_action_without_legacy_fallback() -> None:
    service, world_id = _worldspec_service()
    log = EventLog(service.conn)
    with transaction(service.conn):
        turn_id = log.create_turn(world_id, "legacy fallback probe")
        turn = service.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        result = RuleEngine(service.conn).resolve_turn(world_id, turn_id, turn["turn_index"], "守卫 放行", action_id="show_pass_token")

    assert service.get_world(world_id)["runtime_mode"] == "template_only"
    assert result.accepted is False
    assert result.action_id == "show_pass_token"
    assert "template" in result.reason


def test_template_only_does_not_default_to_talk_to_guard() -> None:
    service, world_id = _worldspec_service()

    result = service.turn(world_id, "这不是任何当前可行动作")

    assert result["accepted"] is False
    assert result["action_id"] == "__unparsed__"


def test_demo_gate_still_supports_legacy_actions() -> None:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    service = GameWorldService(conn)

    result = service.turn(DEMO_WORLD_ID, "我向守卫出示通行令")

    assert service.get_world(DEMO_WORLD_ID)["runtime_mode"] == "legacy_demo"
    assert result["accepted"] is True
    assert result["action_id"] == "show_pass_token"


def test_connected_location_has_no_world_specific_inner_city_logic() -> None:
    source = inspect.getsource(PredicateEvaluator.evaluate)

    assert "inner_city" not in source
    assert "iron_gate" not in source


def test_locked_edge_blocks_and_unblocks_by_generic_state_requirement() -> None:
    conn = connect(":memory:")
    init_db(conn)
    projector = StateProjector(conn)
    log = EventLog(conn)
    with transaction(conn):
        conn.execute("INSERT INTO worlds(id, name, description, created_at) VALUES ('w', 'w', '', 'now')")
        turn_id = log.create_bootstrap_turn("w", "test")
        for node_id in ["actor", "a", "b", "gate"]:
            event = log.append("w", turn_id, 0, "CREATE_ENTITY", "system", {"stable_key": node_id, "entity_type": "Location", "name": node_id, "properties": {}}, participants=[node_id])
            projector.apply_event(event)
        for event in [
            log.append("w", turn_id, 0, "SET_STATE", "system", {"entity_id": "actor", "attr": "location", "value": "a"}, state_deltas=[delta("actor", "location", None, "a")]),
            log.append("w", turn_id, 0, "SET_STATE", "system", {"entity_id": "gate", "attr": "open", "value": False}, state_deltas=[delta("gate", "open", None, False)]),
            log.append("w", turn_id, 0, "CONNECT_LOCATION", "system", {"from": "a", "to": "b", "properties": {"requires_state": {"entity": "gate", "attr": "open", "value": True}}}),
        ]:
            projector.apply_event(event)

    predicate = {"type": "edge_unblocked", "actor": "$actor", "target": "$target"}
    evaluator = PredicateEvaluator(conn)
    assert evaluator.evaluate("w", predicate, {"actor": "actor", "target": "b"}) is False

    with transaction(conn):
        event = log.append("w", turn_id, 0, "SET_STATE", "system", {"entity_id": "gate", "attr": "open", "value": True}, state_deltas=[delta("gate", "open", False, True)])
        projector.apply_event(event)
    assert evaluator.evaluate("w", predicate, {"actor": "actor", "target": "b"}) is True


def test_worldgen_evaluation_uses_real_checks_and_detects_invalid_rejection() -> None:
    service, world_id = _worldspec_service()

    result = service.worldgen_evaluation(world_id)

    assert result["bootstrap_replay_equivalence"] == 1.0
    assert result["invalid_action_rate"] == 0.0
    assert result["turns_playable"] == 30
    assert result["details"]["state_hash_before_replay"] == result["details"]["state_hash_after_replay"]


def test_repairer_fixes_common_llm_errors() -> None:
    spec = sample_world_spec("cultivation").model_dump(mode="json")
    spec["locations"][-1]["connects_to"] = []
    spec["locations"][1]["connects_to"].remove("well_square")
    spec["items"][0].pop("owner_id")
    spec["characters"][0]["goals"] = []
    spec["action_templates"][0]["effects"].append({"type": "free_text_magic"})

    first_report = WorldSpecValidator().validate(spec)
    repaired = WorldSpecRepairer().repair(spec, first_report)
    final_report = WorldSpecValidator().validate(repaired)

    assert final_report["valid"] is True
