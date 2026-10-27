"""Safe file loading with clear, actionable error messages."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import SuiteLoadError
from .models import Fixtures, Report, Suite
from .simulator import SimulatorConfig

MAX_FILE_BYTES = 25 * 1024 * 1024
T = TypeVar("T", bound=BaseModel)


def read_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        raise SuiteLoadError(f"file not found: {p}")
    if p.is_dir():
        raise SuiteLoadError(f"expected a file but got a directory: {p}")
    try:
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SuiteLoadError(f"file too large ({size} bytes, limit {MAX_FILE_BYTES}): {p}")
        raw = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SuiteLoadError(f"file is not valid UTF-8 text: {p}") from exc
    except OSError as exc:
        raise SuiteLoadError(f"cannot read {p}: {exc.strerror or type(exc).__name__}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SuiteLoadError(
            f"malformed JSON in {p}: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    except RecursionError as exc:
        raise SuiteLoadError(f"JSON in {p} is nested too deeply") from exc


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors()[:5]:
        location = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"{location}: {err['msg']}")
    more = exc.error_count() - len(lines)
    if more > 0:
        lines.append(f"... and {more} more")
    return "; ".join(lines)


def _load(path: str | Path, model: type[T], label: str) -> T:
    data = read_json(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise SuiteLoadError(f"invalid {label} in {path}: {_format_errors(exc)}") from exc


def load_suite(path: str | Path) -> Suite:
    return _load(path, Suite, "suite")


def load_fixtures(path: str | Path) -> Fixtures:
    return _load(path, Fixtures, "fixtures")


def load_simulator_config(path: str | Path) -> SimulatorConfig:
    return _load(path, SimulatorConfig, "simulator config")


def load_report(path: str | Path) -> Report:
    return _load(path, Report, "report")


def discover_suites(paths: Sequence[str | Path]) -> list[Path]:
    """Expand directories into their ``*.json`` files (sorted); keep files as given."""
    found: list[Path] = []
    for item in paths:
        p = Path(item)
        if p.is_dir():
            matches = sorted(p.glob("*.json"))
            if not matches:
                raise SuiteLoadError(f"no .json suite files found in directory: {p}")
            found.extend(matches)
        else:
            found.append(p)
    return found
