from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from driftguard.assertions import evaluate_assertion
from driftguard.errors import AssertionConfigError
from driftguard.models import AssertionSpec, Response

ADAPTER: TypeAdapter[AssertionSpec] = TypeAdapter(AssertionSpec)


def check(spec: dict, text: str):
    return evaluate_assertion(ADAPTER.validate_python(spec), Response(text=text))


def test_exact_match() -> None:
    assert check({"type": "exact_match", "expected": "Paris"}, "Paris").passed
    assert check({"type": "exact_match", "expected": "Paris"}, "  Paris\n").passed
    assert not check({"type": "exact_match", "expected": "Paris"}, "paris").passed
    assert check(
        {"type": "exact_match", "expected": "Paris", "case_sensitive": False}, "paris"
    ).passed
    assert not check({"type": "exact_match", "expected": "Paris", "strip": False}, " Paris").passed
    result = check({"type": "exact_match", "expected": "Paris"}, "London")
    assert not result.passed and "London" in result.message


def test_non_empty() -> None:
    assert check({"type": "non_empty"}, "x").passed
    assert not check({"type": "non_empty"}, "").passed
    assert not check({"type": "non_empty"}, " \n\t ").passed


def test_json_keys() -> None:
    spec = {"type": "json_keys", "keys": ["a", "b"]}
    assert check(spec, '{"a": 1, "b": null, "c": 3}').passed
    missing = check(spec, '{"a": 1}')
    assert not missing.passed and "b" in missing.message
    assert not check(spec, "not json").passed
    assert "not valid JSON" in check(spec, "{oops").message
    assert "not an object" in check(spec, "[1, 2]").message
    assert not check(spec, "").passed


def test_json_keys_nested_and_literal_dotted() -> None:
    spec = {"type": "json_keys", "keys": ["user.name"]}
    assert check(spec, '{"user": {"name": "x"}}').passed
    assert check(spec, '{"user.name": 1}').passed
    assert not check(spec, '{"user": {"id": 1}}').passed
    assert not check(spec, '{"user": 5}').passed


def test_json_schema_object_accepts_any_object() -> None:
    # {"type": "object"} must ACCEPT {"x": 1}: it only constrains the type.
    assert check({"type": "json_schema", "schema": {"type": "object"}}, '{"x": 1}').passed
    assert not check({"type": "json_schema", "schema": {"type": "object"}}, "[1]").passed


def test_json_schema_required_property_missing_is_rejected() -> None:
    # Fixed test: rejection requires a missing required property.
    schema = {"type": "object", "required": ["required_field"]}
    missing = check({"type": "json_schema", "schema": schema}, '{"x": 1}')
    assert not missing.passed
    assert "required_field" in missing.message
    assert check({"type": "json_schema", "schema": schema}, '{"required_field": 1}').passed


def test_json_schema_types_and_nested_paths() -> None:
    schema = {
        "type": "object",
        "required": ["n"],
        "properties": {
            "n": {"type": "integer", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }
    spec = {"type": "json_schema", "schema": schema}
    assert check(spec, '{"n": 3, "tags": ["a"]}').passed
    bad = check(spec, '{"n": "3", "tags": ["a", 1], "zzz": 1}')
    assert not bad.passed and "n:" in bad.message
    assert not check(spec, '{"n": -1}').passed
    assert not check(spec, "plain text").passed


def test_json_schema_invalid_schema_is_a_config_error() -> None:
    with pytest.raises(AssertionConfigError, match="invalid JSON Schema"):
        check({"type": "json_schema", "schema": {"type": "not-a-type"}}, "{}")


def test_json_schema_remote_ref_is_not_fetched() -> None:
    spec = {"type": "json_schema", "schema": {"$ref": "http://127.0.0.1:9/never.json"}}
    with pytest.raises(AssertionConfigError):
        check(spec, "{}")


def test_spec_validation() -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"type": "bogus"})
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"type": "json_keys", "keys": []})
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"type": "exact_match", "expected": "x", "extra": 1})
    assert json.loads(Response(text="{}").text) == {}
