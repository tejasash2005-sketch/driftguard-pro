from __future__ import annotations

import sys
import types

import pytest

from driftguard.errors import MissingAPIKeyError, ProviderError
from driftguard.providers import AnthropicProvider, OpenAIProvider, Pricing, get_provider

SECRET = "sk-test-SECRET-1234567890"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DRIFTGUARD_PROVIDER_TIMEOUT", raising=False)


def test_missing_key_errors_do_not_need_sdk() -> None:
    with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY"):
        OpenAIProvider("m").generate("hi")
    with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider("m").generate("hi")


def test_blank_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(MissingAPIKeyError):
        OpenAIProvider("m").generate("hi")


def test_get_provider_and_validation() -> None:
    assert get_provider("openai", "m").name == "openai"
    assert get_provider("anthropic", "m").name == "anthropic"
    with pytest.raises(ProviderError, match="unknown provider"):
        get_provider("nope", "m")
    with pytest.raises(ProviderError):
        OpenAIProvider("")


def test_repr_never_contains_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    assert SECRET not in repr(OpenAIProvider("gpt-x")) and SECRET not in str(
        vars(OpenAIProvider("g"))
    )


def test_pricing() -> None:
    assert Pricing(1.0, 2.0).cost(1_000_000, 500_000) == 2.0


def fake_openai(monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> dict:
    seen: dict = {}

    class Completions:
        def create(self, **kw):
            seen.update(kw)
            if fail:
                raise RuntimeError(f"auth failed for {SECRET}")
            msg = types.SimpleNamespace(content="hello from openai")
            usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)

    class Client:
        def __init__(self, api_key, **settings):
            seen["api_key"] = api_key
            seen.update(settings)
            self.chat = types.SimpleNamespace(completions=Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=Client))
    return seen


def test_openai_adapter_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    seen = fake_openai(monkeypatch)
    resp = OpenAIProvider("gpt-x", Pricing(1.0, 2.0)).generate("hi", max_tokens=7)
    assert (
        resp.text == "hello from openai"
        and resp.prompt_tokens == 10
        and resp.completion_tokens == 5
    )
    assert resp.cost_usd == pytest.approx(20 / 1_000_000) and resp.latency_ms is not None
    assert seen["model"] == "gpt-x" and seen["max_tokens"] == 7 and seen["api_key"] == SECRET
    assert seen["timeout"] == 30 and seen["max_retries"] == 0
    assert SECRET not in resp.model_dump_json()


def test_provider_timeout_is_bounded_and_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    seen = fake_openai(monkeypatch)
    monkeypatch.setenv("DRIFTGUARD_PROVIDER_TIMEOUT", "5.5")
    OpenAIProvider("gpt-x").generate("hi")
    assert seen["timeout"] == 5.5 and seen["max_retries"] == 0
    for value in ("nan", "0", "301", "invalid"):
        monkeypatch.setenv("DRIFTGUARD_PROVIDER_TIMEOUT", value)
        with pytest.raises(ProviderError, match="DRIFTGUARD_PROVIDER_TIMEOUT"):
            OpenAIProvider("gpt-x").generate("hi")


def test_provider_errors_do_not_leak_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    fake_openai(monkeypatch, fail=True)
    with pytest.raises(ProviderError) as info:
        OpenAIProvider("gpt-x").generate("hi")
    assert SECRET not in str(info.value) and "RuntimeError" in str(info.value)


def test_anthropic_adapter_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)

    class Messages:
        def create(self, **kw):
            assert kw["messages"][0]["content"] == "hi"
            blocks = [
                types.SimpleNamespace(type="text", text="part1 "),
                types.SimpleNamespace(type="tool_use"),
                types.SimpleNamespace(type="text", text="part2"),
            ]
            return types.SimpleNamespace(
                content=blocks, usage=types.SimpleNamespace(input_tokens=3, output_tokens=4)
            )

    class Client:
        def __init__(self, api_key, **settings):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    resp = AnthropicProvider("claude-x").generate("hi")
    assert resp.text == "part1 part2" and resp.prompt_tokens == 3 and resp.completion_tokens == 4
    assert resp.cost_usd is None


def test_missing_sdk_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setitem(sys.modules, "openai", None)  # makes `import openai` raise ImportError
    with pytest.raises(ProviderError, match=r"driftguard-pro\[openai\]"):
        OpenAIProvider("m").generate("hi")


def test_anthropic_errors_do_not_leak_and_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)

    class Messages:
        def create(self, **kw):
            raise RuntimeError(f"401 for key {SECRET}")

    class Client:
        def __init__(self, api_key, **settings):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    with pytest.raises(ProviderError) as info:
        AnthropicProvider("m").generate("hi")
    assert SECRET not in str(info.value) and "RuntimeError" in str(info.value)
    assert SECRET not in repr(AnthropicProvider("m"))
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderError, match=r"driftguard-pro\[anthropic\]"):
        AnthropicProvider("m").generate("hi")
    with pytest.raises(ProviderError):
        AnthropicProvider("")
