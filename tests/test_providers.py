"""프로바이더 선택과 요청 변환. 네트워크 호출 없음."""
from pathlib import Path

import pytest

from app import config
from app.providers import LLMRefused, get_provider, image_part, text_part


@pytest.fixture
def jpg(tmp_path) -> Path:
    from PIL import Image
    p = tmp_path / "s.jpg"
    Image.new("RGB", (40, 40), "white").save(p, "JPEG")
    return p


def test_get_provider_by_name(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    assert get_provider("anthropic").name == "anthropic"
    assert get_provider("gemini").name == "gemini"
    with pytest.raises(ValueError):
        get_provider("openai")


def test_anthropic_blocks(jpg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from app.providers.anthropic_provider import AnthropicProvider
    p = AnthropicProvider()
    kw = p._kwargs("SYS", [text_part("[슬라이스 1/1]"), image_part(jpg)])
    blocks = kw["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "[슬라이스 1/1]"}
    assert blocks[1]["source"]["media_type"] == "image/jpeg" and blocks[1]["source"]["type"] == "base64"
    assert kw["system"] == "SYS" and kw["max_tokens"] == config.LLM_MAX_TOKENS
    assert "temperature" not in kw  # 현행 모델은 거부


def test_gemini_contents_and_config(jpg, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    from google.genai import types
    from app.providers.gemini_provider import GeminiProvider
    p = GeminiProvider()
    contents = p._to_contents([text_part("t"), image_part(jpg)])
    assert contents[0].text == "t"
    assert contents[1].inline_data.mime_type == "image/jpeg" and contents[1].inline_data.data
    cfg = p._config("SYS")
    assert isinstance(cfg, types.GenerateContentConfig)
    assert cfg.system_instruction == "SYS"
    assert cfg.temperature == 0.0
    assert cfg.response_mime_type == "application/json"
    assert cfg.max_output_tokens == config.LLM_MAX_TOKENS


def test_gemini_refusal_mapping(jpg, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    from google.genai import types
    from app.providers.gemini_provider import GeminiProvider

    class FakeModels:
        def __init__(self, resp): self.resp = resp
        def generate_content(self, **kw): return self.resp

    class FakeClient:
        def __init__(self, resp): self.models = FakeModels(resp)

    ok = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[types.Part.from_text(text='{"a":1}')]), finish_reason=types.FinishReason.STOP)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=5))
    text, usage = GeminiProvider(FakeClient(ok)).call("s", [text_part("x")])
    assert text == '{"a":1}' and usage.input_tokens == 10 and usage.output_tokens == 5

    cut = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[types.Part.from_text(text='{"a"')]), finish_reason=types.FinishReason.MAX_TOKENS)])
    with pytest.raises(LLMRefused):
        GeminiProvider(FakeClient(cut)).call("s", [text_part("x")])

    blocked = types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY))
    with pytest.raises(LLMRefused):
        GeminiProvider(FakeClient(blocked)).call("s", [text_part("x")])


def test_gemini_retries_with_double_tokens_when_truncated(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(config, "LLM_MAX_TOKENS", 8000)
    from google.genai import types
    from app.providers.gemini_provider import GeminiProvider
    seen = []

    class FakeModels:
        def generate_content(self, **kw):
            seen.append(kw["config"].max_output_tokens)
            fr = types.FinishReason.MAX_TOKENS if len(seen) == 1 else types.FinishReason.STOP
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(parts=[types.Part.from_text(text='{"a":1}')]), finish_reason=fr)])

    class FakeClient:
        models = FakeModels()

    text, _ = GeminiProvider(FakeClient()).call("s", [text_part("x")])
    assert text == '{"a":1}' and seen == [8000, 16000]


def test_gemini_gives_up_after_second_truncation(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(config, "LLM_MAX_TOKENS", 8000)
    from google.genai import types
    from app.providers.gemini_provider import GeminiProvider

    class FakeModels:
        def generate_content(self, **kw):
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(parts=[types.Part.from_text(text='{"a"')]), finish_reason=types.FinishReason.MAX_TOKENS)])

    class FakeClient:
        models = FakeModels()

    with pytest.raises(LLMRefused) as ei:
        GeminiProvider(FakeClient()).call("s", [text_part("x")])
    assert "16000" in str(ei.value) and "LLM_MAX_TOKENS" in str(ei.value)
