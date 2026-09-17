"""스키마 v2 실측: 지정한 PNG 들을 추출 + 검증(lines)하고 요약을 출력한다.
실행: uv run python scripts/run_samples.py "DKBP 베이드크림 디테일카드.png" ...   (이름만, PNG_DIR 기준)
결과: tests/fixtures/extracted/samples/<stem>.json / <stem>.issues.json"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.extractor import ExtractError, extract  # noqa: E402
from app.slicer import prepare  # noqa: E402
from app.verify import MISSING_PREFIX, verify  # noqa: E402
from tests.conftest import PNG_DIR  # noqa: E402

out_dir = Path("tests/fixtures/extracted/samples"); out_dir.mkdir(parents=True, exist_ok=True)
for name in sys.argv[1:]:
    png = PNG_DIR / name
    stem = png.stem.replace("DKBP ", "").replace(" 디테일카드", "")
    t0 = time.time()
    try:
        slices = prepare(png, out_dir / f"_{stem}_slices")
        r1 = extract(slices)
        (out_dir / f"{stem}.json").write_text(json.dumps(r1.data, ensure_ascii=False, indent=2), encoding="utf-8")
        r2 = verify(png, out_dir / f"_{stem}_slices_verify", r1.data)
        (out_dir / f"{stem}.issues.json").write_text(json.dumps(r2.data, ensure_ascii=False, indent=2), encoding="utf-8")
    except ExtractError as e:
        print(f"## {stem}: 실패 — {e}"); continue
    kinds = [s["kind"] for s in r1.data["sections"]]
    hints = [(s["kind"], s.get("layout_hint")) for s in r1.data["sections"] if s.get("layout_hint")]
    issues = r2.data["issues"]
    missing = [i for i in issues if i["path"].startswith(MISSING_PREFIX)]
    flagged = [i for i in issues if not i["path"].startswith(MISSING_PREFIX)]
    print(f"## {stem}  ({time.time()-t0:.0f}s, tokens {r1.input_tokens}+{r1.output_tokens} / {r2.input_tokens}+{r2.output_tokens})")
    print(f"   kinds: {' > '.join(kinds)}")
    print(f"   uncertain: {r1.data['uncertain']}")
    print(f"   layout_hint: {hints or '없음'}")
    print(f"   문구 목록 {len(r2.data.get('lines', []))}줄 → 빠진 문구 {len(missing)}건, 확인 필요 {len(flagged)}건")
    for m in missing:
        print(f"     [빠짐] {m['image_says']}")
    for f in flagged:
        print(f"     [확인] {f['path']} | 결과: {str(f['json_says'])[:50]} | 이미지: {str(f['image_says'])[:50]}")
