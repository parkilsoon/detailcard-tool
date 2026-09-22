"""출력 이스케이프 + 인라인 태그 화이트리스트.

렌더 시 모든 문자열을 이스케이프한 뒤, 아래 태그만 실제 태그로 복원한다.
  <em>            굵게(강조)                      → <em>
  <red> <blue> <green> <gray>    글자색 (검수자가 넣음)   → <span class="c-red"> …
블랙리스트(특정 태그 제거)가 아니라 화이트리스트 방식이다. 속성은 어떤 태그에도 허용하지 않는다.
"""
from __future__ import annotations

import re
from html import escape

from markupsafe import Markup

COLOR_TAGS = ("red", "blue", "green", "gray")
ALLOWED_TAGS = ("em",) + COLOR_TAGS

_ANY_TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
_ALLOWED_STRIP = re.compile(r"</?(?:em|red|blue|green|gray)>", re.IGNORECASE)


def em(value: object) -> Markup:
    """Jinja2 필터. 이스케이프 후 허용 태그만 복원. None 이면 빈 문자열."""
    if value is None:
        return Markup("")
    s = escape(str(value), quote=True)
    s = re.sub(r"&lt;em&gt;", "<em>", s, flags=re.I)
    s = re.sub(r"&lt;/em&gt;", "</em>", s, flags=re.I)
    for c in COLOR_TAGS:
        s = re.sub(rf"&lt;{c}&gt;", f'<span class="c-{c}">', s, flags=re.I)
        s = re.sub(rf"&lt;/{c}&gt;", "</span>", s, flags=re.I)
    return Markup(s)


def strip_disallowed_tags(value: str) -> str:
    """추출·저장 후처리용: 허용 태그 이외의 태그를 제거하고, 허용 태그는 속성을 벗겨 정규형으로."""
    def repl(m: re.Match) -> str:
        name = m.group(1).lower()
        if name not in ALLOWED_TAGS:
            return ""
        return f"</{name}>" if m.group(0).startswith("</") else f"<{name}>"
    return _ANY_TAG.sub(repl, value)


def plain_text(value: str | None) -> str:
    """허용 태그를 모두 벗긴 순수 텍스트 (DB 컬럼·대조용)."""
    if not value:
        return ""
    return _ALLOWED_STRIP.sub("", value)
