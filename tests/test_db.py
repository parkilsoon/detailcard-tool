from app.db import COVERAGE_LABELS, coverage_from_badges


def b(text, kind):
    return {"text": text, "kind": kind}


def test_coverage_from_badges():
    assert coverage_from_badges([b("전문의약품", "plain"), b("311", "code"), b("급여·비급여", "mixed")]) == "both"
    assert coverage_from_badges([b("급여·비급여", "plain")]) == "both"          # 종류를 잘못 붙여도 글자로 판정
    assert coverage_from_badges([b("급여", "covered")]) == "covered"
    assert coverage_from_badges([b("비급여", "noncovered")]) == "noncovered"
    assert coverage_from_badges([b("비급여", "plain")]) == "noncovered"
    assert coverage_from_badges([b("급여", "covered"), b("비급여", "noncovered")]) == "both"
    assert coverage_from_badges([b("선별급여", "selective")]) == "selective"
    assert coverage_from_badges([b("<em>급여</em>", "covered")]) == "covered"
    assert coverage_from_badges([b("전문의약품", "plain"), b("259", "code")]) is None
    assert coverage_from_badges([]) is None and coverage_from_badges(None) is None
    assert COVERAGE_LABELS["both"] == "급여·비급여"
