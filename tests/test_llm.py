from __future__ import annotations

import json
import urllib.request

from game_world_kg.llm import AnthropicClient, OpenAICompatibleClient, _to_anthropic_messages, build_llm_client_from_env
from game_world_kg.config import LLMConfig


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"content": [{"type": "text", "text": "hello"}]}).encode("utf-8")


def test_build_llm_client_defaults_to_anthropic(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_ENABLED", raising=False)
    monkeypatch.setenv("GAME_WORLD_KG_LLM_API_KEY", "secret")

    assert isinstance(build_llm_client_from_env(), AnthropicClient)


def test_build_llm_client_disables_anthropic_without_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GAME_WORLD_KG_LLM_API_KEY", raising=False)

    assert build_llm_client_from_env() is None


def test_build_llm_client_supports_openai_compatible(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GAME_WORLD_KG_LLM_PROVIDER", "openai_compatible")

    assert isinstance(build_llm_client_from_env(), OpenAICompatibleClient)


def test_build_llm_client_can_be_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GAME_WORLD_KG_LLM_ENABLED", "0")

    assert build_llm_client_from_env() is None


def test_to_anthropic_messages_splits_system_and_merges_roles() -> None:
    system, messages = _to_anthropic_messages(
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "one"},
            {"role": "tool", "content": "two"},
            {"role": "assistant", "content": "three"},
        ]
    )

    assert system == "rules"
    assert messages == [
        {"role": "user", "content": "one\n\ntwo"},
        {"role": "assistant", "content": "three"},
    ]


def test_anthropic_client_posts_messages_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = AnthropicClient(
        LLMConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-test",
            api_key="secret",
            timeout_seconds=30,
            worldgen_timeout_seconds=180,
            max_tokens=123,
            anthropic_version="2023-06-01",
        )
    )

    text = client.complete_text(
        [
            {"role": "system", "content": "strict"},
            {"role": "user", "content": "say hello"},
        ],
        temperature=0.2,
        timeout_seconds=77,
    )

    assert text == "hello"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["timeout"] == 77
    assert captured["body"] == {
        "model": "claude-test",
        "messages": [{"role": "user", "content": "say hello"}],
        "max_tokens": 123,
        "temperature": 0.2,
        "system": "strict",
    }
