"""이미지 전처리: 리사이즈 → 세로 슬라이스 (겹침 포함).

슬라이스 1장이 모델의 비주얼 토큰 한도 안에 들어가게 잘라서 API 측 자동 축소를 피한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app import config

PATCH = 28


class TooManySlices(ValueError):
    pass


@dataclass
class SliceInfo:
    index: int          # 1부터
    path: Path
    top: int            # 원본(리사이즈 후) 좌표계에서의 y 시작
    bottom: int
    width: int
    height: int

    @property
    def position_label(self) -> str:
        return ""


def compute_slice_height(width: int,
                         max_visual_tokens: int | None = None,
                         max_long_edge: int | None = None,
                         fixed: int | None = None) -> int:
    """슬라이스 높이.
    - fixed(또는 config.SLICE_HEIGHT)가 있으면 그 값 (Gemini 기본: 768px 타일 2단 = 1536).
    - 없으면 Claude 규칙: 28px 패치 기준 비주얼 토큰 한도 안에 들어가는 최대 높이."""
    max_long_edge = max_long_edge or config.LLM_MAX_LONG_EDGE
    fixed = fixed if fixed is not None else config.SLICE_HEIGHT
    if fixed:
        return min(fixed, max_long_edge)
    max_visual_tokens = max_visual_tokens or config.LLM_MAX_VISUAL_TOKENS
    if not max_visual_tokens:
        raise ValueError("SLICE_HEIGHT 또는 LLM_MAX_VISUAL_TOKENS 중 하나는 있어야 합니다")
    w_patch = math.ceil(width / PATCH)
    max_h_patch = max_visual_tokens // w_patch
    if max_h_patch < 1:
        raise ValueError(f"width {width} too wide for token budget {max_visual_tokens}")
    return min(max_h_patch * PATCH, max_long_edge)


def plan_slices(width: int, height: int,
                overlap_ratio: float = config.SLICE_OVERLAP_RATIO,
                slice_height: int | None = None) -> list[tuple[int, int]]:
    """(top, bottom) 목록. 마지막 슬라이스는 이미지 하단에 맞춘다."""
    sh = slice_height or compute_slice_height(width)
    if height <= sh:
        return [(0, height)]
    overlap = int(sh * overlap_ratio)
    step = sh - overlap
    tops: list[int] = []
    y = 0
    while True:
        tops.append(y)
        if y + sh >= height:
            break
        y += step
    # 마지막 슬라이스가 하단을 넘지 않게 당긴다
    tops[-1] = max(0, height - sh)
    # 당긴 결과 직전 슬라이스와 같아지면 제거
    dedup: list[int] = []
    for t in tops:
        if not dedup or t > dedup[-1]:
            dedup.append(t)
    return [(t, min(t + sh, height)) for t in dedup]


def prepare(source_png: Path, out_dir: Path,
            max_width: int | None = None,
            slice_height: int | None = None) -> list[SliceInfo]:
    """원본을 읽어 (필요 시 폭 축소 후) 슬라이스를 out_dir에 저장한다.
    slice_height 를 주면 그 높이로(검증용 2차 전사), 아니면 기본 규칙으로 자른다."""
    max_width = max_width or config.LLM_MAX_LONG_EDGE
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source_png) as im:
        im = im.convert("RGB")
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, round(im.height * ratio)), Image.LANCZOS)
        if slice_height is None and config.SLICE_HEIGHT is None and not config.LLM_MAX_VISUAL_TOKENS:
            raise ValueError("슬라이스 규칙이 없습니다")
        plan = plan_slices(im.width, im.height, slice_height=slice_height)
        if len(plan) > config.SLICE_MAX_COUNT:
            raise TooManySlices(
                f"슬라이스가 {len(plan)}장 필요합니다 (최대 {config.SLICE_MAX_COUNT}장). "
                f"이미지 높이 {im.height}px")
        infos: list[SliceInfo] = []
        for i, (top, bottom) in enumerate(plan, start=1):
            crop = im.crop((0, top, im.width, bottom))
            p = out_dir / f"{i:02d}.jpg"
            crop.save(p, "JPEG", quality=config.SLICE_JPEG_QUALITY, optimize=True)
            infos.append(SliceInfo(i, p, top, bottom, crop.width, crop.height))
        return infos


def slice_label(info: SliceInfo, total: int) -> str:
    if total == 1:
        pos = "전체"
    elif info.index == 1:
        pos = "상단"
    elif info.index == total:
        pos = "하단"
    else:
        pos = "중간"
    return f"[슬라이스 {info.index}/{total} · {pos}]"


if __name__ == "__main__":  # CLI: uv run python -m app.slicer <png> [out_dir]
    import sys

    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("storage/_slicer_test") / src.stem
    infos = prepare(src, out)
    for info in infos:
        print(slice_label(info, len(infos)), info.path, f"{info.width}x{info.height}",
              f"y={info.top}..{info.bottom}", f"{info.path.stat().st_size/1024:.0f}KB")
