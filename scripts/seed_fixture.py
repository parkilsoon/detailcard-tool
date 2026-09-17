"""API 키 없이 화면을 확인하기 위한 시드. 실제 추출 결과(tests/fixtures/extracted/samples/<stem>.json)가 있으면
그것과 검증 이슈를 그대로 심고, 없으면 손 전사 payload(guse|glifos)로 심는다.
실행: uv run python scripts/seed_fixture.py "구세정" | "더모타손MLE로션" | guse | glifos ..."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, db, service  # noqa: E402
from app.slicer import prepare  # noqa: E402
from tests.conftest import PNG_DIR  # noqa: E402

ALIAS = {"guse": "구세정", "glifos": "글리포스연질캡슐"}
SAMPLES = Path("tests/fixtures/extracted/samples")

config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()
for arg in sys.argv[1:]:
    stem = ALIAS.get(arg, arg)
    png = PNG_DIR / f"DKBP {stem} 디테일카드.png"
    real, real_issues = SAMPLES / f"{stem}.json", SAMPLES / f"{stem}.issues.json"
    if real.exists():
        payload = json.loads(real.read_text())
        issues = json.loads(real_issues.read_text()) if real_issues.exists() else {"issues": []}
        src = "실제 추출 결과"
    else:
        payload = json.loads(Path(f"tests/fixtures/{arg}.payload.json").read_text())
        issues = {"issues": []}
        src = "손 전사 payload"
    card_id = service.create_card(png.read_bytes())
    d = service.card_dir(card_id)
    slices = prepare(d / "original.png", d / "slices")
    payload["meta"] = {"card_id": card_id, "source_image": str(d / "original.png"), "slice_count": len(slices),
                       "extracted_at": db.now_iso(), "model": "seed", "prompt_version": config.EXTRACT_PROMPT_VERSION}
    db.save_extracted(card_id, payload, issues, "seed", config.EXTRACT_PROMPT_VERSION)
    print(f"{stem}: {card_id} ({src}, 이슈 {len(issues['issues'])}건)")
