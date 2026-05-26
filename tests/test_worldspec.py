from __future__ import annotations

from fastapi.testclient import TestClient

from game_world_kg.api import create_app
from game_world_kg.db import connect, init_db
from game_world_kg.service import GameWorldService
from game_world_kg.worldspec import WorldSpecValidator, sample_world_spec


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
