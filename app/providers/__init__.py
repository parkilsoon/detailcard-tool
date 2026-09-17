"""LLM 프로바이더 추상화. 추출/검증 로직은 프로바이더를 모른다.

parts 표현 (프로바이더 공통):
  {"type": "text",  "text": "..."}
  {"type": "image", "path": Path, "media_type": "image/jpeg"}
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app import config


class LLMRefused(Exception):
    """모델이 응답을 거부/차단했거나 출력이 잘림."""


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str
    model: str

    def call(self, system: str, parts: list[dict]) -> tuple[str, Usage]: ...


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def image_part(path: Path, media_type: str = "image/jpeg") -> dict:
    return {"type": "image", "path": path, "media_type": media_type}


def get_provider(name: str | None = None) -> Provider:
    name = (name or config.LLM_PROVIDER).lower()
    if name == "anthropic":
        from app.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "gemini":
        from app.providers.gemini_provider import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"unknown provider: {name}")
