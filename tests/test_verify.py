"""2차 전사 diff 검증. 네트워크 없음."""
import copy
import json

import pytest

from app.verify import diff_payloads
from tests.conftest import FIXTURES


def test_identical_no_issues(hand_payload):
    assert diff_payloads(hand_payload, copy.deepcopy(hand_payload)) == []


def test_em_and_whitespace_ignored(hand_payload):
    b = copy.deepcopy(hand_payload)
    b["sections"][0]["rows"][1]["value"] = hand_payload["sections"][0]["rows"][1]["value"].replace("<em>", "").replace("</em>", "") + "  "
    assert diff_payloads(hand_payload, b) == []


def test_value_diff_severity(hand_payload):
    b = copy.deepcopy(hand_payload)
    b["sections"][0]["rows"][4]["value"] = "657309021"      # 보험코드 (숫자)
    b["header"]["company"] = "동구바이오"                   # 산문
    issues = {i["path"]: i for i in diff_payloads(hand_payload, b)}
    assert issues["sections.0.rows.4.value"]["severity"] == "critical"
    assert issues["sections.0.rows.4.value"]["image_says"] == "657309021"
    assert issues["header.company"]["severity"] == "minor"


def test_notice_and_action_always_critical(hand_payload):
    b = copy.deepcopy(hand_payload)
    for s in b["sections"]:
        if s["kind"] == "notice":
            s["blocks"][0]["paragraphs"][0] = s["blocks"][0]["paragraphs"][0] + " 추가 문구"
        if s["kind"] == "callouts":
            s["items"][1]["note"] = "다른 문구"
    sev = {i["path"]: i["severity"] for i in diff_payloads(hand_payload, b)}
    assert all(v == "critical" for v in sev.values()) and len(sev) == 2


def test_structure_mismatch_section_level(hand_payload):
    b = copy.deepcopy(hand_payload)
    icd = next(s for s in b["sections"] if s["kind"] == "icd")
    icd["items"].append({"code": "Z99", "name": "추가"})
    issues = diff_payloads(hand_payload, b)
    assert len(issues) == 1 and issues[0]["path"].endswith(".title") and "항목 수" in issues[0]["note"]


def test_section_order_mismatch(hand_payload):
    b = copy.deepcopy(hand_payload)
    b["sections"] = b["sections"][:-1]
    issues = diff_payloads(hand_payload, b)
    assert len(issues) == 1 and "섹션 구성" in issues[0]["note"]


def test_real_runs_catch_known_errors():
    """실제 Gemini 두 실행(1536px vs 768px)의 diff 가 알려진 오류 3건을 모두 잡는지."""
    old = FIXTURES / "extracted" / "runs" / "gemini-2.5-pro_slice1536" / "guse.json"
    new = FIXTURES / "extracted" / "guse.json"
    if not (old.exists() and new.exists()):
        pytest.skip("실행 결과 없음")
    a, b = json.loads(old.read_text()), json.loads(new.read_text())
    paths = {i["path"] for i in diff_payloads(a, b)}
    assert "sections.4.blocks.0.paragraphs.0" in paths  # 금기 문단 (적절하게 누락, 저해제제도)
    assert all(i["severity"] == "critical" for i in diff_payloads(a, b) if i["path"] == "sections.4.blocks.0.paragraphs.0")


def test_row_split_between_value_and_chip_is_not_an_issue(hand_payload):
    b = copy.deepcopy(hand_payload)
    row = b["sections"][0]["rows"][5]
    row["value"], row["chip"] = "3,500원", "비급여 · 전문"
    hand_payload["sections"][0]["rows"][5]["value"] = "3,500원 비급여 · 전문"
    hand_payload["sections"][0]["rows"][5]["chip"] = None
    assert diff_payloads(hand_payload, b) == []


def test_diff_snippets():
    from app.verify import diff_snippets
    a = "단독요법으로 적절하게 조절되지 않는 조루증"
    b = "단독요법으로 조절되지 않는 조루증"
    sn = diff_snippets(a, b)
    assert len(sn) == 1 and sn[0]["first_seg"].strip() == "적절하게" and sn[0]["second_seg"] == ""
    assert diff_snippets("같다", "같다") == []


def test_coverage_exact_lines_pass(hand_payload):
    from app.verify import coverage_issues, _field_texts
    lines = [v for p, v, _ in _field_texts(hand_payload) if p is not None]
    assert coverage_issues(hand_payload, lines) == []


def test_coverage_section_header_and_icon_lines(hand_payload):
    from app.verify import coverage_issues
    lines = ["1 제품 정보 PRODUCT INFORMATION", "2 상병코드 ICD-10 CODE", "★ " + hand_payload["sections"][3]["items"][0]["title"].replace("<em>", "").replace("</em>", ""),
             "규격 : " + hand_payload["sections"][0]["rows"][1]["value"].replace("<em>", "").replace("</em>", "")]
    assert coverage_issues(hand_payload, lines) == []


def test_coverage_label_plus_value_line_pass(hand_payload):
    from app.verify import coverage_issues
    assert coverage_issues(hand_payload, ["보험코드 657309020" if "657309020" in str(hand_payload) else "보험코드 657304640"]) == []


def test_coverage_near_match_flags_field(hand_payload):
    from app.verify import coverage_issues
    notice = next(s for s in hand_payload["sections"] if s["kind"] == "notice")
    para = notice["blocks"][0]["paragraphs"][0].replace("<em>", "").replace("</em>", "")
    changed = para.replace("조절되지", "조절 되지 않게 되지") if "조절되지" in para else para[:-6] + "다른말입니다"
    issues = coverage_issues(hand_payload, [changed])
    assert len(issues) == 1 and issues[0]["path"].endswith("blocks.0.paragraphs.0")
    assert issues[0]["severity"] == "critical" and issues[0]["image_says"] == changed


def test_coverage_missing_line(hand_payload):
    from app.verify import coverage_issues, MISSING_PREFIX
    issues = coverage_issues(hand_payload, ["※ 본 품목은 대우제약 재위탁 품목입니다", "고시 제2099-1호 시행"])
    assert len(issues) == 2 and all(i["path"].startswith(MISSING_PREFIX) for i in issues)
    assert issues[1]["severity"] == "critical"  # 숫자 포함


def test_coverage_skips_short_and_unreadable(hand_payload):
    from app.verify import coverage_issues
    assert coverage_issues(hand_payload, ["·", "1", "___UNREADABLE___ 어쩌구"]) == []


def test_diff_allkinds_identity():
    import copy
    from tests.conftest import load_json
    d = load_json("allkinds.payload.json")
    assert diff_payloads(d, copy.deepcopy(d)) == []
    b = copy.deepcopy(d)
    b["sections"][2]["items"][0]["rows"][0]["value"] = "657300851"
    issues = diff_payloads(d, b)
    assert len(issues) == 1 and issues[0]["severity"] == "critical" and issues[0]["path"] == "sections.2.items.0.rows.0.value"


def test_norm_ignores_bullets_separators_and_l_i():
    from app.verify import _norm
    assert _norm("· TCA(Serotonin 재흡수 저해) + PDE5-i") == _norm("TCA(Serotonin 재흡수 저해) + PDE5-i")
    assert _norm("성인 남성 · 4주(5회)") == _norm("성인 남성 - 4주(5회)")
    assert _norm("Clomipramine HCl 15mg") == _norm("Clomipramine HCI 15mg")
    assert _norm("Refs: 식약처 허가사항 ('26.9 기준)") == _norm("Refs: 식약처 허가사항 (26.9 기준)")
    assert _norm("445원 (2022.9.1)") != _norm("445원 (2022.9.7)")
    assert _norm("적절하게 조절되지") != _norm("조절되지")


def test_gemini_transient_retry(monkeypatch):
    import httpx
    from app import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    from google.genai import types
    from app.providers.gemini_provider import GeminiProvider
    from app.providers import LLMRefused, text_part
    import app.providers.gemini_provider as gp
    monkeypatch.setattr(gp.time, "sleep", lambda s: None)
    calls = []

    class FakeModels:
        def generate_content(self, **kw):
            calls.append(1)
            if len(calls) < 3:
                raise httpx.RemoteProtocolError("Server disconnected")
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(parts=[types.Part.from_text(text='{"a":1}')]), finish_reason=types.FinishReason.STOP)])

    class FakeClient:
        models = FakeModels()

    text, _ = GeminiProvider(FakeClient()).call("s", [text_part("x")])
    assert text == '{"a":1}' and len(calls) == 3

    calls.clear()

    class AlwaysFail:
        class models:
            @staticmethod
            def generate_content(**kw):
                calls.append(1); raise httpx.ConnectError("x")
    with pytest.raises(LLMRefused):
        GeminiProvider(AlwaysFail()).call("s", [text_part("x")])
    assert len(calls) == 4


def test_structure_warning_on_ratio_mismatch(hand_payload):
    from app.verify import coverage_issues, STRUCTURE_PATH, _field_texts
    lines = [v for p, v, _ in _field_texts(hand_payload) if p is not None]
    assert not any(i["path"] == STRUCTURE_PATH for i in coverage_issues(hand_payload, lines))
    few = lines[: len(lines) // 3]
    assert any(i["path"] == STRUCTURE_PATH for i in coverage_issues(hand_payload, few))
