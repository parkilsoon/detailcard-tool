"""출력 이스케이프 + <em> 화이트리스트.

렌더 시 모든 문자열을 이스케이프한 뒤 &lt;em&gt; / &lt;/em&gt; 만 태그로 복원한다.
블랙리스트(특정 태그 제거)가 아니라 화이트리스트 방식이다.
"""
from __future__ import annotations

import re
from html import escape

from markupsafe import Markup

_EM_OPEN = re.compile(r"&lt;em&gt;", re.IGNORECASE)
_EM_CLOSE = re.compile(r"&lt;/em&gt;", re.IGNORECASE)
_ANY_TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>")


def em(value: object) -> Markup:
    """Jinja2 필터. None 이면 빈 문자열."""
    if value is None:
        return Markup("")
    s = escape(str(value), quote=True)
    s = _EM_OPEN.sub("<em>", s)
    s = _EM_CLOSE.sub("</em>", s)
    return Markup(s)


def strip_disallowed_tags(value: str) -> str:
    """추출 후처리용: <em> / </em> 이외의 태그를 문자열에서 제거한다.
    (렌더 단계의 화이트리스트와 별개로, 저장 payload를 깨끗하게 유지하기 위한 것)"""
    def repl(m: re.Match) -> str:
        if m.group(1).lower() != "em":
            return ""
        # <em ...속성> → <em>, </em ...> → </em>
        return "</em>" if m.group(0).startswith("</") else "<em>"
    return _ANY_TAG.sub(repl, value)


def plain_text(value: str | None) -> str:
    """<em> 태그를 벗긴 순수 텍스트 (DB 컬럼·검색용)."""
    if not value:
        return ""
    return re.sub(r"</?em>", "", value, flags=re.I)
