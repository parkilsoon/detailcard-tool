"""필드 경로 유틸. 점 + 숫자 인덱스 표기 (예: sections.0.rows.4.value)."""
from __future__ import annotations

from typing import Any, Iterator

_MISSING = object()


def _keys(path: str) -> list[str]:
    if not path:
        raise ValueError("empty path")
    return path.split(".")


def path_get(obj: Any, path: str, default: Any = _MISSING) -> Any:
    cur = obj
    for k in _keys(path):
        if isinstance(cur, dict):
            if k not in cur:
                if default is _MISSING:
                    raise KeyError(path)
                return default
            cur = cur[k]
        elif isinstance(cur, list):
            try:
                idx = int(k)
                cur = cur[idx]
            except (ValueError, IndexError):
                if default is _MISSING:
                    raise KeyError(path)
                return default
        else:
            if default is _MISSING:
                raise KeyError(path)
            return default
    return cur


def path_set(obj: Any, path: str, value: Any) -> None:
    """기존 경로에만 값을 쓴다. 없는 키나 인덱스를 만들지 않는다."""
    keys = _keys(path)
    parent = path_get(obj, ".".join(keys[:-1])) if len(keys) > 1 else obj
    last = keys[-1]
    if isinstance(parent, dict):
        if last not in parent:
            raise KeyError(path)
        parent[last] = value
    elif isinstance(parent, list):
        idx = int(last)
        if idx < 0 or idx >= len(parent):
            raise KeyError(path)
        parent[idx] = value
    else:
        raise KeyError(path)


def iter_strings(obj: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """payload 안의 모든 문자열 값을 (경로, 값)으로 순회한다. 키 문자열은 제외."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{prefix}.{i}" if prefix else str(i))
    elif isinstance(obj, str):
        yield prefix, obj
