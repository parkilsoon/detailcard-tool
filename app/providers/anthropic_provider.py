"""Anthropic Messages API (anthropic SDK)."""
from __future__ import annotations

import base64
import os
from typing import Any

import anthropic

from app import config
from app.providers import LLMRefused, Usage


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.model = config.LLM_MODEL
        # 5xx / 429 에 지수 백오프 3회 (SDK 내장)
        self._client = client or anthropic.Anthropic(max_retries=3)

    @staticmethod
    def _to_blocks(parts: list[dict]) -> list[dict]:
        blocks = []
        for p in parts:
            if p["type"] == "text":
                blocks.append({"type": "text", "text": p["text"]})
            else:
                data = base64.standard_b64encode(p["path"].read_bytes()).decode("ascii")
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": p["media_type"], "data": data}})
        return blocks

    def _kwargs(self, system: str, parts: list[dict], max_tokens: int | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": self._to_blocks(parts)}],
        )
        effort = os.getenv("LLM_EFFORT", "").strip()
        if effort:
            kwargs["output_config"] = {"effort": effort}
        # 현행 모델(Opus 5 등)은 temperature 를 거부한다. 구형 모델에서만 환경변수로 켠다.
        temp = os.getenv("LLM_TEMPERATURE", "").strip()
        if temp:
            kwargs["extra_body"] = {"temperature": float(temp)}
        fallbacks = os.getenv("LLM_FALLBACKS", "default").strip()
        if fallbacks and fallbacks.lower() != "off":
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = fallbacks
        return kwargs

    MAX_TOKENS_CAP = 64000

    def call(self, system: str, parts: list[dict]) -> tuple[str, Usage]:
        limit = config.LLM_MAX_TOKENS
        for attempt in range(2):
            kwargs = self._kwargs(system, parts, limit)
            api = self._client.beta.messages if "betas" in kwargs else self._client.messages
            with api.stream(**kwargs) as stream:  # 긴 출력 대비 스트리밍
                msg = stream.get_final_message()
            if msg.stop_reason == "max_tokens" and attempt == 0 and limit < self.MAX_TOKENS_CAP:
                limit = min(limit * 2, self.MAX_TOKENS_CAP)   # 잘리면 한도를 두 배로 올려 한 번 더
                continue
            break
        if msg.stop_reason == "refusal":
            raise LLMRefused("모델이 응답을 거부했습니다.")
        if msg.stop_reason == "max_tokens":
            raise LLMRefused(f"응답이 너무 길어 잘렸습니다 (max_tokens {limit}). .env 의 LLM_MAX_TOKENS 를 올려 주세요.")
        text = "".join(b.text for b in msg.content if b.type == "text")
        return text, Usage(msg.usage.input_tokens, msg.usage.output_tokens)
