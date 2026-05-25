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
class LLMConfig:
    base_url: str = "http://localhost:5001/v1"
    model: str = "qwen3"
    api_key: str = ""
    timeout_seconds: float = 30.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv()
        return cls(
            base_url=os.getenv("GAME_WORLD_KG_LLM_BASE_URL", "http://localhost:5001/v1").rstrip("/"),
            model=os.getenv("GAME_WORLD_KG_LLM_MODEL", "qwen3"),
            api_key=os.getenv("GAME_WORLD_KG_LLM_API_KEY", ""),
            timeout_seconds=float(os.getenv("GAME_WORLD_KG_LLM_TIMEOUT", "30")),
            enabled=os.getenv("GAME_WORLD_KG_LLM_ENABLED", "1") not in {"0", "false", "False"},
        )
