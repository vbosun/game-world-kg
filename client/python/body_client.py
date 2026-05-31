"""Python client skeleton for AI Body Runtime.

The runtime API is implemented in a later stage. This client defines the target
shape that the Godot runtime should support.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class BodyClient:
    base_url: str = "http://127.0.0.1:17860"
    timeout: float = 30.0

    def action(
        self,
        action: str,
        expression: str = "neutral",
        prop: str = "none",
        gaze: str = "none",
        camera: str = "front_medium",
        screenshot: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "action": action,
            "expression": expression,
            "prop": prop,
            "gaze": gaze,
            "camera": camera,
            "screenshot": screenshot,
        }
        response = requests.post(
            f"{self.base_url}/body/action",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
