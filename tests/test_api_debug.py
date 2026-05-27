from __future__ import annotations

from game_world_kg.api import create_app


def test_debug_panel_html_file_contains_expected_mount_points() -> None:
    app = create_app(":memory:")
    route_paths = {route.path for route in app.routes}

    assert "/debug" in route_paths
    assert "/evaluation" in route_paths


def test_debug_panel_file_references_core_endpoints() -> None:
    from game_world_kg.api import DEBUG_HTML_PATH

    html = DEBUG_HTML_PATH.read_text(encoding="utf-8")

    assert "Game World KG Debug" in html
    assert "/worlds/${id}/state" in html
    assert "/worlds/${id}/events" in html
    assert "/worlds/${id}/quests" in html
    assert "/worlds/${id}/tensions" in html
    assert "/worlds/${id}/play/state" in html
    assert "/worlds/${id}/play/turn" in html
    assert "document.getElementById(\"worldId\").value = data.generatedWorldSpec.world_id" not in html
    assert "/worlds/${id}/projectors/status" in html
    assert "/worlds/${id}/explain/state/${entity}/${attr" in html
    assert "/evaluation" in html


def test_projection_status_endpoint_is_available() -> None:
    from fastapi.testclient import TestClient

    response = TestClient(create_app(":memory:")).get("/worlds/demo_village/projectors/status")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
