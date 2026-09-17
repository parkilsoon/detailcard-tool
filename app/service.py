"""업로드 → 전처리 → 추출 → 검증 → 저장 파이프라인. 백그라운드 태스크에서 돈다."""
from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ulid import ULID

from app import config, db
from app.extractor import ExtractError, extract
from app.verify import verify
from app.renderer import TEMPLATE_VERSION, render_card
from app.slicer import TooManySlices, prepare

log = logging.getLogger("detailcard")

_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=config.PIPELINE_WORKERS, thread_name_prefix="pipeline")
    return _executor


def enqueue(card_id: str) -> None:
    """추출 파이프라인을 작업자 풀에 넣는다. 단건·다중 등록 모두 이 경로를 쓴다."""
    _pool().submit(run_pipeline, card_id)


def requeue_unfinished() -> int:
    """서버가 재시작되면 '추출 중/검증 중' 에 멈춘 카드를 다시 큐에 넣는다."""
    ids = db.unfinished_card_ids()
    for cid in ids:
        db.set_status(cid, "extracting")
        enqueue(cid)
    if ids:
        log.info("requeued %d unfinished cards", len(ids))
    return len(ids)


def card_dir(card_id: str) -> Path:
    return config.STORAGE_DIR / card_id


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(config.ROOT))
    except ValueError:
        return str(p)


def create_card(png_bytes: bytes) -> str:
    card_id = str(ULID())
    d = card_dir(card_id)
    d.mkdir(parents=True, exist_ok=False)
    original = d / "original.png"
    original.write_bytes(png_bytes)
    db.insert_card(card_id, _rel(original))
    return card_id


def run_pipeline(card_id: str) -> None:
    d = card_dir(card_id)
    original = d / "original.png"
    try:
        slices_dir = d / "slices"
        if slices_dir.exists():
            shutil.rmtree(slices_dir)
        slices = prepare(original, slices_dir)
        t0 = time.monotonic()
        r1 = extract(slices)
        extract_seconds = time.monotonic() - t0
        payload = r1.data
        payload["meta"] = {
            "card_id": card_id,
            "source_image": _rel(original),
            "slice_count": len(slices),
            "extracted_at": db.now_iso(),
            "model": r1.model,
            "prompt_version": config.EXTRACT_PROMPT_VERSION,
        }
        db.set_status(card_id, "verifying")
        t1 = time.monotonic()
        try:
            issues = verify(original, d / "slices_verify", payload).data
        except ExtractError as e:
            # 검증이 실패해도 추출 결과는 살린다. 화면에는 검증 미완료로 표시.
            log.warning("verify failed for %s: %s", card_id, e)
            issues = {"issues": [], "error": str(e)}
        verify_seconds = time.monotonic() - t1
        db.save_extracted(card_id, payload, issues, r1.model, config.EXTRACT_PROMPT_VERSION,
                          extract_seconds=extract_seconds, verify_seconds=verify_seconds)
    except TooManySlices as e:
        db.save_failed(card_id, str(e))
    except ExtractError as e:
        if e.unsupported_kinds:
            log.warning("unsupported kinds on %s: %s", card_id, e.unsupported_kinds)
        db.save_failed(card_id, str(e), e.detail)
    except Exception as e:  # noqa: BLE001 — 백그라운드에서 죽으면 화면이 영원히 대기한다
        log.exception("pipeline crashed for %s", card_id)
        db.save_failed(card_id, "처리 중 오류가 났습니다. 다시 시도해 주세요.", f"{type(e).__name__}: {e}")


def render_and_store(card: dict) -> Path:
    html = render_card(card["payload"])
    out = card_dir(card["id"]) / "mobile.html"
    out.write_text(html, encoding="utf-8")
    db.save_rendered(card["id"], TEMPLATE_VERSION, _rel(out))
    return out


def register(card: dict) -> Path:
    """저장(등록): HTML 을 고유번호 폴더에 쓰고 DB 컬럼을 확정한다."""
    db.save_payload(card["id"], card["payload"])   # 제품명·회사명·보험코드 등 요약 컬럼을 payload 와 동기화
    html = render_card(card["payload"])
    out = card_dir(card["id"]) / "mobile.html"
    out.write_text(html, encoding="utf-8")
    db.register(card["id"], TEMPLATE_VERSION, _rel(out))
    return out


def delete_card(card: dict) -> None:
    d = card_dir(card["id"])
    if d.exists():
        shutil.rmtree(d)
    db.delete_card(card["id"])


def download_name(card: dict) -> str:
    name = (card.get("product_name") or card["id"]).replace("/", "_")
    form = card.get("form") or ""
    return f"{name}{form}_mobile.html"
