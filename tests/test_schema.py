import re

import pytest
from pydantic import ValidationError

from app.config import PROMPTS_DIR
from app.schema import validate_issues, validate_payload
from tests.conftest import load_json


def test_hand_payloads_validate(fixture_name, hand_payload, expected):
    p = validate_payload(hand_payload)
    exp = expected[fixture_name]
    assert [s.kind for s in p.sections] == exp["section_kinds"]
    by_kind = {s.kind: s for s in p.sections}
    assert len(by_kind["icd"].items) == exp["icd_count"]
    assert len(by_kind["points"].items) == exp["points_count"]


def test_bad_enum_rejected(hand_payload):
    hand_payload["sections"][0]["kind"] = "table"
    with pytest.raises(ValidationError):
        validate_payload(hand_payload)
    hand_payload["sections"][0]["kind"] = "spec_table"
    hand_payload["header"]["badges"][0]["kind"] = "gold"
    with pytest.raises(ValidationError):
        validate_payload(hand_payload)


def test_issues_validate():
    v = validate_issues({"issues": []})
    assert v.issues == []
    v = validate_issues({"issues": [{"severity": "critical", "path": "a.b", "image_says": "1", "json_says": "2"}]})
    assert v.issues[0].severity == "critical"
    with pytest.raises(ValidationError):
        validate_issues({"issues": [{"severity": "fatal", "path": "a"}]})


KINDS = ["spec_table", "variants", "callouts", "icd", "points", "notice", "text_box", "table"]
BADGES = ["plain", "code", "covered", "noncovered", "selective", "mixed"]


def test_prompt_schema_enums_match_pydantic():
    """프롬프트 안의 손으로 쓴 스키마 사본이 pydantic 열거형과 어긋나지 않는지 확인."""
    from typing import get_args
    from app import schema
    assert list(get_args(schema.SectionKind)) == KINDS
    assert list(get_args(schema.BadgeKind)) == BADGES
    txt = (PROMPTS_DIR / "extract_v2.txt").read_text(encoding="utf-8")
    for kind in KINDS:
        assert f'"kind": "{kind}"' in txt, kind
    for badge in BADGES:
        assert f'"{badge}"' in txt, badge
    for tone in get_args(schema.CalloutTone) + get_args(schema.NoticeTone) + get_args(schema.BoxTone):
        assert f'"{tone}"' in txt, tone
    for icon in get_args(schema.PointIcon):
        assert f'"{icon}"' in txt, icon
    kinds_in_prompt = set(re.findall(r'"kind":\s*"([a-z_]+)"', txt)) - set(BADGES)
    assert kinds_in_prompt == set(KINDS)
    assert "layout_hint" in txt and '"schema_version": "2.0"' in txt


def test_allkinds_fixture_validates():
    d = load_json("allkinds.payload.json")
    p = validate_payload(d)
    assert [s.kind for s in p.sections] == ["spec_table", "text_box", "variants", "callouts", "icd", "points", "table", "notice"]
    assert p.schema_version == "2.0"


def test_notice_requires_blocks(hand_payload):
    for s in hand_payload["sections"]:
        if s["kind"] == "notice":
            s.pop("blocks")
            s["paragraphs"] = ["x"]
    with pytest.raises(ValidationError):
        validate_payload(hand_payload)
