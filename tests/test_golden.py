"""수용 기준 12.1 ~ 12.3. scripts/run_golden.py 가 만든 실제 LLM 추출 결과를 검사한다.
결과 파일이 없으면 건너뛴다 (API 키 없는 환경)."""
import json
import re
from pathlib import Path

import pytest

from app.paths import iter_strings
from app.sanitize import plain_text
from app.schema import validate_payload
from tests.conftest import FIXTURES

EXTRACTED = FIXTURES / "extracted"


def _load(name: str) -> dict:
    p = EXTRACTED / f"{name}.json"
    if not p.exists():
        pytest.skip(f"골든 추출 결과 없음: {p} (scripts/run_golden.py 실행 필요)")
    return json.loads(p.read_text(encoding="utf-8"))


def _all_text(payload: dict) -> str:
    return "".join(plain_text(v) for _, v in iter_strings(payload))


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_structure(fixture_name, expected):
    data = _load(fixture_name)
    p = validate_payload(data)
    exp = expected[fixture_name]
    assert [s.kind for s in p.sections] == exp["section_kinds"]
    by_kind = {s.kind: s for s in p.sections}
    assert len(by_kind["icd"].items) == exp["icd_count"]
    assert len(by_kind["points"].items) == exp["points_count"]
    assert data["uncertain"] == [], f"판독 불확실 필드: {data['uncertain']}"


def test_values(fixture_name, expected):
    data = _load(fixture_name)
    exp = expected[fixture_name]
    spec = next(s for s in data["sections"] if s["kind"] == "spec_table")
    rows = {r["label"]: plain_text(r["value"]) for r in spec["rows"]}
    for label, needles in exp["spec_rows"].items():
        assert label in rows, f"행 없음: {label} (있는 행: {list(rows)})"
        for n in needles:
            assert n in rows[label], f"{label}: {n!r} not in {rows[label]!r}"
    text = _all_text(data)
    for n in exp["text_contains"]:
        assert n in text, f"{n!r} 누락"
    if "icd_codes" in exp:
        icd = next(s for s in data["sections"] if s["kind"] == "icd")
        assert [plain_text(i["code"]) for i in icd["items"]] == exp["icd_codes"]


def test_no_missing_text(fixture_name):
    """수기 전사 기준 파일의 모든 줄이 (공백 무시) 추출 결과에 포함되어야 한다."""
    data = _load(fixture_name)
    hay = _squash(_all_text(data))
    lines = [l for l in (FIXTURES / f"{fixture_name}.transcript.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    missing = [l for l in lines if _squash(l) not in hay]
    assert not missing, "누락 문자열:\n" + "\n".join(missing)
