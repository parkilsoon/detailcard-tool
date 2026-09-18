"""LLM 호출 #1(추출) / #2(검증) + 후처리.

두 호출은 반드시 별도 API 호출이다. 같은 호출 안에서 자기 결과를 검증하게 하지 않는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app import config
from app.paths import iter_strings, path_set
from app.providers import LLMRefused, Provider, get_provider, image_part, text_part
from app.sanitize import strip_disallowed_tags
from app.schema import validate_lines, validate_payload
from app.slicer import SliceInfo, slice_label


class ExtractError(Exception):
    """사용자에게 보여줄 실패. str(e) 는 한국어 안내문, detail 은 기술 정보, unsupported_kinds 는 모델이 지어낸 형식 이름."""

    def __init__(self, message: str, detail: str | None = None, unsupported_kinds: list[str] | None = None):
        super().__init__(message)
        self.detail = detail
        self.unsupported_kinds = unsupported_kinds or []


_KNOWN_KINDS = {"spec_table", "variants", "callouts", "icd", "points", "notice", "text_box", "table"}


def _unsupported_kinds(raw: dict) -> list[str]:
    out = []
    for s in raw.get("sections") or []:
        if isinstance(s, dict):
            k = s.get("kind")
            if isinstance(k, str) and k not in _KNOWN_KINDS and k not in out:
                out.append(k)
    return out


@dataclass
class LLMResult:
    data: dict
    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int


# ---------- 프롬프트 ----------

def load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8")


# ---------- 요청 구성 ----------

def build_slice_content(slices: list[SliceInfo]) -> list[dict]:
    """한 요청에 모든 슬라이스를 순서대로. 각 이미지 앞에 라벨 text 블록."""
    parts: list[dict] = []
    total = len(slices)
    for s in slices:
        parts.append(text_part(slice_label(s, total)))
        parts.append(image_part(s.path, "image/jpeg"))
    return parts


# ---------- 호출 ----------

def call_llm(system: str, parts: list[dict], provider: Provider | None = None) -> tuple[str, object]:
    """프로바이더(.env 의 LLM_PROVIDER)에 위임. 거부/잘림은 ExtractError 로 변환."""
    provider = provider or get_provider()
    try:
        return provider.call(system, parts)
    except LLMRefused as e:
        raise ExtractError(str(e)) from e


# ---------- 후처리 ----------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?\s*```\s*$", re.IGNORECASE)


def strip_code_fence(text: str) -> str:
    t = text.strip()
    t = _FENCE_RE.sub("", t)
    return t.strip()


def parse_json(text: str) -> dict:
    t = strip_code_fence(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # 앞뒤 잡음이 있으면 첫 { 부터 마지막 } 까지 시도
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            return json.loads(t[s:e + 1])
        raise


def postprocess_extract(raw: dict) -> dict:
    """1) 태그 화이트리스트 2) 길이 상한 3) pydantic 4) UNREADABLE 수거 → 정규화된 dict."""
    # 1, 2
    for path, val in list(iter_strings(raw)):
        cleaned = re.sub(r"\s*\n\s*", " ", strip_disallowed_tags(val)).strip()  # 문자열 안 줄바꿈은 공백으로
        if len(cleaned) > config.FIELD_MAX_LEN:
            raise ExtractError(f"필드 길이 초과 ({len(cleaned)}자): {path}")
        if cleaned != val:
            path_set(raw, path, cleaned)
    # 3
    try:
        payload = validate_payload(raw)
    except ValidationError as e:
        first = e.errors()[0]
        detail = f"{'.'.join(str(x) for x in first.get('loc', ()))}: {first.get('msg')}"
        bad = _unsupported_kinds(raw)
        if bad:
            raise ExtractError(
                f"이 카드에는 아직 지원하지 않는 형식의 블록이 있습니다 (모델이 제안한 형식: {', '.join(bad)}). "
                "개발팀에 이 카드를 전달해 주세요.", detail=detail, unsupported_kinds=bad) from e
        raise ExtractError("추출 결과가 정해진 형식과 맞지 않습니다. 다시 시도해 주세요.", detail=detail) from e
    data = payload.model_dump(mode="json")
    # 4
    uncertain = list(dict.fromkeys(data.get("uncertain") or []))
    for path, val in iter_strings({k: v for k, v in data.items() if k != "uncertain"}):
        if config.UNREADABLE in val and path not in uncertain:
            uncertain.append(path)
    data["uncertain"] = uncertain
    return data


def postprocess_lines(raw: dict) -> dict:
    try:
        data = validate_lines(raw).model_dump(mode="json")
    except ValidationError as e:
        raise ExtractError(f"문구 목록 스키마 오류: {e.errors()[0].get('msg')}") from e
    data["lines"] = [strip_disallowed_tags(l).strip() for l in data["lines"] if l and l.strip()]
    return data


# ---------- 제품명 정규화 ----------

# 여러 제형을 묶은 배지 (붙이면 이름이 이상해지는 것들)
_COMPOUND_FORM = re.compile(r"[·/,+&\s]|패밀리|\d+제형|라인업")


def normalize_product_name(payload: dict) -> dict:
    """제품명에 단일 제형을 붙인다. "구세" + "정" → "구세정". form 은 그대로 둔다.
    "정·서방정", "패밀리", "3제형" 같은 복합 배지는 붙이지 않는다. 이미 붙어 있으면 그대로."""
    from app.sanitize import plain_text
    h = payload.get("header") or {}
    name = plain_text(h.get("product_name")).strip()
    form = plain_text(h.get("form")).strip()
    if name and form and not _COMPOUND_FORM.search(form) and not name.endswith(form):
        h["product_name"] = name + form
    return payload


# ---------- 파이프라인 ----------

def _call_and_parse(system: str, content: list[dict], post, provider: Provider | None = None) -> LLMResult:
    """JSON 파싱/스키마 실패는 1회만 재시도."""
    last: Exception | None = None
    model = provider.model if provider else config.LLM_MODEL
    for attempt in range(2):
        text, usage = call_llm(system, content, provider)
        try:
            data = post(parse_json(text))
            return LLMResult(data, text, model, usage.input_tokens, usage.output_tokens)
        except (json.JSONDecodeError, ExtractError) as e:
            last = e
    if isinstance(last, ExtractError):
        raise last
    raise ExtractError("응답을 읽을 수 없습니다. 다시 시도해 주세요.", detail=f"JSON 파싱 실패 (재시도 후): {last}")


def extract(slices: list[SliceInfo], provider: Provider | None = None) -> LLMResult:
    """호출 #1: 이미지 → payload (meta 없음)."""
    return _call_and_parse(load_prompt("extract_v2.txt"), build_slice_content(slices),
                           postprocess_extract, provider)


def extract_lines(slices: list[SliceInfo], provider: Provider | None = None) -> LLMResult:
    """검증용: 구조 없이 이미지의 모든 문구를 한 줄씩."""
    return _call_and_parse(load_prompt("lines_v1.txt"), build_slice_content(slices),
                           postprocess_lines, provider)


if __name__ == "__main__":  # CLI: uv run python -m app.extractor <png> [out_dir] [--no-verify]
    import sys
    from app.slicer import prepare

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else Path("storage/_extract_test") / src.stem
    infos = prepare(src, out / "slices")
    print(f"provider={config.LLM_PROVIDER} model={config.LLM_MODEL} slices={len(infos)}")
    r1 = extract(infos)
    (out / "payload.json").write_text(json.dumps(r1.data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"extract ok  tokens in={r1.input_tokens} out={r1.output_tokens}  → {out/'payload.json'}")
    if "--no-verify" not in sys.argv:
        from app.verify import verify
        r2 = verify(src, out / "slices_verify", r1.data)
        (out / "issues.json").write_text(json.dumps(r2.data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"verify ok   tokens in={r2.input_tokens} out={r2.output_tokens}  issues={len(r2.data['issues'])}")
        for it in r2.data["issues"]:
            print("   ", it["severity"], it["path"], "|", it.get("json_says"), "→ 2차:", it.get("image_says"))
