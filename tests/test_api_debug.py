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
    assert "/evaluation" in html
