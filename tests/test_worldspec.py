from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db
from game_world_kg.service import GameWorldService
from game_world_kg.worldspec import WorldIntentExtractor, WorldSpecValidator, sample_world_spec


def test_sample_worldspecs_validate() -> None:
    for genre in ["cultivation", "ocean", "village"]:
        spec = sample_world_spec(genre)
        report = WorldSpecValidator().validate(spec)

        assert report["valid"] is True


def test_validator_rejects_dangling_reference_and_disconnected_map() -> None:
    spec = sample_world_spec("cultivation").model_dump(mode="json")
    spec["characters"][0]["start_location"] = "missing_place"
    spec["locations"][-1]["connects_to"] = []
    spec["locations"][1]["connects_to"].remove("well_square")

    report = WorldSpecValidator().validate(spec)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["valid"] is False
    assert "dangling_ref" in codes
    assert "map_disconnected" in codes


def test_validator_rejects_unsupported_action_effect() -> None:
    spec = sample_world_spec("cultivation").model_dump(mode="json")
    spec["action_templates"][0]["effects"].append({"type": "free_text_magic"})

    report = WorldSpecValidator().validate(spec)

    assert report["valid"] is False
    assert any(issue["code"] == "unsupported_effect" for issue in report["issues"])


def test_worldspec_bootstrap_runtime_tick_and_evaluation() -> None:
    conn = connect(":memory:")
    init_db(conn)
    service = GameWorldService(conn)

    generated = service.generate_worldspec("我想玩一个修仙小镇，主角刚入外门，后山妖兽异常。")
    bootstrap = service.bootstrap_worldspec(generated["spec"])
    world_id = generated["world_id"]

    assert generated["validation_report"]["valid"] is True
    assert bootstrap["accepted"] is True
    assert len(service.affordances(world_id)) >= 5
    assert service.tick_world(world_id)["npc_count"] >= 1
    assert service.worldgen_evaluation(world_id)["quest_traceability_rate"] == 1.0


def test_worldspec_api_routes() -> None:
    client = TestClient(create_app(":memory:"))

    generated = client.post("/v1/worldspec/generate", json={"idea": "修仙小镇，后山妖兽异常"}).json()
    validation = client.post("/v1/worldspec/validate", json={"spec": generated["spec"]}).json()
    bootstrap = client.post("/v1/worldspec/bootstrap", json={"spec": generated["spec"]}).json()
    world_id = generated["world_id"]

    assert validation["valid"] is True
    assert bootstrap["accepted"] is True
    assert client.get(f"/worlds/{world_id}/worldspec").status_code == 200
    assert client.post(f"/worlds/{world_id}/tick").json()["npc_count"] >= 1
    assert client.get(f"/worlds/{world_id}/drama/foreground").json()["foreground_tensions"]


def test_intent_does_not_prime_llm_with_fixed_title() -> None:
    intent = WorldIntentExtractor().extract("我想玩一个青楼小世界，玩家想脱身")

    assert "title" not in intent
    assert intent["title_hint"] != "边村铁门风波"


def test_sample_fallback_title_comes_from_idea() -> None:
    spec = sample_world_spec("village", "我想玩一个青楼小世界，玩家想脱身")

    assert spec.title == "花楼旧梦"


def test_chinese_ideas_get_distinct_world_ids() -> None:
    first = sample_world_spec("village", "我想玩一个青楼小世界，玩家想脱身")
    second = sample_world_spec("village", "我想玩一个边境驿站，玩家是密探")

    assert first.world_id.startswith("demo_border_village_")
    assert second.world_id.startswith("demo_border_village_")
    assert first.world_id != second.world_id
