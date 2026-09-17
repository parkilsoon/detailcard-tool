"""FastAPI 라우트 테스트. LLM 호출은 손 전사 payload 로 대체한다."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import fixture_png, load_json


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data.db")
    from app import extractor, service

    class R:
        def __init__(self, data):
            self.data, self.model, self.input_tokens, self.output_tokens = data, "fake", 0, 0

    monkeypatch.setattr(service, "enqueue", lambda card_id: service.run_pipeline(card_id))  # 테스트는 동기 실행
    monkeypatch.setattr(service, "extract", lambda slices: R(load_json("glifos.payload.json")))
    monkeypatch.setattr(service, "verify", lambda original, out_dir, payload: R(
        {"issues": [{"severity": "critical", "path": "sections.0.rows.5.value",
                     "image_says": "445원 (2022.9.1)", "json_says": "445원 (2022.9.7)", "note": "날짜"}]}))
    from app.main import app
    with TestClient(app) as c:
        yield c


def _upload(client, expected):
    png = fixture_png(expected, "glifos")
    r = client.post("/cards", files={"file": ("x.png", png.read_bytes(), "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"].rsplit("/", 1)[-1]


def test_index_empty(client):
    r = client.get("/")
    assert r.status_code == 200 and "디테일카드 목록" in r.text and "새로 등록" in r.text
    assert "PNG" in client.get("/new").text


def test_upload_rejects_non_png(client):
    r = client.post("/cards", files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert "PNG 파일만" in r.text


def test_full_flow(client, expected):
    card_id = _upload(client, expected)
    # TestClient 는 background task 를 응답 후 동기 실행한다
    st = client.get(f"/cards/{card_id}/status").json()
    assert st["status"] == "review" and st["issue_count"] == 1

    page = client.get(f"/cards/{card_id}").text
    assert "결과가 달랐던 항목" in page
    assert "445원 (2022.9.1)" in page          # 이미지 원문 병기
    assert 'title="sections.0.rows.5.value"' in page  # 경로는 title 에만
    assert '"kind"' not in page                # JSON 노출 금지

    # 인라인 저장
    r = client.patch(f"/cards/{card_id}/field", json={"path": "sections.0.rows.5.value", "value": "<em>445원</em> (2022.9.1) <b>x</b>"})
    assert r.json()["value"] == "<em>445원</em> (2022.9.1) x"
    r = client.patch(f"/cards/{card_id}/field", json={"path": "sections.9.rows.0.value", "value": "x"})
    assert r.status_code == 400
    r = client.patch(f"/cards/{card_id}/field", json={"path": "header.product_name", "value": ""})
    assert r.status_code == 400  # 필수값은 비울 수 없다
    r = client.patch(f"/cards/{card_id}/field", json={"path": "sections.3.items.0.desc", "value": " "})
    assert r.json()["value"] is None  # 선택값은 비우면 null

    # payload_raw 는 그대로
    from app import db
    card = db.get_card(card_id)
    assert card["payload_raw"]["sections"][0]["rows"][5]["value"] == "<em>445원</em> (2022.9.1)"
    assert card["payload"]["sections"][0]["rows"][5]["value"] == "<em>445원</em> (2022.9.1) x"
    assert card["insurance_code"] == "657304640" and card["coverage"] == "covered"

    # 미리보기 / 다운로드 / export
    assert "<!DOCTYPE html>" in client.get(f"/cards/{card_id}/preview").text
    r = client.get(f"/cards/{card_id}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert (client.get(f"/cards/{card_id}/export.json").json())["header"]["product_name"] == "글리포스"
    assert client.get(f"/cards/{card_id}/status").json()["status"] == "review"  # 다운로드는 등록이 아니다

    # 저장(등록)
    r = client.post(f"/cards/{card_id}/save", json={})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["registered_at"]
    from app import config
    card = db.get_card(card_id)
    assert card["status"] == "done" and card["company"] == "동구바이오제약" and card["html_path"]
    assert (config.STORAGE_DIR / card_id / "mobile.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    first_reg = card["registered_at"]
    # 수정하면 다시 review 로, 다시 저장하면 등록일은 유지되고 수정일만 갱신
    client.patch(f"/cards/{card_id}/field", json={"path": "header.category", "value": "x"})
    assert client.get(f"/cards/{card_id}/status").json()["status"] == "review"
    client.post(f"/cards/{card_id}/save", json={})
    assert db.get_card(card_id)["registered_at"] == first_reg
    # 등록된 항목은 삭제 불가
    assert client.post(f"/cards/{card_id}/delete", follow_redirects=False).status_code == 409

    # 목록
    idx = client.get("/").text
    assert "글리포스" in idx and "동구바이오제약" in idx and "등록됨" in idx


def test_failed_flow(client, expected, monkeypatch):
    from app import service
    from app.extractor import ExtractError

    def boom(slices):
        raise ExtractError("스키마 검증 실패")
    monkeypatch.setattr(service, "extract", boom)
    card_id = _upload(client, expected)
    assert client.get(f"/cards/{card_id}/status").json()["status"] == "failed"
    page = client.get(f"/cards/{card_id}").text
    assert "추출에 실패했습니다" in page and "다시 시도" in page
    assert client.patch(f"/cards/{card_id}/field", json={"path": "header.company", "value": "x"}).status_code == 409


def test_review_shows_missing_lines_and_hint(client, expected, monkeypatch):
    from app import service
    from tests.conftest import load_json

    class R:
        def __init__(self, data):
            self.data, self.model, self.input_tokens, self.output_tokens = data, "fake", 0, 0

    monkeypatch.setattr(service, "extract", lambda slices: R(load_json("allkinds.payload.json")))
    monkeypatch.setattr(service, "verify", lambda original, out_dir, payload: R(
        {"issues": [{"severity": "critical", "path": "_missing.1", "image_says": "고시 제2020-69호", "json_says": None, "note": "누락"}],
         "method": "lines-coverage-v1", "lines": []}))
    card_id = _upload(client, expected)
    page = client.get(f"/cards/{card_id}").text
    assert "결과에 빠진 문구" in page and "고시 제2020-69호" in page
    assert "임시 서식" in page and "7칸 눈금" in page
    assert "규격별 정보 1" in page and 'title="sections.2.items.1.rows.0.value"' in page
    r = client.patch(f"/cards/{card_id}/field", json={"path": "sections.6.rows.0.3", "value": "x"})
    assert r.status_code == 200
    from app import db
    assert db.get_card(card_id)["insurance_code"] == "657300850"
    assert "<!DOCTYPE html>" in client.get(f"/cards/{card_id}/preview").text


def test_issue_on_hidden_path_is_still_shown(client, expected, monkeypatch):
    from app import service
    from tests.conftest import load_json

    class R:
        def __init__(self, data):
            self.data, self.model, self.input_tokens, self.output_tokens = data, "fake", 0, 0

    monkeypatch.setattr(service, "extract", lambda slices: R(load_json("glifos.payload.json")))
    monkeypatch.setattr(service, "verify", lambda original, out_dir, payload: R(
        {"issues": [{"severity": "minor", "path": "sections.0.title_en", "image_says": "PRODUCT INFO", "json_says": "PRODUCT INFORMATION", "note": None},
                    {"severity": "minor", "path": "footer.left", "image_says": "x", "json_says": "y", "note": None}], "lines": []}))
    card_id = _upload(client, expected)
    page = client.get(f"/cards/{card_id}").text
    assert 'title="sections.0.title_en"' in page and "PRODUCT INFO" in page
    assert page.count('class="field flagged') == 2


def test_failed_shows_friendly_message_and_detail(client, expected, monkeypatch):
    from app import service
    from app.extractor import ExtractError

    def boom(slices):
        raise ExtractError("이 카드에는 아직 지원하지 않는 형식의 블록이 있습니다 (모델이 제안한 형식: timeline).",
                           detail="sections.3.kind: Input tag 'timeline' not found", unsupported_kinds=["timeline"])
    monkeypatch.setattr(service, "extract", boom)
    card_id = _upload(client, expected)
    page = client.get(f"/cards/{card_id}").text
    assert "지원하지 않는 형식" in page and "timeline" in page and "기술 정보" in page
    from app import db
    assert db.get_card(card_id)["error_detail"].startswith("sections.3.kind")


def test_structure_warning_shown(client, expected, monkeypatch):
    from app import service
    from tests.conftest import load_json

    class R:
        def __init__(self, data):
            self.data, self.model, self.input_tokens, self.output_tokens = data, "fake", 0, 0
    monkeypatch.setattr(service, "extract", lambda slices: R(load_json("glifos.payload.json")))
    monkeypatch.setattr(service, "verify", lambda o, d, p: R({"issues": [{"severity": "critical", "path": "_structure", "image_says": None, "json_says": None, "note": "블록이 합쳐졌을 수 있습니다"}], "lines": []}))
    card_id = _upload(client, expected)
    page = client.get(f"/cards/{card_id}").text
    assert "블록이 합쳐졌을 수 있습니다" in page and "기타 확인 항목" not in page


def test_duplicate_save_flow(client, expected):
    from app import db
    a = _upload(client, expected)
    assert client.post(f"/cards/{a}/save", json={}).status_code == 200
    b = _upload(client, expected)  # 같은 제품명+제형
    r = client.post(f"/cards/{b}/save", json={})
    assert r.status_code == 409 and r.json()["duplicate"]["id"] == a
    assert db.get_card(b)["status"] == "review"
    # 다른 이름으로 저장
    r = client.post(f"/cards/{b}/save", json={"product_name": "글리포스(신규)"})
    assert r.status_code == 200
    card = db.get_card(b)
    assert card["product_name"] == "글리포스(신규)" and card["status"] == "done"
    assert card["payload"]["header"]["product_name"] == "글리포스(신규)"
    # 경고 무시하고 저장 (force)
    c = _upload(client, expected)
    assert client.post(f"/cards/{c}/save", json={"force": True}).status_code == 200
    # 빈 이름은 거부
    d = _upload(client, expected)
    assert client.post(f"/cards/{d}/save", json={"product_name": "  "}).status_code == 400


def test_delete_draft(client, expected):
    from app import config, db
    a = _upload(client, expected)
    assert (config.STORAGE_DIR / a).exists()
    r = client.post(f"/cards/{a}/delete", follow_redirects=False)
    assert r.status_code == 303 and db.get_card(a) is None and not (config.STORAGE_DIR / a).exists()


def test_export_csv(client, expected):
    a = _upload(client, expected)
    client.post(f"/cards/{a}/save", json={})
    r = client.get("/export.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    import csv, io
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:4] == ["고유번호", "제품명", "제형", "회사명"]
    assert rows[1][0] == a and rows[1][1] == "글리포스" and rows[1][3] == "동구바이오제약"
    assert rows[1][6] == "done" and rows[1][8]  # 상태, 등록일
    assert '"header"' in rows[1][-1]  # payload JSON


def test_draft_delete_button_only_before_register(client, expected):
    a = _upload(client, expected)
    assert 'danger">초안 삭제' in client.get(f"/cards/{a}").text
    client.post(f"/cards/{a}/save", json={})
    page = client.get(f"/cards/{a}").text
    assert 'danger">초안 삭제' not in page
    assert "기존 항목 열기 (이 초안 삭제)" in page  # 중복 모달의 버튼 문구


def test_status_progress_fields(client, expected, monkeypatch):
    from app import db, service
    # 추출이 끝나지 않은 상태를 흉내: 큐에 넣지 않는다
    monkeypatch.setattr(service, "enqueue", lambda card_id: None)
    card_id = _upload(client, expected)
    j = client.get(f"/cards/{card_id}/status").json()
    assert j["status"] == "extracting" and j["elapsed"] >= 0
    assert j["expected"]["extract"] > 0 and j["expected"]["verify"] > 0
    page = client.get(f"/cards/{card_id}").text
    assert "이미지 준비" in page and "문구 대조" in page and 'id="barFill"' in page


def test_expected_durations_uses_measured_average(client, expected):
    from app import db
    a = _upload(client, expected)  # fake extract/verify 는 즉시 끝나므로 소요시간이 기록된다
    card = db.get_card(a)
    assert card["extract_seconds"] is not None and card["verify_seconds"] is not None
    exp = db.expected_durations()
    assert 0 <= exp["extract"] < 5 and 0 <= exp["verify"] < 5


def test_batch_upload_and_tabs(client, expected):
    png = fixture_png(expected, "glifos").read_bytes()
    r = client.post("/cards/batch", files=[("files", ("a.png", png, "image/png")), ("files", ("b.png", png, "image/png")),
                                          ("files", ("c.jpg", b"\xff\xd8", "image/jpeg"))], follow_redirects=False)
    from urllib.parse import unquote
    loc = unquote(r.headers["location"])
    assert r.status_code == 303 and "tab=processing" in loc and "2장" in loc and "c.jpg" in loc
    from app import db
    assert sum(1 for c in db.list_cards() if c["status"] == "review") == 2
    page = client.get("/?tab=review").text
    assert "검수 대기 <b>2</b>" in page and 'data-status="review"' in page
    assert "다중 등록" in client.get("/").text and "일괄 처리 시작" in client.get("/batch").text
    j = client.get("/cards/summary").json()
    assert j["counts"]["review"] == 2 and len(j["statuses"]) == 2


def test_batch_rejects_no_png(client):
    r = client.post("/cards/batch", files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert "PNG 파일이 없습니다" in r.text


def test_requeue_unfinished(client, expected, monkeypatch):
    from app import db, service
    a = _upload(client, expected)
    db.set_status(a, "verifying")
    queued = []
    monkeypatch.setattr(service, "enqueue", lambda cid: queued.append(cid))
    assert service.requeue_unfinished() == 1 and queued == [a]
    assert db.get_card(a)["status"] == "extracting"
