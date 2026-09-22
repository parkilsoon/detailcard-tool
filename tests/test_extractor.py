import json

import pytest

from app import config
from app.extractor import ExtractError, parse_json, postprocess_extract, strip_code_fence


def test_strip_code_fence():
    assert strip_code_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert strip_code_fence('```\n{"a":1}\n```') == '{"a":1}'
    assert strip_code_fence('{"a":1}') == '{"a":1}'


def test_parse_json_with_noise():
    assert parse_json('여기 결과입니다:\n{"a": 1}\n끝') == {"a": 1}


def test_postprocess_collects_unreadable(hand_payload):
    hand_payload["sections"][0]["rows"][4]["value"] = "6573___UNREADABLE___"
    out = postprocess_extract(hand_payload)
    assert "sections.0.rows.4.value" in out["uncertain"]


def test_postprocess_strips_disallowed_tags(hand_payload):
    hand_payload["header"]["ingredient"] = '<b>x</b> <em>ok</em> <script>alert(1)</script> <em class="x">bad</em>'
    out = postprocess_extract(hand_payload)
    assert out["header"]["ingredient"] == 'x <em>ok</em> alert(1) <em>bad</em>'


def test_postprocess_length_limit(hand_payload):
    hand_payload["footer"]["left"] = "a" * (config.FIELD_MAX_LEN + 1)
    with pytest.raises(ExtractError):
        postprocess_extract(hand_payload)


def test_postprocess_schema_failure(hand_payload):
    del hand_payload["header"]["product_name"]
    with pytest.raises(ExtractError):
        postprocess_extract(hand_payload)


def test_call_and_parse_retries_once(monkeypatch, hand_payload):
    from app import extractor
    calls = []

    class U:
        input_tokens = 1
        output_tokens = 2

    def fake_call(system, content, provider=None):
        calls.append(1)
        if len(calls) == 1:
            return "not json", U()
        return json.dumps(hand_payload, ensure_ascii=False), U()

    monkeypatch.setattr(extractor, "call_llm", fake_call)
    r = extractor.extract([])
    assert len(calls) == 2
    assert r.data["header"]["product_name"] == hand_payload["header"]["product_name"]


def test_call_and_parse_gives_up_after_two(monkeypatch):
    from app import extractor

    class U:
        input_tokens = output_tokens = 0

    monkeypatch.setattr(extractor, "call_llm", lambda s, c, provider=None: ("nope", U()))
    with pytest.raises(ExtractError):
        extractor.extract([])


def test_postprocess_collapses_newlines(hand_payload):
    hand_payload["header"]["ingredient"] = "Clomipramine HCl\n  15mg"
    assert postprocess_extract(hand_payload)["header"]["ingredient"] == "Clomipramine HCl 15mg"


def test_unsupported_kind_message(hand_payload):
    hand_payload["sections"].append({"kind": "timeline", "items": []})
    with pytest.raises(ExtractError) as ei:
        postprocess_extract(hand_payload)
    assert "지원하지 않는 형식" in str(ei.value) and ei.value.unsupported_kinds == ["timeline"]
    assert ei.value.detail and "kind" in ei.value.detail


def test_other_schema_failure_is_friendly(hand_payload):
    del hand_payload["header"]["company"]
    with pytest.raises(ExtractError) as ei:
        postprocess_extract(hand_payload)
    assert "정해진 형식과 맞지 않습니다" in str(ei.value) and "company" in ei.value.detail


def test_normalize_product_name():
    from app.extractor import normalize_product_name
    def run(name, form):
        return normalize_product_name({"header": {"product_name": name, "form": form}})["header"]["product_name"]
    assert run("구세", "정") == "구세정"
    assert run("글리포스", "연질캡슐") == "글리포스연질캡슐"
    assert run("구세정", "정") == "구세정"                 # 이미 붙어 있으면 그대로
    assert run("동구에페리손", "정·서방정") == "동구에페리손"  # 복합 배지는 안 붙임
    assert run("리나탑F", "패밀리") == "리나탑F"
    assert run("자이그라", "3제형") == "자이그라"
    assert run("나조타손", None) == "나조타손"
    assert run("더모타손MLE", "<em>크림</em>") == "더모타손MLE크림"


def test_color_tags_survive_postprocess(hand_payload):
    hand_payload["header"]["ingredient"] = '<red>a</red> <blue class="x">b</blue> <b>c</b> <GREEN>d</GREEN>'
    out = postprocess_extract(hand_payload)
    assert out["header"]["ingredient"] == '<red>a</red> <blue>b</blue> c <green>d</green>'
    from app.sanitize import plain_text
    assert plain_text(out["header"]["ingredient"]) == "a b c d"
