"""기존 DB 의 제품명에 단일 제형을 붙인다 ("구세" + "정" → "구세정"). payload_raw 는 건드리지 않는다.
실행: uv run python scripts/migrate_product_names.py   (서버를 멈춘 뒤)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402
from app.extractor import normalize_product_name  # noqa: E402

db.init_db()
with db.connect() as con:
    rows = con.execute("SELECT id, payload FROM cards WHERE payload != '{}'").fetchall()
changed = 0
for r in rows:
    payload = json.loads(r["payload"])
    before = payload["header"].get("product_name")
    normalize_product_name(payload)
    if payload["header"].get("product_name") != before:
        db.save_payload(r["id"], payload)
        changed += 1
        print(f"{r['id']}: {before} → {payload['header']['product_name']}")
print(f"{len(rows)}건 중 {changed}건 변경")
