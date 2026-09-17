import re

from app.renderer import TEMPLATE_VERSION, render_card
from app.sanitize import em


def test_em_filter_whitelist():
    out = str(em('<em>ok</em> <b>no</b> <div onclick="x()">d</div> <script>alert(1)</script>'))
    assert "<em>ok</em>" in out
    assert "<b>" not in out and "<div" not in out and "<script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert str(em(None)) == ""


def test_render_fixtures(fixture_name, hand_payload):
    html = render_card(hand_payload)
    assert html.startswith("<!DOCTYPE html>")
    assert f"template_version: {TEMPLATE_VERSION}" in html
    assert "<link" not in html and "<script" not in html  # 외부 의존 없음
    assert hand_payload["header"]["product_name"] in html
    # 모든 섹션이 순서대로 나온다
    kinds = re.findall(r'class="sec sec-([a-z_]+)"', html)
    assert kinds == [s["kind"] for s in hand_payload["sections"]]


def test_render_xss(hand_payload):
    hand_payload["header"]["ingredient"] = '<script>alert(1)</script><em>x</em><b>y</b>'
    hand_payload["sections"][0]["rows"][0]["value"] = '<img src=x onerror=alert(1)>'
    html = render_card(hand_payload)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;<em>x</em>&lt;b&gt;y&lt;/b&gt;" in html
    assert "<img" not in html and "onerror=" not in html.replace("&lt;img src=x onerror=alert(1)&gt;", "")


def test_render_null_fields_omitted(hand_payload):
    hand_payload["header"]["form"] = None
    hand_payload["header"]["category"] = None
    hand_payload["header"]["badges"] = []
    for s in hand_payload["sections"]:
        if s["kind"] == "points":
            for it in s["items"]:
                it["desc"] = None
        if s["kind"] == "callouts":
            for it in s["items"]:
                it["note"] = None
    html = render_card(hand_payload)
    assert 'class="pform"' not in html
    assert 'class="cat"' not in html
    assert 'class="tags"' not in html
    assert 'class="note"' not in html
    assert not re.search(r"<p>\s*</p>", html)


def test_render_variable_counts(hand_payload):
    for s in hand_payload["sections"]:
        if s["kind"] == "icd":
            s["items"] = s["items"] * 3
            n = len(s["items"])
    html = render_card(hand_payload)
    assert html.count('class="item"') == n


def test_render_all_kinds():
    from tests.conftest import load_json
    d = load_json("allkinds.payload.json")
    html = render_card(d)
    kinds = re.findall(r'class="sec sec-([a-z_]+)"', html)
    assert kinds == [s["kind"] for s in d["sections"]]
    assert "657300850" in html and "657307940" in html          # variants rows
    assert 'class="tile"' in html and "35.7%" in html            # stats
    assert 'class="pt star hl"' in html and "Salonia 2024" in html  # highlight + cite
    assert "<table" in html and "더모타손 (IV)" in html           # table
    assert 'class="warn warn"' in html and "▶ 제외" in html       # notice tone + heading
    assert 'class="tbox plain"' in html                            # text_box
    assert 'class="grp"' in html and "▶ 서방정" in html            # callout groups
    assert 'class="desc"' in html and "회전근개" in html            # icd desc
    assert "<script" not in html


def test_render_notice_tones(hand_payload):
    for s in hand_payload["sections"]:
        if s["kind"] == "notice":
            s["tone"] = "noncovered"
    assert 'class="warn noncovered"' in render_card(hand_payload)


def test_numbered_table_renders_section_header():
    from tests.conftest import load_json
    d = load_json("allkinds.payload.json")
    t = next(s for s in d["sections"] if s["kind"] == "table")
    t["no"], t["title"], t["title_en"] = 2, "성분·작용", "INGREDIENTS & FUNCTION"
    html = render_card(d)
    assert "INGREDIENTS &amp; FUNCTION" in html and 'class="sec sec-table numbered"' in html
