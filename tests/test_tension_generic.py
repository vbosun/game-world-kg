from __future__ import annotations

from game_world_kg.db import connect, init_db, transaction
from game_world_kg.events import EventLog
from game_world_kg.projector import StateProjector, delta
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService
from game_world_kg.tension import TensionScanner


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


# ── generic locked-location scanner ────────────────────────────────────


def test_generic_locked_location_creates_tension() -> None:
    """A locked location entity in any world must generate a locked_location tension."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "add_warehouse", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        create_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "old_warehouse", "entity_type": "Location", "name": "旧仓库", "properties": {"loc_type": "building"}},
            participants=["old_warehouse"],
        )
        projector.apply_event(create_event)
        lock_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "old_warehouse", "attr": "locked", "value": True},
            participants=["old_warehouse"],
            state_deltas=[delta("old_warehouse", "locked", None, True)],
        )
        projector.apply_event(lock_event)
        open_event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "old_warehouse", "attr": "open", "value": False},
            participants=["old_warehouse"],
            state_deltas=[delta("old_warehouse", "open", None, False)],
        )
        projector.apply_event(open_event)

    service = GameWorldService(conn)
    tensions = {t["tension_id"]: t for t in TensionScanner(service).scan(DEMO_WORLD_ID)}

    assert "tension_locked_old_warehouse" in tensions, \
        f"generic scanner should detect locked warehouse: {list(tensions.keys())}"
    wh = tensions["tension_locked_old_warehouse"]
    assert wh["type"] == "locked_location"
    assert "旧仓库" in wh["reason"]


def test_generic_scanner_does_not_duplicate_hardcoded() -> None:
    """Generic scanner must not create duplicate tensions for entities already covered."""
    service = _service()
    tensions = TensionScanner(service).scan(DEMO_WORLD_ID)
    tension_ids = [t["tension_id"] for t in tensions]
    assert tension_ids.count("tension_locked_iron_gate") == 1, \
        f"should have exactly one tension_locked_iron_gate: {tension_ids}"


def test_unlocked_location_does_not_create_tension() -> None:
    """An unlocked/open location should not generate a locked_location tension."""
    service = _service()
    w = DEMO_WORLD_ID
    service.turn_bound(w, "出示通行令", "show_pass_token")
    service.turn_bound(w, "请求放行", "ask_guard_open_gate")

    tensions = TensionScanner(service).scan(w)
    iron_gate_locked = [t for t in tensions if "iron_gate" in t["tension_id"] and t["type"] == "locked_location"]
    assert len(iron_gate_locked) == 0, \
        f"iron_gate tension should be gone when gate is open: {iron_gate_locked}"


# ── WorldSpec tension loading ─────────────────────────────────────────


def test_worldspec_tensions_loaded_from_nodes_table() -> None:
    """Scanner must load tensions from nodes table where entity_type='Tension'."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        log = EventLog(conn)
        turn_id = log.create_turn(DEMO_WORLD_ID, "add_tension_node", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        event = log.append(
            DEMO_WORLD_ID, turn_id, turn["turn_index"], "ADD_TENSION", "system",
            {
                "id": "worldspec_tension_test",
                "description": "世界中的魔法正在消退。",
                "tension_type": "magic_decay",
                "evidence": [{"source_type": "state", "entity_id": "world", "attr": "magic_level", "value": 3}],
                "affected_entities": ["world", "mage_guild"],
                "suggested_actions": ["investigate_magic", "talk_to_mage"],
                "priority": 0.8,
                "stake": "如果魔法完全消失，依赖魔法的设施将停止运作。",
                "sponsors": ["mage_guild"],
                "blockers": [],
                "player_touchpoints": ["investigate_magic"],
            },
            participants=["system"],
        )
        projector.apply_event(event)

    service = GameWorldService(conn)
    tensions = {t["tension_id"]: t for t in TensionScanner(service).scan(DEMO_WORLD_ID)}

    assert "worldspec_tension_test" in tensions, \
        f"worldspec tensions should be loaded: {list(tensions.keys())}"
    ws = tensions["worldspec_tension_test"]
    assert ws["type"] == "magic_decay"
    assert ws["priority"] == 0.8
    assert ws["stake"] == "如果魔法完全消失，依赖魔法的设施将停止运作。"


def test_worldspec_tension_without_id_is_skipped() -> None:
    """Tensions from nodes without an id in properties must be skipped gracefully."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        conn.execute(
            "INSERT INTO nodes(id, world_id, stable_key, entity_type, name, scope,"
            " valid_from_turn, valid_to_turn, confidence, source_event_id, properties_json, evidence_refs_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad_tension_node", DEMO_WORLD_ID, "bad_tension", "Tension", "bad",
             "canonical", 0, None, 1.0, "evt_seed", "{}", "[]"),
        )

    service = GameWorldService(conn)
    tensions = TensionScanner(service).scan(DEMO_WORLD_ID)
    assert isinstance(tensions, list)


# ── quest validation ──────────────────────────────────────────────────


def test_quest_objectives_are_actionable() -> None:
    """Quest validator must check that objectives reference achievable states."""
    service = _service()
    from game_world_kg.quest import QuestGenerator, QuestValidator

    validator = QuestValidator(service)
    quests = QuestGenerator(service).generate(DEMO_WORLD_ID)

    for quest in quests:
        result = validator.validate(quest, DEMO_WORLD_ID)
        assert "valid" in result
        assert isinstance(result["valid"], bool)
        assert "traceable" in result


def test_tension_scanner_works_for_world_with_no_hardcoded_entities() -> None:
    """Scanner must work for worlds that don't have iron_gate/guard_alos etc."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        conn.execute("INSERT INTO worlds(id, name, description, created_at) VALUES ('minimal', '最小世界', 'test', datetime('now'))")
        log = EventLog(conn)
        turn_id = log.create_turn("minimal", "seed_minimal", "")
        turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        projector = StateProjector(conn)
        # Create player
        p_event = log.append(
            "minimal", turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "player", "entity_type": "Character", "name": "玩家", "properties": {"archetype": "player"}},
            participants=["player"],
        )
        projector.apply_event(p_event)
        # Create a locked well location
        w_event = log.append(
            "minimal", turn_id, turn["turn_index"], "CREATE_ENTITY", "system",
            {"stable_key": "old_well", "entity_type": "Location", "name": "古井", "properties": {"loc_type": "landmark"}},
            participants=["old_well"],
        )
        projector.apply_event(w_event)
        lock_event = log.append(
            "minimal", turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "old_well", "attr": "locked", "value": True},
            participants=["old_well"],
            state_deltas=[delta("old_well", "locked", None, True)],
        )
        projector.apply_event(lock_event)
        set_open = log.append(
            "minimal", turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "old_well", "attr": "open", "value": False},
            participants=["old_well"],
            state_deltas=[delta("old_well", "open", None, False)],
        )
        projector.apply_event(set_open)
        loc_event = log.append(
            "minimal", turn_id, turn["turn_index"], "SET_STATE", "system",
            {"entity_id": "player", "attr": "location", "value": "village_square"},
            participants=["player"],
            state_deltas=[delta("player", "location", None, "village_square")],
        )
        projector.apply_event(loc_event)

    service = GameWorldService(conn)
    tensions = TensionScanner(service).scan("minimal")
    assert isinstance(tensions, list)
    locked_tensions = [t for t in tensions if t["type"] == "locked_location"]
    assert len(locked_tensions) >= 1, \
        f"generic scanner should detect locked well: {tensions}"
