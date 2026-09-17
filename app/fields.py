"""검수 화면용 필드 목록. JSON 경로를 한국어 라벨로 바꿔서 화면에 낸다.
화면에는 라벨만 보이고, 경로는 title 속성에만 숨긴다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from app.paths import path_get

MISSING_PREFIX = "_missing."


@dataclass
class Field:
    path: str
    label: str
    value: str | None
    multiline: bool = False
    flagged: bool = False          # uncertain 또는 issues 에 걸림
    image_says: str | None = None  # 검증에서 잡힌 경우 이미지 원문
    note: str | None = None
    severity: str | None = None
    anchor: float = 0.0            # 원본 이미지에서의 대략적 세로 위치 (0~1)
    critical_rule: bool = False    # 주의항목: 숫자·코드·용법·금기 문구 등 항상 원본과 대조해야 하는 필드 (규칙 기반)
    snippets: list = field(default_factory=list)  # 긴 값일 때 1차/2차가 다른 구간 발췌


@dataclass
class Group:
    title: str
    fields: list[Field] = field(default_factory=list)
    hint: str | None = None        # layout_hint: 임시 서식(text_box/table)으로 담긴 섹션이면 원래 모양 설명


_CALLOUT_LABEL = {"lead": "핵심 문장", "note": "하단 문구"}
_CRITICAL_LABELS = ("함량", "규격", "보험코드", "약가", "환자부담", "저장", "유효", "출하가", "코드")
_CRITICAL_TEXT = re.compile(r"\d+(\.\d+)?\s*배|p\s*[<=]|N\s*=|\d+%|\d{4}년?|제\d{4}-\d+호")
_LONG = 60


def _issue_map(issues: dict | None) -> dict[str, dict]:
    m: dict[str, dict] = {}
    for it in (issues or {}).get("issues") or []:
        if it["path"] not in m or it.get("severity") == "critical":
            m[it["path"]] = it
    return m


def structure_warning(issues: dict | None) -> str | None:
    for it in (issues or {}).get("issues") or []:
        if it["path"] == "_structure":
            return it.get("note")
    return None


def missing_lines(issues: dict | None) -> list[dict]:
    """결과 어디에도 없는 문구 목록 (검증 lines 모드)."""
    return [it for it in (issues or {}).get("issues") or [] if it["path"].startswith(MISSING_PREFIX)]


def build_groups(payload: dict, issues: dict | None) -> list[dict]:
    issue_map = _issue_map(issues)
    uncertain = set(payload.get("uncertain") or [])
    groups: list[Group] = []

    def add(g: Group, path: str, label: str, multiline: bool = False, anchor: float = 0.0,
            critical: bool = False):
        val = path_get(payload, path, default=None)
        if isinstance(val, bool):
            return
        f = Field(path, label, val, multiline or bool(val and len(val) > _LONG), anchor=anchor)
        f.critical_rule = critical or bool(val and _CRITICAL_TEXT.search(val))
        if path in uncertain:
            f.flagged = True
            f.note = "판독이 불확실하다고 표시된 항목입니다. 원본과 대조해 주세요."
        if path in issue_map:
            it = issue_map[path]
            f.flagged = True
            f.image_says = it.get("image_says")
            f.severity = it.get("severity")
            f.note = it.get("note")
            if f.image_says and val and (len(val) > _LONG or len(f.image_says) > _LONG):
                from app.verify import diff_snippets
                f.snippets = diff_snippets(val, f.image_says)
        g.fields.append(f)

    h = Group("제품 기본 정보")
    add(h, "header.company", "회사명", anchor=0.02)
    add(h, "header.product_name", "제품명", anchor=0.02)
    add(h, "header.form", "제형", anchor=0.02)
    add(h, "header.ingredient", "성분·함량", anchor=0.04, critical=True)
    add(h, "header.category", "분류", anchor=0.05)
    for i, b in enumerate(payload["header"].get("badges") or []):
        add(h, f"header.badges.{i}.text", f"배지 {i + 1}", anchor=0.03, critical=True)
    groups.append(h)

    n_sections = max(1, len(payload["sections"]))
    for si, s in enumerate(payload["sections"]):
        base = f"sections.{si}"
        a0 = 0.08 + (si / n_sections) * 0.85
        kind = s["kind"]
        hint = s.get("layout_hint")
        if kind == "spec_table":
            g = Group(s.get("title") or "제품 정보", hint=hint)
            add(g, f"{base}.title", "섹션 제목", anchor=a0)
            add(g, f"{base}.title_en", "영문 부제", anchor=a0)
            for ri, r in enumerate(s["rows"]):
                add(g, f"{base}.rows.{ri}.value", r["label"], anchor=a0 + 0.02 + ri * 0.02,
                    critical=any(k in r["label"] for k in _CRITICAL_LABELS))
                if r.get("chip"):
                    add(g, f"{base}.rows.{ri}.chip", f"{r['label']} 배지", anchor=a0 + 0.02 + ri * 0.02)
        elif kind == "variants":
            for vi, v in enumerate(s["items"]):
                g = Group(f"규격별 정보 {vi + 1}: {re.sub(r'</?em>', '', v.get('name') or '')}", hint=hint)
                vb = f"{base}.items.{vi}"
                add(g, f"{vb}.name", "이름", anchor=a0)
                add(g, f"{vb}.badge", "배지", anchor=a0, critical=True)
                add(g, f"{vb}.subtitle", "부제", anchor=a0)
                for ti, _ in enumerate(v.get("tags") or []):
                    add(g, f"{vb}.tags.{ti}", f"칩 {ti + 1}", anchor=a0)
                for ri, r in enumerate(v.get("rows") or []):
                    add(g, f"{vb}.rows.{ri}.value", r.get("label") or f"값 {ri + 1}", anchor=a0 + 0.01 + ri * 0.01, critical=True)
                add(g, f"{vb}.note", "하단 문구", anchor=a0 + 0.05)
                groups.append(g)
            continue
        elif kind == "callouts":
            for ci, c in enumerate(s["items"]):
                g = Group(re.sub(r'</?em>', '', c.get("title") or ("용법·용량" if c["tone"] == "action" else "효능·효과")), hint=hint)
                cb = f"{base}.items.{ci}"
                act = c["tone"] == "action"
                add(g, f"{cb}.title", "박스 제목", anchor=a0)
                add(g, f"{cb}.lead", _CALLOUT_LABEL["lead"], multiline=True, anchor=a0 + 0.02, critical=act)
                for bi, _ in enumerate(c.get("bullets") or []):
                    add(g, f"{cb}.bullets.{bi}", f"항목 {bi + 1}", multiline=True, anchor=a0 + 0.04 + bi * 0.015, critical=act)
                for gi, grp in enumerate(c.get("groups") or []):
                    gb = f"{cb}.groups.{gi}"
                    add(g, f"{gb}.heading", f"소제목 {gi + 1}", anchor=a0 + 0.04)
                    add(g, f"{gb}.lead", f"소제목 {gi + 1} 핵심 문장", multiline=True, anchor=a0 + 0.05, critical=act)
                    for bi, _ in enumerate(grp.get("bullets") or []):
                        add(g, f"{gb}.bullets.{bi}", f"소제목 {gi + 1} 항목 {bi + 1}", multiline=True, anchor=a0 + 0.05, critical=act)
                    add(g, f"{gb}.note", f"소제목 {gi + 1} 문구", anchor=a0 + 0.06, critical=act)
                add(g, f"{cb}.note", _CALLOUT_LABEL["note"], anchor=a0 + 0.08, critical=act)
                groups.append(g)
            continue
        elif kind == "icd":
            g = Group(s.get("title") or "상병코드", hint=hint)
            add(g, f"{base}.title", "섹션 제목", anchor=a0)
            add(g, f"{base}.title_en", "영문 부제", anchor=a0)
            for ii, _ in enumerate(s["items"]):
                add(g, f"{base}.items.{ii}.code", f"코드 {ii + 1}", anchor=a0 + 0.03, critical=True)
                add(g, f"{base}.items.{ii}.name", f"상병명 {ii + 1}", anchor=a0 + 0.03)
                add(g, f"{base}.items.{ii}.desc", f"코드 {ii + 1} 설명", anchor=a0 + 0.03)
                add(g, f"{base}.items.{ii}.tag", f"코드 {ii + 1} 칩", anchor=a0 + 0.03)
            add(g, f"{base}.note", "섹션 안내 문구", multiline=True, anchor=a0 + 0.05, critical=True)
        elif kind == "points":
            g = Group(s.get("title") or "디테일 포인트", hint=hint)
            add(g, f"{base}.title", "섹션 제목", anchor=a0)
            add(g, f"{base}.title_en", "영문 부제", anchor=a0)
            add(g, f"{base}.stats_title", "임상 근거 제목", anchor=a0 + 0.02)
            for ti, _ in enumerate(s.get("stats") or []):
                add(g, f"{base}.stats.{ti}.value", f"수치 {ti + 1}", anchor=a0 + 0.03, critical=True)
                add(g, f"{base}.stats.{ti}.caption", f"수치 {ti + 1} 설명", multiline=True, anchor=a0 + 0.03, critical=True)
            for pi, _ in enumerate(s["items"]):
                add(g, f"{base}.items.{pi}.title", f"포인트 {pi + 1} 제목", multiline=True, anchor=a0 + 0.05 + pi * 0.04)
                add(g, f"{base}.items.{pi}.desc", f"포인트 {pi + 1} 설명", multiline=True, anchor=a0 + 0.06 + pi * 0.04)
                add(g, f"{base}.items.{pi}.cite", f"포인트 {pi + 1} 출처", anchor=a0 + 0.06 + pi * 0.04)
        elif kind == "notice":
            g = Group("하단 안내문", hint=hint)
            add(g, f"{base}.title", "안내문 제목", anchor=a0, critical=True)
            for bi, b in enumerate(s["blocks"]):
                bb = f"{base}.blocks.{bi}"
                add(g, f"{bb}.heading", f"소제목 {bi + 1}", anchor=a0 + 0.02, critical=True)
                for pi, _ in enumerate(b.get("paragraphs") or []):
                    add(g, f"{bb}.paragraphs.{pi}", f"문단 {bi + 1}-{pi + 1}", multiline=True, anchor=a0 + 0.03, critical=True)
                for li, _ in enumerate(b.get("bullets") or []):
                    add(g, f"{bb}.bullets.{li}", f"항목 {bi + 1}-{li + 1}", multiline=True, anchor=a0 + 0.03, critical=True)
        elif kind == "text_box":
            g = Group(re.sub(r'</?em>', '', s.get("title") or "메모·설명 박스"), hint=hint)
            add(g, f"{base}.title", "제목", anchor=a0)
            add(g, f"{base}.title_en", "영문 부제", anchor=a0)
            add(g, f"{base}.badge", "배지", anchor=a0)
            for pi, _ in enumerate(s["paragraphs"]):
                add(g, f"{base}.paragraphs.{pi}", f"문단 {pi + 1}", multiline=True, anchor=a0 + 0.01)
        elif kind == "table":
            g = Group(re.sub(r'</?em>', '', s.get("title") or "표"), hint=hint)
            add(g, f"{base}.title", "제목", anchor=a0)
            add(g, f"{base}.title_en", "영문 부제", anchor=a0)
            for ci, _ in enumerate(s.get("columns") or []):
                add(g, f"{base}.columns.{ci}", f"열 제목 {ci + 1}", anchor=a0)
            for ri, row in enumerate(s["rows"]):
                for ci, _ in enumerate(row):
                    add(g, f"{base}.rows.{ri}.{ci}", f"{ri + 1}행 {ci + 1}열", anchor=a0 + 0.01 + ri * 0.01)
            add(g, f"{base}.note", "표 아래 문구", anchor=a0 + 0.04)
        else:
            continue
        groups.append(g)

    f = Group("푸터")
    add(f, "footer.left", "좌측 문구", anchor=0.98)
    for ri, _ in enumerate(payload["footer"].get("refs") or []):
        add(f, f"footer.refs.{ri}", f"참고 {ri + 1}", anchor=0.98)
    groups.append(f)

    # 검증에서 걸렸는데 위 목록에 없는 경로가 있으면 (스키마가 바뀌었거나 빠뜨린 필드) 반드시 따로 노출한다
    shown = {x.path for g in groups for x in g.fields}
    extra = Group("기타 확인 항목")
    for path in issue_map:
        if path.startswith(MISSING_PREFIX) or path == "_structure" or path in shown:
            continue
        val = path_get(payload, path, default=None)
        if isinstance(val, (str, type(None))):
            add(extra, path, path.replace(".", " › "), multiline=True, anchor=0.5)
    if extra.fields:
        groups.append(extra)

    # 값이 None 인 선택 필드는 화면에 내지 않는다 (빈 칸을 채우라는 압박을 주지 않기 위해)
    out = []
    for g in groups:
        g.fields = [x for x in g.fields if x.value is not None or x.flagged]
        if g.fields:
            out.append(asdict(g))
    return out


def flagged_count(groups: list[dict]) -> int:
    return sum(1 for g in groups for f in g["fields"] if f["flagged"])


def critical_count(groups: list[dict]) -> int:
    return sum(1 for g in groups for f in g["fields"] if f["critical_rule"] and not f["flagged"])
