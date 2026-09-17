import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
# 골든 픽스처 PNG 위치. 기본은 Downloads 드라이브 폴더, 환경변수로 덮어쓸 수 있다.
PNG_DIR = Path(
    os.getenv(
        "FIXTURE_PNG_DIR",
        Path.home() / "Downloads" / "drive-download-20260916T062937Z-1-001",
    )
)


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def expected() -> dict:
    return load_json("expected.json")


@pytest.fixture(params=["guse", "glifos"])
def fixture_name(request) -> str:
    return request.param


@pytest.fixture
def hand_payload(fixture_name) -> dict:
    return load_json(f"{fixture_name}.payload.json")


def fixture_png(expected: dict, name: str) -> Path:
    p = PNG_DIR / expected[name]["png"]
    if not p.exists():
        pytest.skip(f"fixture png not found: {p}")
    return p
