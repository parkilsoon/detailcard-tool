"""Google Gemini API (google-genai SDK)."""
from __future__ import annotations

import logging
import os
import random
import time

import httpx
from google import genai
from google.genai import errors, types

from app import config
from app.providers import LLMRefused, Usage


# 도구를 쓰지 않는데도 SDK 가 매 호출마다 AFC 권고 경고를 찍는다. 잡음이라 끈다.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: genai.Client | None = None):
        self.model = config.LLM_MODEL
        self._client = client or genai.Client(
            api_key=config.GEMINI_API_KEY or None,  # 비우면 SDK 가 GEMINI_API_KEY/GOOGLE_API_KEY env 를 읽는다
            http_options=types.HttpOptions(
                timeout=600_000,  # ms
                # 5xx / 429 지수 백오프 3회
                retry_options=types.HttpRetryOptions(attempts=4, initial_delay=1.0, max_delay=30.0,
                                                     http_status_codes=[429, 500, 502, 503, 504]),
            ),
        )

    @staticmethod
    def _to_contents(parts: list[dict]) -> list:
        out = []
        for p in parts:
            if p["type"] == "text":
                out.append(types.Part.from_text(text=p["text"]))
            else:
                out.append(types.Part.from_bytes(data=p["path"].read_bytes(), mime_type=p["media_type"]))
        return out

    @staticmethod
    def _config(system: str, max_tokens: int | None = None) -> types.GenerateContentConfig:
        temp = os.getenv("LLM_TEMPERATURE", "").strip()
        kw: dict = dict(
            system_instruction=system,
            temperature=float(temp) if temp else 0.0,   # 전사에 창의성 불필요
            max_output_tokens=max_tokens or config.LLM_MAX_TOKENS,
            response_mime_type="application/json",     # JSON 만 출력
        )
        budget = os.getenv("LLM_THINKING_BUDGET", "").strip()
        if budget:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=int(budget))
        res = os.getenv("LLM_MEDIA_RESOLUTION", "").strip().upper()
        if res:
            kw["media_resolution"] = getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{res}")
        return types.GenerateContentConfig(**kw)

    _TRANSIENT = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError,
                  httpx.ReadTimeout, httpx.WriteError, errors.ServerError)

    def _generate(self, contents, config):
        """상태코드 재시도는 SDK 가 하지만, 서버가 응답 없이 연결을 끊는 경우는 여기서 지수 백오프 3회."""
        last: Exception | None = None
        for attempt in range(4):
            try:
                return self._client.models.generate_content(model=self.model, contents=contents, config=config)
            except self._TRANSIENT as e:
                last = e
                if attempt == 3:
                    break
                time.sleep(min(30.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1))
        raise LLMRefused(f"API 연결 오류 (재시도 후): {type(last).__name__}: {last}")

    MAX_TOKENS_CAP = 65536

    def call(self, system: str, parts: list[dict]) -> tuple[str, Usage]:
        contents = self._to_contents(parts)
        limit = config.LLM_MAX_TOKENS
        for attempt in range(2):
            resp = self._generate(contents, self._config(system, limit))
            if resp.prompt_feedback and resp.prompt_feedback.block_reason:
                raise LLMRefused(f"모델이 요청을 차단했습니다: {resp.prompt_feedback.block_reason}")
            if not resp.candidates:
                raise LLMRefused("모델이 응답을 돌려주지 않았습니다.")
            fr = resp.candidates[0].finish_reason
            if fr == types.FinishReason.MAX_TOKENS and attempt == 0 and limit < self.MAX_TOKENS_CAP:
                # Gemini 는 thinking 토큰도 이 한도에 포함된다. 잘리면 한도를 두 배로 올려 한 번 더.
                limit = min(limit * 2, self.MAX_TOKENS_CAP)
                logging.getLogger("detailcard").warning("output truncated at %s tokens; retrying with %s", config.LLM_MAX_TOKENS, limit)
                continue
            break
        if fr == types.FinishReason.MAX_TOKENS:
            raise LLMRefused(f"응답이 너무 길어 잘렸습니다 (max_output_tokens {limit}). .env 의 LLM_MAX_TOKENS 를 올려 주세요.")
        if fr in (types.FinishReason.SAFETY, types.FinishReason.RECITATION, types.FinishReason.BLOCKLIST):
            raise LLMRefused(f"모델이 응답을 거부했습니다: {fr}")
        text = resp.text or ""
        um = resp.usage_metadata
        return text, Usage(int((um and um.prompt_token_count) or 0),
                           int((um and um.candidates_token_count) or 0))
