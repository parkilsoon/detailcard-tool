"""payload + 템플릿 → mobile.html (CSS 인라인 단일 파일)."""
from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import config
from app.sanitize import em

TEMPLATE_VERSION = config.TEMPLATE_VERSION

_env = Environment(
    loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=False,
    lstrip_blocks=False,
)
_env.filters["em"] = em


def card_css() -> str:
    return (config.STATIC_DIR / "card.css").read_text(encoding="utf-8")


def render_card(payload: dict) -> str:
    tpl = _env.get_template("card/base.html")
    return tpl.render(
        header=payload["header"],
        sections=payload["sections"],
        footer=payload.get("footer") or {},
        meta=payload.get("meta"),
        css=card_css(),
        template_version=TEMPLATE_VERSION,
    )


def app_env() -> Environment:
    """툴 UI 템플릿용 (같은 엔진, 같은 필터)."""
    return _env


if __name__ == "__main__":  # CLI: uv run python -m app.renderer payload.json out.html
    import json
    import sys
    from pathlib import Path

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_card(data), encoding="utf-8")
    print(out)
