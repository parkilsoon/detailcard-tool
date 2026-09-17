# 디테일카드 모바일 변환 툴

PC용 제약 디테일카드 PNG → LLM 전사(JSON) → 원본 대조 검수 → 모바일 HTML 다운로드. 로컬 실행형 독립 툴.

## 실행

서버 배포는 [DEPLOY.md](DEPLOY.md) 참고.

```bash
uv sync
cp .env.example .env        # ANTHROPIC_API_KEY 입력
uv run uvicorn app.main:app --reload --port 8765
```

브라우저에서 http://127.0.0.1:8765 접속.

## 화면 흐름

1. **목록** (`/`): 제품명·회사명·상태·등록일·수정일. "새로 등록", "데이터 출력 (CSV)" 버튼. 초안(저장 전)은 삭제 가능.
2. **새로 등록** (`/new`): PNG 드래그 앤 드롭 → 추출·검증(1~2분) → 검수 화면.
   **다중 등록** (`/batch`): 여러 장을 한 번에 올리면 작업자 풀(`PIPELINE_WORKERS`, 기본 3)에서 동시 처리되고
   끝난 카드는 목록에 "검수 중" 으로 쌓인다. 목록은 처리 중인 카드가 있으면 자동 갱신되고 상태 탭으로 거를 수 있다.
   서버가 재시작되면 처리 도중이던 카드는 자동으로 다시 큐에 들어간다.
3. **검수** (`/cards/{id}`): 원본 옆에서 인라인 수정(자동 저장) → **저장** 을 누르면 등록. 제품명+제형이 이미 등록된 것과 겹치면
   "기존 항목 열기 / 다른 이름으로 저장" 을 고르게 한다. 저장 시 DB 컬럼을 확정하고 `storage/{id}/mobile.html` 을 쓴다.
4. **CSV** (`/export.csv`): DB 컬럼 전부 + 마지막 열에 payload JSON. 엑셀용 BOM 포함.

## 구조

```
app/
  main.py       FastAPI 라우트
  config.py     환경변수
  db.py         SQLite (data.db). CREATE TABLE IF NOT EXISTS 로 초기화
  schema.py     JSON 스키마 v1 (pydantic) — 유일한 원본
  paths.py      path_get / path_set / iter_strings
  slicer.py     Pillow 전처리 (리사이즈 → 세로 슬라이스, 15% 겹침)
  extractor.py  LLM 호출 #1 추출 + 후처리 (프로바이더 무관)
  verify.py     검증 = 다른 슬라이스 규격으로 2차 독립 전사 → 코드 diff → 다른 필드만 "확인 필요"
  providers/    anthropic_provider.py, gemini_provider.py — .env 의 LLM_PROVIDER 로 선택
  sanitize.py   이스케이프 + <em> 화이트리스트
  renderer.py   Jinja2 → mobile.html (CSS 인라인 단일 파일)
  fields.py     검수 화면용 한국어 라벨 필드 목록
  service.py    업로드 → 파이프라인 → 저장
prompts/        extract_v1.txt
templates/app/  툴 UI (index, review)
templates/card/ 카드 템플릿 (base + kind별 부분 템플릿)
static/         card.css (카드 공용), app.css, app.js
storage/{id}/   original.png, slices/, mobile.html
tests/          단위 테스트 + 골든 픽스처
scripts/        seed_fixture.py (키 없이 화면 확인), run_golden.py (실제 LLM 골든 테스트)
```

## CLI 로 단계별 확인

```bash
uv run python -m app.slicer "<png>" out_dir            # 슬라이스 결과 확인
uv run python -m app.extractor "<png>" out_dir         # 추출 + 검증 (API 키 필요)
uv run python -m app.renderer payload.json out.html    # 렌더
uv run python scripts/seed_fixture.py glifos           # 손 전사 payload 로 카드 시드 (키 없이 UI 확인)
```

## 스키마 v2 와 새 레이아웃 대응

124장 실측에서 기존 5종으로 표현되는 카드는 27% 뿐이었다. v2 는 `variants`(규격별 박스), `text_box`, `table` 을 더하고
notice/callouts/points/icd 를 확장해 전부 표현한다. 어떤 kind 에도 안 맞는 블록은 `text_box`/`table` 로 반드시 담고(화면에서는 "임시 서식")
`layout_hint` 에 원래 모양을 적게 했다. `scripts/layout_report.py` 로 힌트를 집계해 반복되는 것을 정식 kind 로 승격한다.

## 검증 방식

LLM 에게 1차 결과의 오류를 찾게 하는 방식은 실측에서 실제 오류를 잡지 못하고 오탐만 냈다.
기본(`VERIFY_MODE=lines`)은 이미지의 모든 문구를 구조 없이 한 줄씩 나열시킨 뒤 코드로 대조한다.
결과에 그대로 있으면 통과, 비슷한 칸이 있으면 그 칸에 "확인 필요" + 이미지 문구, 어디에도 없으면 화면 상단 "빠진 문구" 목록.
`VERIFY_MODE=structured` 는 다른 슬라이스 높이로 2차 구조화 전사 후 필드 diff. 숫자·코드·용법·금기 문구 필드는 "주의항목"으로 표시해 일치해도 항상 대조를 요구한다.

## 테스트

```bash
uv run pytest                      # 단위·라우트 테스트 (LLM 호출 없음)
uv run python scripts/run_golden.py && uv run pytest tests/test_golden.py   # 수용 기준 12.1~12.3 (API 키 필요)
```

골든 픽스처 PNG 위치는 `FIXTURE_PNG_DIR` 환경변수로 지정한다 (기본: `~/Downloads/drive-download-20260916T062937Z-1-001`).

## 환경변수

`.env.example` 참조.

| 변수 | 설명 |
|---|---|
| `LLM_PROVIDER` | `anthropic` 또는 `gemini`. 이 값 하나로 SDK·기본 모델·슬라이스 규칙이 바뀐다 |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | 쓰는 프로바이더의 키만 채운다 |
| `LLM_MODEL` | 비우면 `claude-opus-5` / `gemini-2.5-pro` |
| `SLICE_HEIGHT` | 슬라이스 높이 직접 지정. 비우면 anthropic 은 패치 공식(840px), gemini 는 768px |
| `VERIFY_SLICE_HEIGHT` | 2차 전사용 슬라이스 높이. 비우면 1차의 2배 |
| `LLM_TEMPERATURE` | gemini 는 비우면 0. anthropic 현행 모델은 거부하므로 비워둔다 |

두 키를 모두 넣어두면 `LLM_PROVIDER` 만 바꿔 같은 카드로 A/B 비교할 수 있다.
