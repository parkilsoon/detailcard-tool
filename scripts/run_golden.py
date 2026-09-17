"""골든 픽스처 2건을 실제 LLM 으로 추출·검증해 tests/fixtures/extracted/ 에 저장한다.
실행: uv run python scripts/run_golden.py   (ANTHROPIC_API_KEY 필요, 픽스처 PNG 는 FIXTURE_PNG_DIR 또는 Downloads)
이후 uv run pytest tests/test_golden.py 로 수용 기준 12.1~12.3 을 검사한다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.extractor import extract  # noqa: E402
from app.verify import verify  # noqa: E402
from app.slicer import prepare  # noqa: E402
from tests.conftest import PNG_DIR, load_json  # noqa: E402

out_dir = Path("tests/fixtures/extracted")
out_dir.mkdir(parents=True, exist_ok=True)
expected = load_json("expected.json")
names = sys.argv[1:] or list(expected)
for name in names:
    png = PNG_DIR / expected[name]["png"]
    slices = prepare(png, out_dir / f"_{name}_slices")
    r1 = extract(slices)
    (out_dir / f"{name}.json").write_text(json.dumps(r1.data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{name}: extract ok (in={r1.input_tokens} out={r1.output_tokens})")
    r2 = verify(png, out_dir / f"_{name}_slices_verify", r1.data)
    (out_dir / f"{name}.issues.json").write_text(json.dumps(r2.data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{name}: verify ok, issues={len(r2.data['issues'])}")
    for it in r2.data["issues"]:
        print("   ", it["severity"], it["path"], "| 1차:", it.get("json_says"), "→ 2차:", it.get("image_says"))
