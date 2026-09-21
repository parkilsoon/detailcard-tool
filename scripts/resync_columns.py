"""기존 DB 의 요약 컬럼(제품명·제형·회사명·보험코드·급여구분)을 payload 에서 다시 계산한다.
급여 판정 규칙이 바뀌었을 때 등. payload 자체는 바꾸지 않는다.
실행: uv run python scripts/resync_columns.py   (서버를 멈춘 뒤)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402

db.init_db()
n = db.resync_summary_columns()
with db.connect() as con:
    rows = con.execute("SELECT coverage, COUNT(*) AS n FROM cards GROUP BY coverage").fetchall()
print(f"{n}건 재계산. 급여구분 분포: " + ", ".join(f"{db.COVERAGE_LABELS.get(r['coverage'], r['coverage'] or '없음')} {r['n']}" for r in rows))
