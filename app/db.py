"""SQLite 저장. 마이그레이션 도구 없이 CREATE TABLE IF NOT EXISTS 로 끝낸다."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator

from app import config

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id              TEXT PRIMARY KEY,
  status          TEXT NOT NULL,
  error           TEXT,
  product_name    TEXT,
  form            TEXT,
  insurance_code  TEXT,
  coverage        TEXT,
  payload         TEXT NOT NULL,
  payload_raw     TEXT NOT NULL,
  issues          TEXT,
  source_image    TEXT NOT NULL,
  model           TEXT,
  prompt_version  TEXT,
  template_version TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_code   ON cards(insurance_code);
CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status);
"""


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def init_db(path=None) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)
        # 기존 DB 에 뒤늦게 추가된 컬럼 (마이그레이션 도구 없이 여기서만 처리)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(cards)")}
        for name, ddl in [("error_detail", "TEXT"), ("company", "TEXT"), ("registered_at", "TEXT"), ("html_path", "TEXT"),
                          ("extract_seconds", "REAL"), ("verify_seconds", "REAL")]:
            if name not in cols:
                con.execute(f"ALTER TABLE cards ADD COLUMN {name} {ddl}")


@contextmanager
def connect(path=None) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(str(path or config.DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _row_to_card(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["payload"] = json.loads(d["payload"]) if d["payload"] else None
    d["payload_raw"] = json.loads(d["payload_raw"]) if d["payload_raw"] else None
    d["issues"] = json.loads(d["issues"]) if d["issues"] else {"issues": []}
    return d


def insert_card(card_id: str, source_image: str) -> None:
    ts = now_iso()
    with connect() as con:
        con.execute(
            "INSERT INTO cards (id, status, payload, payload_raw, source_image, created_at, updated_at)"
            " VALUES (?, 'extracting', '{}', '{}', ?, ?, ?)",
            (card_id, source_image, ts, ts))


def get_card(card_id: str) -> dict | None:
    with connect() as con:
        return _row_to_card(con.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone())


def list_cards(limit: int = 200) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, status, error, product_name, form, company, insurance_code, coverage, created_at, updated_at, registered_at,"
            " (SELECT COUNT(*) FROM json_each(cards.payload, '$.sections') WHERE json_extract(value, '$.layout_hint') IS NOT NULL) AS hint_count"
            " FROM cards ORDER BY COALESCE(registered_at, '') DESC, updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


COVERAGE_LABELS = {"both": "급여·비급여", "covered": "급여", "noncovered": "비급여", "selective": "선별급여"}


def coverage_from_badges(badges: list[dict] | None) -> str | None:
    """상단 배지에서 급여 구분을 판정한다. 배지 종류(kind)와 글자(text)를 모두 본다.
    급여+비급여가 같이 있으면 both. 정말 정보가 없을 때만 None."""
    from app.sanitize import plain_text
    covered = noncovered = selective = False
    for b in badges or []:
        kind = b.get("kind")
        text = plain_text(b.get("text")).replace(" ", "")
        if kind == "selective" or "선별급여" in text:
            selective = True
        if kind == "noncovered" or "비급여" in text:
            noncovered = True
        if kind == "covered" or kind == "mixed" or "급여" in text.replace("비급여", "").replace("선별급여", ""):
            covered = True
        if kind == "mixed":
            covered = noncovered = True
    if covered and noncovered:
        return "both"
    if covered:
        return "covered"
    if noncovered:
        return "noncovered"
    if selective:
        return "selective"
    return None


def _summary_columns(payload: dict) -> dict[str, Any]:
    """payload 에서 목록·후속 DB 설계용 컬럼을 뽑는다. 저장 시점에 한 번 동기화."""
    from app.sanitize import plain_text
    header = payload.get("header") or {}
    code = None
    for s in payload.get("sections") or []:
        if code:
            break
        if s.get("kind") == "spec_table":
            for r in s.get("rows") or []:
                if "보험코드" in (r.get("label") or ""):
                    code = plain_text(r.get("value")); break
        elif s.get("kind") == "variants":      # 규격별 카드는 첫 규격의 코드. 전체는 payload 에 있다
            for v in s.get("items") or []:
                for r in v.get("rows") or []:
                    if "보험코드" in (r.get("label") or ""):
                        code = plain_text(r.get("value")); break
                if code:
                    break
    coverage = coverage_from_badges(header.get("badges"))
    return dict(product_name=plain_text(header.get("product_name")),
                form=plain_text(header.get("form")) or None,
                company=plain_text(header.get("company")) or None,
                insurance_code=code, coverage=coverage)


def save_extracted(card_id: str, payload: dict, issues: dict, model: str, prompt_version: str,
                   extract_seconds: float | None = None, verify_seconds: float | None = None) -> None:
    cols = _summary_columns(payload)
    with connect() as con:
        con.execute(
            "UPDATE cards SET status='review', error=NULL, payload=?, payload_raw=?, issues=?,"
            " model=?, prompt_version=?, product_name=?, form=?, company=?, insurance_code=?, coverage=?,"
            " extract_seconds=?, verify_seconds=?, updated_at=?"
            " WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), json.dumps(payload, ensure_ascii=False),
             json.dumps(issues, ensure_ascii=False), model, prompt_version,
             cols["product_name"], cols["form"], cols["company"], cols["insurance_code"], cols["coverage"],
             extract_seconds, verify_seconds, now_iso(), card_id))


DEFAULT_EXTRACT_SECONDS = 75.0
DEFAULT_VERIFY_SECONDS = 45.0


def expected_durations(n: int = 20) -> dict[str, float]:
    """최근 n건의 실측 평균. 데이터가 없으면 기본값."""
    with connect() as con:
        r = con.execute(
            "SELECT AVG(extract_seconds) AS e, AVG(verify_seconds) AS v FROM ("
            " SELECT extract_seconds, verify_seconds FROM cards"
            " WHERE extract_seconds IS NOT NULL ORDER BY updated_at DESC LIMIT ?)", (n,)).fetchone()
    return {"extract": float(r["e"] or DEFAULT_EXTRACT_SECONDS), "verify": float(r["v"] or DEFAULT_VERIFY_SECONDS)}


def save_failed(card_id: str, error: str, detail: str | None = None) -> None:
    with connect() as con:
        con.execute("UPDATE cards SET status='failed', error=?, error_detail=?, updated_at=? WHERE id=?",
                    (error, detail, now_iso(), card_id))


def set_status(card_id: str, status: str) -> None:
    with connect() as con:
        con.execute("UPDATE cards SET status=?, updated_at=? WHERE id=?", (status, now_iso(), card_id))


def save_payload(card_id: str, payload: dict) -> None:
    cols = _summary_columns(payload)
    with connect() as con:
        con.execute(
            "UPDATE cards SET payload=?, product_name=?, form=?, company=?, insurance_code=?, coverage=?, updated_at=?"
            " WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), cols["product_name"], cols["form"], cols["company"],
             cols["insurance_code"], cols["coverage"], now_iso(), card_id))


def save_rendered(card_id: str, template_version: str, html_path: str | None = None) -> None:
    """HTML 을 만들었을 때 호출. 상태는 바꾸지 않는다 (등록은 register 로)."""
    with connect() as con:
        con.execute("UPDATE cards SET template_version=?, html_path=COALESCE(?, html_path), updated_at=? WHERE id=?",
                    (template_version, html_path, now_iso(), card_id))


def register(card_id: str, template_version: str, html_path: str) -> None:
    """저장(등록). 처음이면 registered_at 을 찍고, 이후에는 수정일만 갱신한다."""
    ts = now_iso()
    with connect() as con:
        con.execute("UPDATE cards SET status='done', template_version=?, html_path=?,"
                    " registered_at=COALESCE(registered_at, ?), updated_at=? WHERE id=?",
                    (template_version, html_path, ts, ts, card_id))


def resync_summary_columns() -> int:
    """모든 카드의 요약 컬럼(제품명·제형·회사명·보험코드·급여구분)을 payload 로부터 다시 계산한다."""
    with connect() as con:
        rows = con.execute("SELECT id, payload FROM cards WHERE payload != '{}'").fetchall()
    for r in rows:
        save_payload(r["id"], json.loads(r["payload"]))
    return len(rows)


def unfinished_card_ids() -> list[str]:
    with connect() as con:
        return [r["id"] for r in con.execute("SELECT id FROM cards WHERE status IN ('extracting','verifying') ORDER BY id")]


def status_summary() -> dict:
    with connect() as con:
        rows = con.execute("SELECT id, status FROM cards").fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"counts": counts, "statuses": {r["id"]: r["status"] for r in rows}}


def find_registered_duplicate(product_name: str, form: str | None, exclude_id: str) -> dict | None:
    """등록 완료된 카드 중 제품명+제형이 같은 것."""
    with connect() as con:
        r = con.execute(
            "SELECT id, product_name, form, company, registered_at FROM cards"
            " WHERE status='done' AND id != ? AND product_name = ? AND COALESCE(form,'') = COALESCE(?, '')"
            " ORDER BY registered_at DESC LIMIT 1", (exclude_id, product_name, form)).fetchone()
        return dict(r) if r else None


def delete_card(card_id: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM cards WHERE id=?", (card_id,))


def all_cards_for_export() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, product_name, form, company, insurance_code, coverage, status, created_at, registered_at,"
            " updated_at, html_path, model, prompt_version, template_version, payload FROM cards ORDER BY id").fetchall()
        return [dict(r) for r in rows]
