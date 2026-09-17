"""임시 서식 리포트. DB 에 쌓인 payload 에서 text_box / table 로 담긴(임시 서식) 섹션과 layout_hint 를 집계한다.
같은 힌트가 반복해서 쌓이면 정식 kind 로 승격할 후보다.
실행: uv run python scripts/layout_report.py"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402

hints: dict[str, list[str]] = defaultdict(list)
kinds = Counter()
with db.connect() as con:
    rows = con.execute("SELECT id, product_name, payload FROM cards WHERE status IN ('review','done')").fetchall()
    failed = con.execute("SELECT id, error FROM cards WHERE status='failed' AND error LIKE '%지원하지 않는 형식%'").fetchall()
for r in rows:
    p = json.loads(r["payload"])
    for s in p.get("sections", []):
        kinds[s["kind"]] += 1
        if s.get("layout_hint"):
            hints[f'{s["kind"]}: {s["layout_hint"]}'].append(r["product_name"] or r["id"])
print(f"카드 {len(rows)}건 · 섹션 kind 분포: {dict(kinds)}")
print(f"임시 서식(layout_hint) 섹션 {sum(len(v) for v in hints.values())}건, 종류 {len(hints)}개\n")
for h, cards in sorted(hints.items(), key=lambda kv: -len(kv[1])):
    print(f"[{len(cards)}건] {h}\n        ← {', '.join(cards[:8])}{' …' if len(cards) > 8 else ''}")

if failed:
    print(f"\n지원하지 않는 형식으로 실패한 카드 {len(failed)}건 (모델이 제안한 kind 이름):")
    for r in failed:
        print(f"  {r['id']}: {r['error']}")
