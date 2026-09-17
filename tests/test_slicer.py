from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.slicer import TooManySlices, compute_slice_height, plan_slices, prepare, slice_label
from tests.conftest import fixture_png


@pytest.fixture(autouse=True)
def anthropic_slice_rules(monkeypatch):
    """슬라이스 테스트는 .env 의 프로바이더와 무관하게 Claude 표준 티어 규칙으로 고정한다."""
    monkeypatch.setattr(config, "SLICE_HEIGHT", None)
    monkeypatch.setattr(config, "LLM_MAX_VISUAL_TOKENS", 1568)
    monkeypatch.setattr(config, "LLM_MAX_LONG_EDGE", 1568)


def test_slice_height_1440():
    assert compute_slice_height(1440, 1568, 1568, fixed=0) == 840


def test_slice_height_capped_by_long_edge():
    assert compute_slice_height(560, 1568, 1568, fixed=0) == 1568


def test_slice_height_fixed_override():
    assert compute_slice_height(1440, fixed=1536, max_long_edge=3072) == 1536
    assert compute_slice_height(1440, fixed=4000, max_long_edge=3072) == 3072  # 20 patches → 78*28=2184 > 1568


def test_plan_overlap_and_tail():
    plan = plan_slices(1440, 2170)
    assert plan[0] == (0, 840)
    assert plan[1][0] == 840 - 126  # 15% overlap
    assert plan[-1] == (2170 - 840, 2170)
    for (a0, a1), (b0, b1) in zip(plan, plan[1:]):
        assert b0 < a1  # 겹침 존재
        assert b0 > a0


def test_plan_short_image_single_slice():
    assert plan_slices(1440, 500) == [(0, 500)]


def test_prepare_fixture(tmp_path, expected):
    src = fixture_png(expected, "guse")
    infos = prepare(src, tmp_path)
    assert 1 <= len(infos) <= config.SLICE_MAX_COUNT
    for info in infos:
        with Image.open(info.path) as im:
            assert im.height <= 840 and im.width == 1440
    assert slice_label(infos[0], len(infos)).startswith("[슬라이스 1/")
    assert "하단" in slice_label(infos[-1], len(infos))


def test_prepare_rejects_too_tall(tmp_path):
    big = tmp_path / "big.png"
    Image.new("RGB", (1440, 840 * 9)).save(big)
    with pytest.raises(TooManySlices):
        prepare(big, tmp_path / "out")


def test_prepare_downscales_wide(tmp_path):
    wide = tmp_path / "wide.png"
    Image.new("RGB", (3000, 1000)).save(wide)
    infos = prepare(wide, tmp_path / "out")
    assert infos[0].width == config.LLM_MAX_LONG_EDGE
