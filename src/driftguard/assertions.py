"""Assertion evaluation. Assertions never execute user-provided code."""

from __future__ import annotations

from typing import Any

from jsonschema import SchemaError
from jsonschema.validators import validator_for

from .errors import AssertionConfigError
from .jsonutil import try_parse_json
from .models import (
    AssertionResult,
    AssertionSpec,
    Contains,
    ExactMatch,
    JsonKeys,
    JsonSchemaCheck,
    Length,
    NonEmpty,
    NotContains,
    Response,
)


def preview(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return repr(flat if len(flat) <= limit else flat[: limit - 3] + "...")


def _has_path(obj: dict[str, Any], key: str) -> bool:
    if key in obj:
        return True
    current: Any = obj
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _exact(spec: ExactMatch, response: Response) -> AssertionResult:
    actual, expected = response.text, spec.expected
    if spec.strip:
        actual, expected = actual.strip(), expected.strip()
    if not spec.case_sensitive:
        actual, expected = actual.casefold(), expected.casefold()
    if actual == expected:
        return AssertionResult(type=spec.type, passed=True, message="output matches expected")
    return AssertionResult(
        type=spec.type,
        passed=False,
        message=f"output {preview(response.text)} != expected {preview(spec.expected)}",
    )


def _non_empty(spec: NonEmpty, response: Response) -> AssertionResult:
    ok = bool(response.text.strip())
    return AssertionResult(
        type=spec.type, passed=ok, message="output is non-empty" if ok else "output is empty"
    )


def _json_keys(spec: JsonKeys, response: Response) -> AssertionResult:
    ok, value = try_parse_json(response.text)
    if not ok:
        return AssertionResult(type=spec.type, passed=False, message="output is not valid JSON")
    if not isinstance(value, dict):
        return AssertionResult(
            type=spec.type, passed=False, message="top-level JSON value is not an object"
        )
    missing = [key for key in spec.keys if not _has_path(value, key)]
    if missing:
        return AssertionResult(
            type=spec.type, passed=False, message=f"missing keys: {', '.join(missing)}"
        )
    return AssertionResult(type=spec.type, passed=True, message="all required keys present")


def _json_schema(spec: JsonSchemaCheck, response: Response) -> AssertionResult:
    schema = spec.json_schema
    try:
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
    except SchemaError as exc:
        raise AssertionConfigError(f"invalid JSON Schema: {exc.message}") from exc
    ok, value = try_parse_json(response.text)
    if not ok:
        return AssertionResult(type=spec.type, passed=False, message="output is not valid JSON")
    try:
        errors = sorted(
            validator_cls(schema).iter_errors(value),
            key=lambda e: [str(p) for p in e.absolute_path],
        )
    except Exception as exc:  # unresolvable $ref, bad regex, etc.
        raise AssertionConfigError(
            f"JSON Schema could not be evaluated: {type(exc).__name__}"
        ) from exc
    if not errors:
        return AssertionResult(type=spec.type, passed=True, message="output matches schema")
    shown = []
    for err in errors[:3]:
        location = "/".join(str(p) for p in err.absolute_path) or "(root)"
        shown.append(f"{location}: {err.message[:120]}")
    extra = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
    return AssertionResult(
        type=spec.type, passed=False, message="schema violations: " + "; ".join(shown) + extra
    )


def _contains(spec: Contains | NotContains, response: Response) -> AssertionResult:
    text, needle = response.text, spec.value
    if not spec.case_sensitive:
        text, needle = text.casefold(), needle.casefold()
    found = needle in text
    if isinstance(spec, Contains):
        msg = "contains required text" if found else f"missing required text {preview(spec.value)}"
        return AssertionResult(type=spec.type, passed=found, message=msg)
    msg = "forbidden text absent" if not found else f"contains forbidden text {preview(spec.value)}"
    return AssertionResult(type=spec.type, passed=not found, message=msg)


def _length(spec: Length, response: Response) -> AssertionResult:
    size = len(response.text.strip())
    if spec.min is not None and size < spec.min:
        return AssertionResult(
            type=spec.type, passed=False, message=f"length {size} is below minimum {spec.min}"
        )
    if spec.max is not None and size > spec.max:
        return AssertionResult(
            type=spec.type, passed=False, message=f"length {size} exceeds maximum {spec.max}"
        )
    return AssertionResult(type=spec.type, passed=True, message=f"length {size} within bounds")


def evaluate_assertion(spec: AssertionSpec, response: Response) -> AssertionResult:
    """Evaluate one assertion. Raises AssertionConfigError for misconfiguration."""
    if isinstance(spec, ExactMatch):
        return _exact(spec, response)
    if isinstance(spec, NonEmpty):
        return _non_empty(spec, response)
    if isinstance(spec, JsonKeys):
        return _json_keys(spec, response)
    if isinstance(spec, JsonSchemaCheck):
        return _json_schema(spec, response)
    if isinstance(spec, Contains | NotContains):
        return _contains(spec, response)
    if isinstance(spec, Length):
        return _length(spec, response)
    raise AssertionConfigError(f"unsupported assertion: {spec!r}")  # pragma: no cover


__all__ = ["evaluate_assertion", "preview"]
