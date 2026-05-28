from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: Path = Path(".data/game_world_kg.sqlite3")
    kuzu_path: Path = Path(".data/kuzu")
    chroma_path: Path = Path(".data/chroma")

    @classmethod
    def from_env(cls) -> "StorageConfig":
        load_dotenv()
        return cls(
            sqlite_path=Path(os.getenv("GAME_WORLD_KG_DB", ".data/game_world_kg.sqlite3")),
            kuzu_path=Path(os.getenv("GAME_WORLD_KG_KUZU_PATH", ".data/kuzu")),
            chroma_path=Path(os.getenv("GAME_WORLD_KG_CHROMA_PATH", ".data/chroma")),
        )

    def ensure_dirs(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.kuzu_path.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "mock"
    base_url: str = "http://localhost:5001/v1"
    model: str = "bge-m3"
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        load_dotenv()
        return cls(
            provider=os.getenv("GAME_WORLD_KG_EMBEDDING_PROVIDER", "mock"),
            base_url=os.getenv("GAME_WORLD_KG_EMBEDDING_BASE_URL", "http://localhost:5001/v1").rstrip("/"),
            model=os.getenv("GAME_WORLD_KG_EMBEDDING_MODEL", "bge-m3"),
            api_key=os.getenv("GAME_WORLD_KG_EMBEDDING_API_KEY", ""),
        )


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "anthropic"
    base_url: str = "https://api.anthropic.com/v1"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    timeout_seconds: float = 30.0
    worldgen_timeout_seconds: float = 180.0
    max_tokens: int = 4096
    anthropic_version: str = "2023-06-01"
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv()
        timeout_seconds = float(os.getenv("GAME_WORLD_KG_LLM_TIMEOUT", "30"))
        return cls(
            provider=os.getenv("GAME_WORLD_KG_LLM_PROVIDER", "anthropic").lower(),
            base_url=os.getenv("GAME_WORLD_KG_LLM_BASE_URL", "https://api.anthropic.com/v1").rstrip("/"),
            model=os.getenv("GAME_WORLD_KG_LLM_MODEL", "claude-sonnet-4-20250514"),
            api_key=os.getenv("GAME_WORLD_KG_LLM_API_KEY", ""),
            timeout_seconds=timeout_seconds,
            worldgen_timeout_seconds=float(os.getenv("GAME_WORLD_KG_WORLDGEN_LLM_TIMEOUT", str(timeout_seconds * 6))),
            max_tokens=int(os.getenv("GAME_WORLD_KG_LLM_MAX_TOKENS", "4096")),
            anthropic_version=os.getenv("GAME_WORLD_KG_ANTHROPIC_VERSION", "2023-06-01"),
            enabled=os.getenv("GAME_WORLD_KG_LLM_ENABLED", "1") not in {"0", "false", "False"},
        )


@dataclass(frozen=True)
class JsonRepairConfig:
    enabled: bool = False
    mode: str = "localized"
    provider: str = "openai_compatible"
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = "EMPTY"
    model: str = "qwen2.5-coder-7b-instruct"
    timeout_seconds: float = 20.0
    temperature: float = 0.0
    max_tokens: int = 4096
    max_attempts: int = 2
    window_lines: int = 8

    @classmethod
    def from_env(cls) -> "JsonRepairConfig":
        load_dotenv()
        return cls(
            enabled=os.getenv("WORLDGEN_JSON_REPAIR_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            mode=os.getenv("WORLDGEN_JSON_REPAIR_MODE", "localized"),
            provider=os.getenv("WORLDGEN_JSON_REPAIR_PROVIDER", "openai_compatible").lower(),
            base_url=os.getenv("WORLDGEN_JSON_REPAIR_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
            api_key=os.getenv("WORLDGEN_JSON_REPAIR_API_KEY", "EMPTY"),
            model=os.getenv("WORLDGEN_JSON_REPAIR_MODEL", "qwen2.5-coder-7b-instruct"),
            timeout_seconds=float(os.getenv("WORLDGEN_JSON_REPAIR_TIMEOUT_SECONDS", "20")),
            temperature=float(os.getenv("WORLDGEN_JSON_REPAIR_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("WORLDGEN_JSON_REPAIR_MAX_TOKENS", "4096")),
            max_attempts=int(os.getenv("WORLDGEN_JSON_REPAIR_MAX_ATTEMPTS", "2")),
            window_lines=int(os.getenv("WORLDGEN_JSON_REPAIR_WINDOW_LINES", "8")),
        )

    def to_llm_config(self) -> LLMConfig:
        return LLMConfig(
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            worldgen_timeout_seconds=self.timeout_seconds,
            max_tokens=self.max_tokens,
            enabled=self.enabled,
        )
