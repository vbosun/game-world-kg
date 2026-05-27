from __future__ import annotations

import os
from pathlib import Path

from game_world_kg.config import LLMConfig, load_dotenv


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
