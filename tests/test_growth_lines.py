from __future__ import annotations

from game_world_kg.action_template import ActionTemplate, ActionTemplateStore
from game_world_kg.db import connect, init_db, transaction
from game_world_kg.seed import DEMO_WORLD_ID, seed_demo_world
from game_world_kg.service import GameWorldService


def _service() -> GameWorldService:
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
    return GameWorldService(conn)


def _growth_events(service: GameWorldService, world_id: str) -> list[dict]:
    return [e for e in service.events(world_id) if e["event_type"] == "PLAYER_GROWTH"]


def _growth_lines(service: GameWorldService, world_id: str) -> list[dict]:
    lines: list[dict] = []
    for event in _growth_events(service, world_id):
        for line in event.get("payload", {}).get("growth_lines", []):
            lines.append(line)
    return lines


# ── relationship growth ──────────────────────────────────────────────


def test_show_pass_token_produces_relationship_growth() -> None:
    """show_pass_token CHANGE_RELATION effect must produce relationship growth line."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    rel_lines = [l for l in _growth_lines(service, w) if l["line"] == "relationship"]
    assert len(rel_lines) >= 1, f"expected relationship growth, got {_growth_lines(service, w)}"
    rel = rel_lines[0]
    assert rel["src"] == "guard_alos"
    assert rel["rel"] == "TRUSTS"
    assert rel["dst"] == "player"
    assert rel["delta"] == 2


# ── skill growth ─────────────────────────────────────────────────────


def test_talk_to_guard_produces_skill_social_growth() -> None:
    """talk_to_guard action_id matches 'talk' pattern → skill.social growth."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "和守卫交谈", selected_action_id="talk_to_guard", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    skill_lines = [l for l in _growth_lines(service, w) if l["line"] == "skill"]
    assert len(skill_lines) >= 1, f"expected skill growth, got {_growth_lines(service, w)}"
    assert skill_lines[0]["attr"] == "skill.social"


def test_bribe_guard_produces_skill_social_growth() -> None:
    """bribe_guard matches 'bribe' pattern → skill.social growth."""
    service = _service()
    w = DEMO_WORLD_ID

    result = service.play_turn(w, "贿赂", selected_action_id="bribe_guard", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    skill_lines = [l for l in _growth_lines(service, w) if l["line"] == "skill"]
    assert len(skill_lines) >= 1
    assert skill_lines[0]["attr"] == "skill.social"


def test_skill_is_incremented_in_player_state() -> None:
    """After a skill-matching action, player state should have skill.social incremented."""
    service = _service()
    w = DEMO_WORLD_ID

    state_before = service.state(w)
    social_before = state_before.get("player", {}).get("skill.social", 0)

    service.play_turn(w, "和守卫交谈", selected_action_id="talk_to_guard", selected_target_id="guard_alos")

    state_after = service.state(w)
    social_after = state_after.get("player", {}).get("skill.social", 0)
    assert social_after == social_before + 1


# ── knowledge growth ─────────────────────────────────────────────────


def test_knowledge_growth_from_add_knowledge_effect() -> None:
    """add_knowledge effect must produce knowledge growth line."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="investigate_gate",
            label="调查城门",
            target_id="iron_gate",
            risk="low",
            reason="玩家在城门口观察",
            preconditions=[],
            effects=[{"type": "add_knowledge", "entity": "$actor", "clue": "城门上刻着古老的符文", "actor": "$actor"}],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    result = service.play_turn(w, "调查", selected_action_id="investigate_gate", selected_target_id="iron_gate")
    assert result["turn"]["accepted"] is True

    knowledge_lines = [l for l in _growth_lines(service, w) if l["line"] == "knowledge"]
    assert len(knowledge_lines) >= 1, f"expected knowledge growth, got {_growth_lines(service, w)}"
    assert any("符文" in l.get("clue", "") for l in knowledge_lines)


def test_knowledge_growth_from_player_scoped_add_memory() -> None:
    """add_memory with truth_scope=player must produce knowledge growth line."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="recall_memory_test",
            label="回忆往事",
            target_id=None,
            risk="low",
            reason="test player memory growth",
            preconditions=[],
            effects=[{
                "type": "add_memory",
                "owner": "$actor",
                "memory_text": "玩家回忆起一段关于古老传说的线索。",
                "truth_scope": "player",
                "salience": 0.9,
                "valence": 0.3,
                "actor": "system",
            }],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    result = service.play_turn(w, "回忆", selected_action_id="recall_memory_test")
    assert result["turn"]["accepted"] is True

    knowledge_lines = [l for l in _growth_lines(service, w) if l["line"] == "knowledge"]
    assert len(knowledge_lines) >= 1, f"expected knowledge growth from player memory, got {_growth_lines(service, w)}"


# ── identity growth ──────────────────────────────────────────────────


def test_identity_growth_from_add_identity_tag() -> None:
    """add_identity_tag effect must produce identity growth line."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="declare_hero",
            label="自称英雄",
            target_id=None,
            risk="low",
            reason="test identity growth",
            preconditions=[],
            effects=[{"type": "add_identity_tag", "entity": "$actor", "tag": "自称英雄", "actor": "$actor"}],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    result = service.play_turn(w, "自称英雄", selected_action_id="declare_hero")
    assert result["turn"]["accepted"] is True

    identity_lines = [l for l in _growth_lines(service, w) if l["line"] == "identity"]
    assert len(identity_lines) >= 1, f"expected identity growth, got {_growth_lines(service, w)}"
    assert any("自称英雄" in l.get("tag", "") for l in identity_lines)


def test_identity_tag_reflected_in_player_panel() -> None:
    """After add_identity_tag, player_panel identity_tags must include the new tag."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="earn_title_hero",
            label="赢得英雄称号",
            target_id=None,
            risk="low",
            reason="test identity panel",
            preconditions=[],
            effects=[{"type": "add_identity_tag", "entity": "$actor", "tag": "英雄", "actor": "system"}],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    service.play_turn(w, "赢得称号", selected_action_id="earn_title_hero")

    from game_world_kg.playable_turn import PlayableTurnKernel
    panel = PlayableTurnKernel(service).player_panel(w)
    assert "英雄" in panel["identity_tags"], f"identity_tags should contain 英雄: {panel['identity_tags']}"


# ── permission growth ────────────────────────────────────────────────


def test_permission_growth_from_grant_permission() -> None:
    """grant_permission effect must produce permission growth line."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="receive_gate_pass",
            label="领取通行证",
            target_id=None,
            risk="low",
            reason="test permission growth",
            preconditions=[],
            effects=[{"type": "grant_permission", "entity": "$actor", "permission": "gate_pass", "actor": "system"}],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    result = service.play_turn(w, "领通行证", selected_action_id="receive_gate_pass")
    assert result["turn"]["accepted"] is True

    perm_lines = [l for l in _growth_lines(service, w) if l["line"] == "permission"]
    assert len(perm_lines) >= 1, f"expected permission growth, got {_growth_lines(service, w)}"
    assert any("gate_pass" in l.get("permission", "") for l in perm_lines)


def test_permission_reflected_in_player_panel() -> None:
    """After grant_permission, player_panel permissions must include the new permission."""
    conn = connect(":memory:")
    init_db(conn)
    with transaction(conn):
        seed_demo_world(conn)
        ActionTemplateStore(conn).upsert(DEMO_WORLD_ID, ActionTemplate(
            action_id="get_inner_city_permit",
            label="获得内城许可",
            target_id=None,
            risk="low",
            reason="test permission panel",
            preconditions=[],
            effects=[{"type": "grant_permission", "entity": "$actor", "permission": "enter_inner_city", "actor": "mayor"}],
        ))

    service = GameWorldService(conn)
    w = DEMO_WORLD_ID
    service.play_turn(w, "获得许可", selected_action_id="get_inner_city_permit")

    from game_world_kg.playable_turn import PlayableTurnKernel
    panel = PlayableTurnKernel(service).player_panel(w)
    assert "enter_inner_city" in panel["permissions"], f"permissions should contain enter_inner_city: {panel['permissions']}"


# ── multi-line growth ────────────────────────────────────────────────


def test_multi_line_growth_in_single_action() -> None:
    """A single action can produce multiple growth lines (relationship + skill + knowledge)."""
    service = _service()
    w = DEMO_WORLD_ID

    # show_pass_token produces CHANGE_RELATION (relationship) and matches "show" → no skill match
    # But bribe_guard produces CHANGE_RELATION + delta_resource + matches "bribe" → skill.social
    result = service.play_turn(w, "贿赂守卫", selected_action_id="bribe_guard", selected_target_id="guard_alos")
    assert result["turn"]["accepted"] is True

    lines = _growth_lines(service, w)
    line_types = {l["line"] for l in lines}
    # bribe_guard: relationship (CHANGE_RELATION trust+1) + skill (bribe → social)
    assert "relationship" in line_types, f"expected relationship in {line_types}"
    assert "skill" in line_types, f"expected skill in {line_types}"


def test_growth_event_recorded_with_action_id() -> None:
    """PLAYER_GROWTH event payload must include the triggering action_id."""
    service = _service()
    w = DEMO_WORLD_ID

    service.play_turn(w, "出示通行令", selected_action_id="show_pass_token", selected_target_id="guard_alos")

    events = _growth_events(service, w)
    assert len(events) >= 1
    assert events[0]["payload"]["action_id"] == "show_pass_token"


def test_rejected_action_produces_no_growth() -> None:
    """A rejected action must NOT produce PLAYER_GROWTH events."""
    service = _service()
    w = DEMO_WORLD_ID

    growth_before = len(_growth_events(service, w))

    result = service.play_turn(w, "我用钥匙打开铁门", selected_action_id="unlock_gate_with_key", selected_target_id="iron_gate")
    assert result["turn"]["accepted"] is False

    growth_after = len(_growth_events(service, w))
    assert growth_after == growth_before, "rejected action should not produce growth events"
