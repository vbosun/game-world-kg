from __future__ import annotations

import os
from pathlib import Path

from game_world_kg.config import JsonRepairConfig, LLMConfig, load_dotenv


def test_load_dotenv_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GAME_WORLD_KG_LLM_BASE_URL=http://localhost:5001/v1\n"
        "GAME_WORLD_KG_LLM_MODEL='qwen3-local'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GAME_WORLD_KG_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_MODEL", raising=False)

    load_dotenv(env_file)

    assert os.environ["GAME_WORLD_KG_LLM_BASE_URL"] == "http://localhost:5001/v1"
    assert os.environ["GAME_WORLD_KG_LLM_MODEL"] == "qwen3-local"


def test_load_dotenv_does_not_override_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GAME_WORLD_KG_LLM_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("GAME_WORLD_KG_LLM_MODEL", "from-env")

    load_dotenv(env_file)

    assert os.environ["GAME_WORLD_KG_LLM_MODEL"] == "from-env"


def test_llm_worldgen_timeout_defaults_longer_than_regular_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_WORLDGEN_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_MODEL", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_ANTHROPIC_VERSION", raising=False)

    config = LLMConfig.from_env()

    assert config.provider == "anthropic"
    assert config.base_url == "https://api.anthropic.com/v1"
    assert config.model == "claude-sonnet-4-20250514"
    assert config.timeout_seconds == 30.0
    assert config.worldgen_timeout_seconds == 180.0
    assert config.max_tokens == 4096
    assert config.anthropic_version == "2023-06-01"


def test_llm_worldgen_timeout_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("GAME_WORLD_KG_LLM_TIMEOUT", "45")
    monkeypatch.setenv("GAME_WORLD_KG_WORLDGEN_LLM_TIMEOUT", "240")
    monkeypatch.setenv("GAME_WORLD_KG_LLM_PROVIDER", "OPENAI_COMPATIBLE")
    monkeypatch.setenv("GAME_WORLD_KG_LLM_MAX_TOKENS", "8192")

    config = LLMConfig.from_env()

    assert config.provider == "openai_compatible"
    assert config.timeout_seconds == 45.0
    assert config.worldgen_timeout_seconds == 240.0
    assert config.max_tokens == 8192


def test_json_repair_config_defaults_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in [
        "WORLDGEN_JSON_REPAIR_ENABLED",
        "WORLDGEN_JSON_REPAIR_MODE",
        "WORLDGEN_JSON_REPAIR_PROVIDER",
        "WORLDGEN_JSON_REPAIR_BASE_URL",
        "WORLDGEN_JSON_REPAIR_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = JsonRepairConfig.from_env()

    assert config.enabled is False
    assert config.mode == "localized"
    assert config.provider == "openai_compatible"
    assert config.temperature == 0
    assert config.max_attempts == 2
    assert config.window_lines == 8


def test_json_repair_config_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_ENABLED", "true")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_PROVIDER", "openai_compatible")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_MODEL", "qwen-coder")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_MAX_TOKENS", "2048")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("WORLDGEN_JSON_REPAIR_WINDOW_LINES", "5")

    config = JsonRepairConfig.from_env()
    llm_config = config.to_llm_config()

    assert config.enabled is True
    assert config.model == "qwen-coder"
    assert config.timeout_seconds == 11
    assert config.max_tokens == 2048
    assert config.max_attempts == 3
    assert config.window_lines == 5
    assert llm_config.provider == "openai_compatible"
    assert llm_config.base_url == "http://127.0.0.1:8000/v1"
    assert llm_config.max_tokens == 2048
