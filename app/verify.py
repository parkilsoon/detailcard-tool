"""검증 = 2차 독립 전사 + 코드 diff.

LLM 에게 "1차 결과를 보고 틀린 곳을 찾아라"고 시키는 방식은 실측에서 실제 오류를 잡지 못하고
오탐만 냈다. 대신 같은 이미지를 다른 슬라이스 규격으로 한 번 더 전사하고, 두 결과를 기계적으로
비교한다. 두 번이 같은 자리에서 같은 실수를 할 확률은 낮으므로, 다른 필드 = 사람이 볼 곳이다.
"""
from __future__ import annotations

import re
from pathlib import Path

from app import config
from app.extractor import LLMResult, extract, extract_lines
from app.paths import iter_strings, path_get
from app.sanitize import plain_text
from app.slicer import prepare

VERIFY_METHOD = "second-pass-diff-v1"
LINES_METHOD = "lines-coverage-v1"
MISSING_PREFIX = "_missing."   # 결과 어디에도 없는 문구. 화면 상단에 별도 목록으로 보여준다
STRUCTURE_PATH = "_structure"  # 문구 줄 수와 결과 필드 수가 크게 어긋남 → 블록이 잘못 묶였을 가능성
STRUCTURE_RATIO = (0.75, 1.35) # 실측 7장은 0.94~1.14

# 숫자·코드·단위가 들어간 값은 critical
_NUMERIC = re.compile(r"\d")
# 항상 critical 로 보는 spec_table 라벨
_CRITICAL_LABELS = ("함량", "규격", "보험코드", "약가", "환자부담", "저장", "유효")


# 대조 전용 정규화. 저장 값은 건드리지 않는다.
#  - 공백, 글머리·구분 기호(· • - – —), 따옴표, 괄호 제거 / 소문자 / l→i (HCl vs HCI 같은 OCR 혼동)
_NOISE = re.compile(r"[\s·•‧∙・\-–—'\"‘’“”()\[\]:]+")
_BULLET_PREFIX = re.compile(r"^[\s·•‧∙・\-–—▶►◆■□○●▪★☆✓✔◎⚠△ⓘ※]+")


def _norm(v: str | None) -> str:
    if v is None:
        return ""
    t = plain_text(v)
    t = _BULLET_PREFIX.sub("", t)
    t = _NOISE.sub("", t).lower()
    return t.replace("l", "i")


def _severity(path: str, a: str, b: str, payload: dict) -> str:
    if _NUMERIC.search(a) or _NUMERIC.search(b):
        return "critical"
    m = re.match(r"sections\.(\d+)\.", path)
    if m:
        sec = payload["sections"][int(m.group(1))]
        kind = sec["kind"]
        if kind in ("notice", "variants"):
            return "critical"
        rm = re.match(r"sections\.\d+\.rows\.(\d+)\.value$", path)
        if kind == "spec_table" and rm:
            label = sec["rows"][int(rm.group(1))]["label"]
            if any(k in label for k in _CRITICAL_LABELS):
                return "critical"
        im = re.match(r"sections\.\d+\.items\.(\d+)\.", path)
        if kind == "callouts" and im and sec["items"][int(im.group(1))]["tone"] == "action":
            return "critical"
    return "minor"


def _section_signature(s: dict) -> tuple:
    kind = s["kind"]
    if kind == "spec_table":
        return (kind, tuple(_norm(r["label"]) for r in s["rows"]))
    if kind == "variants":
        return (kind, tuple(len(v.get("rows") or []) for v in s["items"]))
    if kind == "callouts":
        return (kind, tuple((len(c.get("bullets") or []), len(c.get("groups") or [])) for c in s["items"]))
    if kind == "points":
        return (kind, len(s["items"]), len(s.get("stats") or []))
    if kind == "icd":
        return (kind, len(s["items"]))
    if kind == "notice":
        return (kind, tuple((len(b.get("paragraphs") or []), len(b.get("bullets") or [])) for b in s["blocks"]))
    if kind == "text_box":
        return (kind, len(s["paragraphs"]))
    if kind == "table":
        return (kind, len(s["rows"]))
    return (kind,)


def diff_payloads(first: dict, second: dict) -> list[dict]:
    """1차(first) 기준 경로로 이슈를 만든다. image_says 에는 2차 값을 넣는다."""
    issues: list[dict] = []
    a_secs, b_secs = first["sections"], second["sections"]
    if [s["kind"] for s in a_secs] != [s["kind"] for s in b_secs]:
        issues.append({"severity": "critical", "path": "sections.0.title",
                       "image_says": " → ".join(s["kind"] for s in b_secs),
                       "json_says": " → ".join(s["kind"] for s in a_secs),
                       "note": "두 번째 전사에서 섹션 구성이 다르게 읽혔습니다. 섹션 누락·중복을 확인하세요."})
        return issues  # 구조가 다르면 필드 대조는 의미 없음

    # 구조가 다른 섹션은 섹션 단위로 한 건만
    skip: set[int] = set()
    for i, (sa, sb) in enumerate(zip(a_secs, b_secs)):
        if _section_signature(sa) != _section_signature(sb):
            skip.add(i)
            issues.append({"severity": "critical", "path": f"sections.{i}.title",
                           "image_says": None, "json_says": None,
                           "note": "두 번째 전사에서 이 섹션의 항목 수나 라벨이 다르게 읽혔습니다. 항목 누락·중복을 확인하세요."})

    b_map = dict(iter_strings({k: v for k, v in second.items() if k not in ("meta", "uncertain")}))
    for path, a_val in iter_strings({k: v for k, v in first.items() if k not in ("meta", "uncertain")}):
        m = re.match(r"sections\.(\d+)\.", path)
        if m and int(m.group(1)) in skip:
            continue
        if path.endswith(".kind") or path.endswith(".tone") or path.endswith(".icon") or path == "schema_version":
            continue
        b_val = b_map.get(path)
        if _norm(a_val) == _norm(b_val):
            continue
        # 표 행의 값/배지 분리만 다른 경우 (예: "3,500원" + chip "비급여·전문" vs "3,500원 비급여·전문") 는 잡음
        rm = re.match(r"(sections\.\d+\.rows\.\d+)\.(value|chip)$", path)
        if rm:
            base = rm.group(1)
            a_row = _norm(path_get(first, base + ".value", "")) + _norm(path_get(first, base + ".chip", ""))
            b_row = _norm(path_get(second, base + ".value", "")) + _norm(path_get(second, base + ".chip", ""))
            if a_row == b_row:
                continue
        issues.append({"severity": _severity(path, a_val, b_val or "", first),
                       "path": path, "image_says": plain_text(b_val), "json_says": plain_text(a_val),
                       "note": None})
    return issues


def diff_snippets(a: str | None, b: str | None, context: int = 8, max_items: int = 4) -> list[dict]:
    """두 문자열에서 다른 구간만 앞뒤 문맥과 함께 발췌한다. 검수 화면에서 긴 문단의 차이를 짚어주는 용도."""
    import difflib
    a, b = plain_text(a), plain_text(b)
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        out.append({"first": a[max(0, a0 - context):a1 + context].strip(),
                    "second": b[max(0, b0 - context):b1 + context].strip(),
                    "first_seg": a[a0:a1], "second_seg": b[b0:b1]})
        if len(out) >= max_items:
            break
    return out


# ---------- 문구 목록 대조 (기본 검증 방식) ----------

_SKIP_PATHS = re.compile(r"(\.kind|\.tone|\.icon|\.layout_hint|^schema_version|^meta\.)")
_LINE_MIN = 2


def _field_texts(payload: dict) -> list[tuple[str | None, str, str]]:
    """(path, 원문, 정규화문) 목록. 문서 순서 유지.
    섹션 번호(no)는 문자열 필드가 아니지만 이미지에서는 제목 앞에 붙어 한 줄로 읽히므로
    path=None 인 가짜 항목으로 제목 앞에 끼워 넣는다 (대조용, 매칭 대상 아님)."""
    out: list[tuple[str | None, str, str]] = []
    for path, val in iter_strings({k: v for k, v in payload.items() if k not in ("meta", "uncertain")}):
        if _SKIP_PATHS.search(path):
            continue
        m = re.match(r"sections\.(\d+)\.title$", path)
        if m:
            no = payload["sections"][int(m.group(1))].get("no")
            if no is not None:
                out.append((None, str(no), str(no)))
        n = _norm(val)
        if n:
            out.append((path, val, n))
    return out


def coverage_issues(payload: dict, lines: list[str]) -> list[dict]:
    """이미지 문구 목록(lines)의 각 줄이 payload 어딘가에 있는지 대조한다.
    - 그대로 있음 → 통과
    - 비슷한 필드가 있음 (글자 몇 개 차이) → 그 필드에 '확인 필요' + 이미지 문구
    - 어디에도 없음 → _missing.N (화면 상단 누락 목록)"""
    import difflib
    fields = _field_texts(payload)
    joined = "".join(n for _, _, n in fields)      # 인접 필드에 걸친 줄(라벨+값)도 잡히게 붙여서 본다
    issues: list[dict] = []
    flagged: set[str] = set()
    n_missing = 0
    n_fields = sum(1 for f in fields if f[0] is not None)
    n_lines = sum(1 for l in lines if len(_norm(l)) >= _LINE_MIN)
    if n_fields and n_lines >= 10:   # 실제 카드는 50줄 이상. 너무 짧은 목록은 판정하지 않는다
        ratio = n_lines / n_fields
        if not (STRUCTURE_RATIO[0] <= ratio <= STRUCTURE_RATIO[1]):
            issues.append({"severity": "critical", "path": STRUCTURE_PATH, "image_says": None, "json_says": None,
                           "note": f"이미지에서 읽은 문구 {n_lines}줄에 비해 결과 항목이 {n_fields}개입니다. "
                                   "블록이 합쳐지거나 나뉘어 들어갔을 수 있으니 미리보기로 전체 구성을 확인해 주세요."})
    for raw in lines:
        line = raw.strip()
        n = _norm(line)
        if len(n) < _LINE_MIN or config.UNREADABLE in line:
            continue
        if n in joined:
            continue
        # 가장 비슷한 필드 찾기
        best, best_ratio = None, 0.0
        for path, val, fn in fields:
            if path is None:
                continue
            if abs(len(fn) - len(n)) > max(12, len(n) // 2):
                continue
            r = difflib.SequenceMatcher(None, fn, n, autojunk=False).ratio()
            if r > best_ratio:
                best, best_ratio = (path, val), r
        if best and best_ratio >= 0.72 and best[0] not in flagged:
            flagged.add(best[0])
            issues.append({"severity": _severity(best[0], best[1], line, payload) if best[0].startswith("sections.") else ("critical" if _NUMERIC.search(line) else "minor"),
                           "path": best[0], "image_says": line, "json_says": plain_text(best[1]),
                           "note": None})
        else:
            n_missing += 1
            issues.append({"severity": "critical" if _NUMERIC.search(line) else "minor",
                           "path": f"{MISSING_PREFIX}{n_missing}", "image_says": line, "json_says": None,
                           "note": "이미지에는 있는데 결과 어디에도 없는 문구입니다. 알맞은 칸에 넣어 주세요."})
    return issues


def verify_lines(original: Path, work_dir: Path, first: dict, provider=None) -> LLMResult:
    slices = prepare(original, work_dir, slice_height=config.VERIFY_SLICE_HEIGHT)
    r = extract_lines(slices, provider)
    issues = coverage_issues(first, r.data["lines"])
    return LLMResult({"issues": issues, "method": LINES_METHOD, "lines": r.data["lines"]},
                     r.raw_text, r.model, r.input_tokens, r.output_tokens)


# ---------- 2차 구조화 전사 diff (VERIFY_MODE=structured) ----------

def second_pass(original: Path, work_dir: Path, provider=None) -> LLMResult:
    """1차와 다른 슬라이스 높이로 다시 전사한다."""
    slices = prepare(original, work_dir, slice_height=config.VERIFY_SLICE_HEIGHT)
    return extract(slices, provider)


def verify(original: Path, work_dir: Path, first: dict, provider=None) -> LLMResult:
    if config.VERIFY_MODE == "lines":
        return verify_lines(original, work_dir, first, provider)
    r = second_pass(original, work_dir, provider)
    issues = diff_payloads(first, r.data)
    return LLMResult({"issues": issues, "method": VERIFY_METHOD, "second": r.data},
                     r.raw_text, r.model, r.input_tokens, r.output_tokens)
