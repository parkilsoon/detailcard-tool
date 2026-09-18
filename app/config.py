"""환경변수 로딩. 코드에 상수를 박지 않고 여기서만 읽는다."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", ROOT / "storage"))
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data.db"))
PROMPTS_DIR = ROOT / "prompts"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

# ---------- LLM 프로바이더 ----------
# anthropic | gemini
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()

_DEFAULTS = {
    #            모델                 최대 장변  비주얼 토큰  슬라이스 높이(None=공식 계산)
    "anthropic": ("claude-opus-5",    1568,      1568,        None),
    "gemini":    ("gemini-2.5-pro",   3072,      0,           768),   # 768px 타일 1단. 골든 A/B 에서 1536 대비 오류 3→1
}
if LLM_PROVIDER not in _DEFAULTS:
    raise RuntimeError(f"LLM_PROVIDER 는 anthropic 또는 gemini 여야 합니다: {LLM_PROVIDER!r}")
_m, _edge, _tok, _sh = _DEFAULTS[LLM_PROVIDER]

LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or _m
LLM_MAX_LONG_EDGE = int(os.getenv("LLM_MAX_LONG_EDGE") or _edge)
LLM_MAX_VISUAL_TOKENS = int(os.getenv("LLM_MAX_VISUAL_TOKENS") or _tok)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS") or 16000)  # Gemini 는 thinking 토큰도 이 한도에 포함된다
# 슬라이스 높이 직접 지정 (px). 비우면 프로바이더별 기본 규칙
SLICE_HEIGHT = int(os.getenv("SLICE_HEIGHT") or 0) or _sh
# 검증 방식: lines = 이미지의 모든 문구를 한 줄씩 나열시켜 누락·불일치를 대조 (기본) / structured = 2차 구조화 전사 diff
VERIFY_MODE = os.getenv("VERIFY_MODE", "lines").strip().lower()
# 검증(2차 전사)용 슬라이스 높이. 1차와 다르게 잘라 시야를 바꾼다. 비우면 1차의 2배 (anthropic 은 공식값의 2배)
VERIFY_SLICE_HEIGHT = int(os.getenv("VERIFY_SLICE_HEIGHT") or 0) or (SLICE_HEIGHT * 2 if SLICE_HEIGHT else None)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 동시에 처리할 카드 수 (다중 등록). API 속도 제한을 고려해 기본 3
PIPELINE_WORKERS = int(os.getenv("PIPELINE_WORKERS") or 3)
BATCH_MAX_FILES = int(os.getenv("BATCH_MAX_FILES") or 50)

SLICE_OVERLAP_RATIO = 0.15
SLICE_MAX_COUNT = 8
SLICE_JPEG_QUALITY = 92

FIELD_MAX_LEN = 4000
UNREADABLE = "___UNREADABLE___"

EXTRACT_PROMPT_VERSION = "extract-v2"
LINES_PROMPT_VERSION = "lines-v1"
TEMPLATE_VERSION = "card-v2"
