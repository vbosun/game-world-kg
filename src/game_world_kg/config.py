from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://localhost:5001/v1"
    model: str = "qwen3"
    api_key: str = ""
    timeout_seconds: float = 30.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.getenv("GAME_WORLD_KG_LLM_BASE_URL", "http://localhost:5001/v1").rstrip("/"),
            model=os.getenv("GAME_WORLD_KG_LLM_MODEL", "qwen3"),
            api_key=os.getenv("GAME_WORLD_KG_LLM_API_KEY", ""),
            timeout_seconds=float(os.getenv("GAME_WORLD_KG_LLM_TIMEOUT", "30")),
            enabled=os.getenv("GAME_WORLD_KG_LLM_ENABLED", "1") not in {"0", "false", "False"},
        )
