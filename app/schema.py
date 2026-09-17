"""JSON 스키마 v2 — pydantic 모델. 이 파일이 유일한 원본이다.
prompts/extract_v2.txt 안의 스키마 텍스트는 사람이 읽기 좋게 쓴 사본이며,
tests/test_schema.py 가 둘의 열거형이 어긋나지 않는지 확인한다.

v2 변경 (124장 실측 기반):
- 새 kind: variants(규격별 박스), text_box(메모·설명 박스), table(특수 표의 안전망)
- notice: tone + 소제목 블록 / callouts: 소제목 그룹 / points: 수치 타일·인용 / icd: 설명·메모
- 모든 섹션에 layout_hint: 스키마에 딱 맞지 않아 임시 서식(text_box/table)으로 담았을 때 원래 모양 설명
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "2.0"

BadgeKind = Literal["plain", "code", "covered", "noncovered", "selective", "mixed"]
SectionKind = Literal["spec_table", "variants", "callouts", "icd", "points", "notice", "text_box", "table"]
CalloutTone = Literal["info", "action"]
PointIcon = Literal["star", "check"]
NoticeTone = Literal["warn", "info", "noncovered"]
BoxTone = Literal["plain", "info", "success"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Badge(_Base):
    text: str
    kind: BadgeKind


class Header(_Base):
    company: str
    product_name: str
    form: Optional[str] = None
    ingredient: str
    category: Optional[str] = None
    badges: list[Badge] = Field(default_factory=list)


class _Section(_Base):
    no: Optional[int] = None
    layout_hint: Optional[str] = None


class SpecRow(_Base):
    label: str
    value: str
    chip: Optional[str] = None


class SpecTable(_Section):
    kind: Literal["spec_table"]
    title: str
    title_en: Optional[str] = None
    rows: list[SpecRow]


class VariantRow(_Base):
    label: str
    value: str


class VariantItem(_Base):
    name: str                       # 박스 제목 (예: "동구에페리손정", "20g", "5mg")
    badge: Optional[str] = None     # 제목 옆 배지 (예: "50mg", "소포장 · 튜브", "2:1")
    subtitle: Optional[str] = None  # 제목 아래 부제
    tags: list[str] = Field(default_factory=list)  # 작은 칩들 (자사생산, 표준, 하루 3회 ...)
    rows: list[VariantRow] = Field(default_factory=list)
    note: Optional[str] = None      # 박스 하단 문구


class Variants(_Section):
    kind: Literal["variants"]
    title: Optional[str] = None
    items: list[VariantItem]


class CalloutGroup(_Base):
    heading: str                    # ▶ 소제목, ① 번호 항목 등
    lead: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class CalloutItem(_Base):
    tone: CalloutTone
    title: str
    lead: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    groups: list[CalloutGroup] = Field(default_factory=list)
    note: Optional[str] = None


class Callouts(_Section):
    kind: Literal["callouts"]
    items: list[CalloutItem]


class IcdItem(_Base):
    code: str
    name: str
    desc: Optional[str] = None      # 코드 아래 작은 설명 줄
    tag: Optional[str] = None       # "필수" 같은 칩


class Icd(_Section):
    kind: Literal["icd"]
    title: str
    title_en: Optional[str] = None
    items: list[IcdItem]
    note: Optional[str] = None      # 섹션 안 경고 띠 / 코드 없음 안내


class StatTile(_Base):
    value: str                      # "35.7%", "1.4배", "동등"
    caption: str


class PointItem(_Base):
    icon: PointIcon
    title: str
    desc: Optional[str] = None
    cite: Optional[str] = None      # 작은 출처 줄
    highlight: bool = False         # 초록 배경 강조 타일


class Points(_Section):
    kind: Literal["points"]
    title: str
    title_en: Optional[str] = None
    stats_title: Optional[str] = None   # "▶ 임상 근거 (…)"
    stats: list[StatTile] = Field(default_factory=list)
    items: list[PointItem]


class NoticeBlock(_Base):
    heading: Optional[str] = None   # "▶ 원칙" 등. 없으면 null
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class Notice(_Section):
    kind: Literal["notice"]
    title: str
    tone: NoticeTone = "warn"
    blocks: list[NoticeBlock]


class TextBox(_Section):
    kind: Literal["text_box"]
    title: Optional[str] = None
    title_en: Optional[str] = None  # 번호 달린 섹션 제목으로 쓰일 때의 영문 부제
    badge: Optional[str] = None
    tone: BoxTone = "plain"
    paragraphs: list[str]


class Table(_Section):
    kind: Literal["table"]
    title: Optional[str] = None
    title_en: Optional[str] = None  # 번호 달린 섹션 제목으로 쓰일 때의 영문 부제
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]]
    note: Optional[str] = None


Section = Annotated[
    Union[SpecTable, Variants, Callouts, Icd, Points, Notice, TextBox, Table],
    Field(discriminator="kind"),
]


class Footer(_Base):
    left: Optional[str] = None
    refs: list[str] = Field(default_factory=list)


class Meta(_Base):
    card_id: str
    source_image: str
    slice_count: int
    extracted_at: str
    model: str
    prompt_version: str


class Payload(_Base):
    schema_version: str = SCHEMA_VERSION
    meta: Optional[Meta] = None
    header: Header
    sections: list[Section]
    footer: Footer
    uncertain: list[str] = Field(default_factory=list)


class Issue(_Base):
    severity: Literal["critical", "minor"]
    path: str
    image_says: Optional[str] = None
    json_says: Optional[str] = None
    note: Optional[str] = None


class Issues(_Base):
    issues: list[Issue] = Field(default_factory=list)


class Lines(_Base):
    lines: list[str]


def validate_payload(data: dict) -> Payload:
    return Payload.model_validate(data)


def validate_issues(data: dict) -> Issues:
    return Issues.model_validate(data)


def validate_lines(data: dict) -> Lines:
    return Lines.model_validate(data)
