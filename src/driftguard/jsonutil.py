"""JSON parsing and structural diffing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def try_parse_json(text: str) -> tuple[bool, Any]:
    """Parse ``text`` as JSON. Returns ``(ok, value)``; never raises."""
    import json

    if not text.strip():
        return False, None
    try:
        return True, json.loads(text)
    except (ValueError, RecursionError):
        return False, None


def kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


@dataclass
class JsonDiffResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    type_changed: list[str] = field(default_factory=list)
    value_changed: list[str] = field(default_factory=list)


def diff_json(old: Any, new: Any, *, max_depth: int = 50) -> JsonDiffResult:
    """Structural diff using dotted/indexed paths (``a.b[0]``); ``$`` is the root."""
    result = JsonDiffResult()

    def walk(x: Any, y: Any, path: str, depth: int) -> None:
        kx, ky = kind(x), kind(y)
        if kx != ky:
            result.type_changed.append(path or "$")
            return
        if depth >= max_depth:
            if x != y:
                result.value_changed.append(path or "$")
            return
        if kx == "object":
            for key in sorted(set(x) | set(y)):
                child = f"{path}.{key}" if path else key
                if key not in y:
                    result.removed.append(child)
                elif key not in x:
                    result.added.append(child)
                else:
                    walk(x[key], y[key], child, depth + 1)
        elif kx == "array":
            for index in range(max(len(x), len(y))):
                child = f"{path}[{index}]"
                if index >= len(y):
                    result.removed.append(child)
                elif index >= len(x):
                    result.added.append(child)
                else:
                    walk(x[index], y[index], child, depth + 1)
        elif x != y:
            result.value_changed.append(path or "$")

    walk(old, new, "", 0)
    return result
