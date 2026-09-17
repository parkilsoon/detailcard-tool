"""FastAPI 진입점. 실행: uv run uvicorn app.main:app --reload --port 8765"""
from __future__ import annotations

import csv
import io
import json
import logging

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db, service
from app.fields import build_groups, critical_count, flagged_count, missing_lines, structure_warning
from app.paths import path_get, path_set
from app.renderer import app_env, render_card
from app.sanitize import strip_disallowed_tags
from app.schema import validate_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="디테일카드 모바일 변환 툴")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = app_env()


@app.on_event("startup")
def _startup() -> None:
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    service.requeue_unfinished()


def _render(name: str, **ctx) -> HTMLResponse:
    return HTMLResponse(templates.get_template(f"app/{name}").render(**ctx))


def _card_or_404(card_id: str) -> dict:
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "카드를 찾을 수 없습니다.")
    return card


# ---------- 화면 ----------

@app.get("/", response_class=HTMLResponse)
def index(tab: str = "all", msg: str | None = None):
    cards = db.list_cards()
    counts = {"processing": 0, "review": 0, "done": 0, "failed": 0}
    for c in cards:
        key = "processing" if c["status"] in ("extracting", "verifying") else c["status"]
        counts[key] = counts.get(key, 0) + 1
    return _render("index.html", cards=cards, counts=counts, tab=tab, msg=msg)


@app.get("/cards/summary")
def cards_summary():
    return db.status_summary()


@app.get("/new", response_class=HTMLResponse)
def new_card():
    return _render("new.html")


@app.get("/batch", response_class=HTMLResponse)
def batch_page():
    return _render("batch.html", max_files=config.BATCH_MAX_FILES)


@app.post("/cards")
async def upload(file: UploadFile):
    data = await file.read()
    if not data or not data.startswith(b"\x89PNG"):
        return _render("new.html", error="PNG 파일만 올릴 수 있습니다.")
    card_id = service.create_card(data)
    service.enqueue(card_id)
    return RedirectResponse(f"/cards/{card_id}", status_code=303)


@app.post("/cards/batch")
async def upload_batch(files: list[UploadFile]):
    """여러 장을 한 번에 올려 작업자 풀에서 처리한다. 끝난 카드는 목록에 '검수 중' 으로 쌓인다."""
    if len(files) > config.BATCH_MAX_FILES:
        return _render("batch.html", max_files=config.BATCH_MAX_FILES,
                       error=f"한 번에 {config.BATCH_MAX_FILES}장까지 올릴 수 있습니다. ({len(files)}장 선택됨)")
    accepted, skipped = 0, []
    for f in files:
        data = await f.read()
        if not data or not data.startswith(b"\x89PNG"):
            skipped.append(f.filename or "(이름 없음)")
            continue
        service.enqueue(service.create_card(data))
        accepted += 1
    if accepted == 0:
        return _render("batch.html", max_files=config.BATCH_MAX_FILES, error="PNG 파일이 없습니다.")
    msg = f"{accepted}장을 처리하기 시작했습니다."
    if skipped:
        msg += f" PNG 가 아닌 {len(skipped)}개는 건너뛰었습니다: {', '.join(skipped[:5])}"
    return RedirectResponse(f"/?tab=processing&msg={msg}", status_code=303)


@app.get("/cards/{card_id}", response_class=HTMLResponse)
def review(card_id: str):
    card = _card_or_404(card_id)
    groups = build_groups(card["payload"], card["issues"]) if card["status"] in ("review", "done") else []
    return _render("review.html", card=card, groups=groups,
                   flagged=flagged_count(groups), critical=critical_count(groups),
                   missing=missing_lines(card["issues"]) if card["status"] in ("review", "done") else [],
                   structure=structure_warning(card["issues"]),
                   verify_error=(card["issues"] or {}).get("error"))


@app.get("/cards/{card_id}/status")
def status(card_id: str):
    card = _card_or_404(card_id)
    n_issues = len((card["issues"] or {}).get("issues") or [])
    out = {"status": card["status"], "error": card["error"], "issue_count": n_issues}
    if card["status"] in ("extracting", "verifying"):
        from datetime import datetime
        since = datetime.fromisoformat(card["updated_at"])
        out["elapsed"] = max(0.0, (datetime.now(since.tzinfo) - since).total_seconds())
        out["expected"] = db.expected_durations()
    return out


class FieldPatch(BaseModel):
    path: str
    value: str | None


@app.patch("/cards/{card_id}/field")
def patch_field(card_id: str, body: FieldPatch):
    card = _card_or_404(card_id)
    if card["status"] not in ("review", "done"):
        raise HTTPException(409, "아직 추출이 끝나지 않았습니다.")
    payload = card["payload"]
    try:
        current = path_get(payload, body.path)
    except KeyError:
        raise HTTPException(400, "수정할 수 없는 항목입니다.")
    if not isinstance(current, (str, type(None))):
        raise HTTPException(400, "수정할 수 없는 항목입니다.")
    value = body.value
    if value is not None:
        value = strip_disallowed_tags(value)
        if len(value) > config.FIELD_MAX_LEN:
            raise HTTPException(400, f"{config.FIELD_MAX_LEN}자를 넘을 수 없습니다.")
        if value.strip() == "":
            value = None
    path_set(payload, body.path, value)
    try:
        validate_payload(payload)
    except Exception:
        raise HTTPException(400, "이 항목은 비워둘 수 없습니다.")
    if card["status"] == "done":
        db.set_status(card_id, "review")  # 수정했으면 다시 내려받아야 한다
    db.save_payload(card_id, payload)
    return {"ok": True, "path": body.path, "value": value}


@app.get("/cards/{card_id}/preview", response_class=HTMLResponse)
def preview(card_id: str):
    card = _card_or_404(card_id)
    if card["status"] not in ("review", "done"):
        raise HTTPException(409, "아직 추출이 끝나지 않았습니다.")
    return HTMLResponse(render_card(card["payload"]))


@app.get("/cards/{card_id}/download")
def download(card_id: str):
    card = _card_or_404(card_id)
    if card["status"] not in ("review", "done"):
        raise HTTPException(409, "아직 추출이 끝나지 않았습니다.")
    out = service.render_and_store(card)
    return FileResponse(out, media_type="text/html", filename=service.download_name(card))


class SaveBody(BaseModel):
    force: bool = False              # 중복 경고를 보고도 저장
    product_name: str | None = None  # "다른 이름으로 저장" 시 새 제품명


@app.post("/cards/{card_id}/save")
def save_card(card_id: str, body: SaveBody | None = None):
    """저장(등록). 제품명+제형이 이미 등록된 것과 겹치면 409 로 기존 항목을 알려준다."""
    body = body or SaveBody()
    card = _card_or_404(card_id)
    if card["status"] not in ("review", "done"):
        raise HTTPException(409, "아직 추출이 끝나지 않았습니다.")
    payload = card["payload"]
    if body.product_name is not None:
        name = strip_disallowed_tags(body.product_name).strip()
        if not name:
            raise HTTPException(400, "제품명을 입력해 주세요.")
        payload["header"]["product_name"] = name
        db.save_payload(card_id, payload)
        card = _card_or_404(card_id)
    dup = db.find_registered_duplicate(card["product_name"], card["form"], exclude_id=card_id)
    if dup and not body.force:
        return JSONResponse({"ok": False, "duplicate": dup}, status_code=409)
    out = service.register(card)
    fresh = db.get_card(card_id)
    return {"ok": True, "id": card_id, "registered_at": fresh["registered_at"], "updated_at": fresh["updated_at"],
            "html_path": fresh["html_path"], "download": f"/cards/{card_id}/download"}


@app.post("/cards/{card_id}/delete")
def delete_card(card_id: str):
    card = _card_or_404(card_id)
    if card["status"] == "done":
        raise HTTPException(409, "등록된 항목은 삭제할 수 없습니다.")
    service.delete_card(card)
    return RedirectResponse("/", status_code=303)


@app.get("/export.csv")
def export_csv():
    cols = ["id", "product_name", "form", "company", "insurance_code", "coverage", "status", "created_at",
            "registered_at", "updated_at", "html_path", "model", "prompt_version", "template_version", "payload"]
    labels = ["고유번호", "제품명", "제형", "회사명", "보험코드", "급여구분", "상태", "업로드일", "등록일", "수정일",
              "HTML 경로", "모델", "프롬프트 버전", "템플릿 버전", "데이터(JSON)"]
    buf = io.StringIO()
    buf.write("\ufeff")  # 엑셀에서 한글이 깨지지 않게 BOM
    w = csv.writer(buf)
    w.writerow(labels)
    for r in db.all_cards_for_export():
        w.writerow([r.get(c) if r.get(c) is not None else "" for c in cols])
    fname = f"detailcards_{db.now_iso()[:10]}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/cards/{card_id}/export.json")
def export_json(card_id: str):
    card = _card_or_404(card_id)
    body = json.dumps(card["payload"], ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{card_id}.json"'})


@app.post("/cards/{card_id}/reextract")
def reextract(card_id: str):
    _card_or_404(card_id)
    db.set_status(card_id, "extracting")
    service.enqueue(card_id)
    return RedirectResponse(f"/cards/{card_id}", status_code=303)


@app.get("/cards/{card_id}/original.png")
def original(card_id: str):
    _card_or_404(card_id)
    p = service.card_dir(card_id) / "original.png"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    if request.url.path.endswith(("/field", "/status", "/save")):
        return JSONResponse({"ok": False, "detail": exc.detail}, status_code=exc.status_code)
    return HTMLResponse(f"<p style='font-family:sans-serif;padding:40px'>{exc.detail}</p>", status_code=exc.status_code)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
