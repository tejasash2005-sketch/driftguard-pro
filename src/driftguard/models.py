"""Pydantic data models shared by the engine, CLI, API and reports."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TEXT_CHARS = 1_000_000
MAX_CASES = 10_000


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    INCONCLUSIVE = "INCONCLUSIVE"

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self]


EXIT_CODES: dict[Status, int] = {
    Status.PASS: 0,
    Status.FAIL: 1,
    Status.ERROR: 2,
    Status.INCONCLUSIVE: 3,
}

# Severity order used to combine statuses: ERROR > FAIL > INCONCLUSIVE > PASS.
_SEVERITY = {Status.PASS: 0, Status.INCONCLUSIVE: 1, Status.FAIL: 2, Status.ERROR: 3}


def worst_status(statuses: Iterable[Status]) -> Status:
    """Combine statuses. An empty collection is INCONCLUSIVE (nothing was checked)."""
    items = list(statuses)
    if not items:
        return Status.INCONCLUSIVE
    return max(items, key=lambda s: _SEVERITY[s])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- inputs


class Response(StrictModel):
    """A recorded model response with optional operational metrics."""

    text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class ExactMatch(StrictModel):
    type: Literal["exact_match"]
    expected: str
    strip: bool = True
    case_sensitive: bool = True


class NonEmpty(StrictModel):
    type: Literal["non_empty"]


class JsonKeys(StrictModel):
    type: Literal["json_keys"]
    keys: list[str] = Field(min_length=1)


class JsonSchemaCheck(StrictModel):
    type: Literal["json_schema"]
    json_schema: dict[str, Any] = Field(alias="schema")


class Contains(StrictModel):
    type: Literal["contains"]
    value: str = Field(min_length=1)
    case_sensitive: bool = True


class NotContains(StrictModel):
    type: Literal["not_contains"]
    value: str = Field(min_length=1)
    case_sensitive: bool = True


class Length(StrictModel):
    """Bounds on the output length in characters (after stripping surrounding whitespace)."""

    type: Literal["length"]
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> Length:
        if self.min is None and self.max is None:
            raise ValueError("length assertion needs 'min' and/or 'max'")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("length 'min' must not exceed 'max'")
        return self


AssertionSpec = Annotated[
    ExactMatch | NonEmpty | JsonKeys | JsonSchemaCheck | Contains | NotContains | Length,
    Field(discriminator="type"),
]


class Thresholds(StrictModel):
    """Limits beyond which candidate-vs-baseline drift counts as a failure."""

    min_similarity: float = Field(default=0.8, ge=0, le=1)
    max_latency_increase_pct: float | None = Field(default=50.0, ge=0, allow_inf_nan=False)
    max_token_increase_pct: float | None = Field(default=50.0, ge=0, allow_inf_nan=False)
    max_cost_increase_pct: float | None = Field(default=50.0, ge=0, allow_inf_nan=False)
    fail_on_json_structure_change: bool = True
    fail_on_json_value_change: bool = False


class Case(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    name: str | None = None
    prompt: str = Field(default="", max_length=MAX_TEXT_CHARS)
    assertions: list[AssertionSpec] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0, le=1_000_000, allow_inf_nan=False)
    baseline: Response | None = None
    candidate: Response | None = None
    min_similarity: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class Suite(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    version: str = "1"
    thresholds: Thresholds = Field(default_factory=Thresholds)
    cases: list[Case] = Field(default_factory=list, max_length=MAX_CASES)

    @field_validator("cases")
    @classmethod
    def _unique_ids(cls, cases: list[Case]) -> list[Case]:
        seen: set[str] = set()
        for case in cases:
            if case.id in seen:
                raise ValueError(f"duplicate case id: {case.id!r}")
            seen.add(case.id)
        return cases


class Fixtures(StrictModel):
    """A mapping of case id to recorded response (one side of a comparison)."""

    name: str = ""
    responses: dict[str, Response]


class RunConfig(StrictModel):
    similarity: Literal["lexical", "embedding"] = "lexical"
    seed: int = 0
    bootstrap_resamples: int = Field(default=2000, ge=100, le=20_000)
    permutation_resamples: int = Field(default=10_000, ge=100, le=100_000)
    confidence: float = Field(default=0.95, ge=0.5, le=0.999)
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    min_pairs: int = Field(default=6, ge=2, le=1000)


# --------------------------------------------------------------------------- results


class AssertionResult(StrictModel):
    type: str
    passed: bool
    message: str


class DriftMetric(StrictModel):
    name: str
    baseline: float | None = None
    candidate: float | None = None
    change: float | None = None
    pct_change: float | None = None
    threshold_pct: float | None = None
    exceeded: bool = False


class JsonDiff(StrictModel):
    baseline_valid: bool
    candidate_valid: bool
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    type_changed: list[str] = Field(default_factory=list)
    value_changed: list[str] = Field(default_factory=list)

    @property
    def structure_changed(self) -> bool:
        return bool(
            self.baseline_valid != self.candidate_valid
            or self.added
            or self.removed
            or self.type_changed
        )


class CaseDrift(StrictModel):
    similarity: float
    similarity_method: str
    text_changed: bool
    json_diff: JsonDiff | None = None
    metrics: list[DriftMetric] = Field(default_factory=list)


class CaseResult(StrictModel):
    id: str
    name: str | None = None
    status: Status
    weight: float
    tags: list[str] = Field(default_factory=list)
    assertions: list[AssertionResult] = Field(default_factory=list)
    drift: CaseDrift | None = None
    failure_codes: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    baseline_preview: str | None = None
    candidate_preview: str | None = None


class MetricSummary(StrictModel):
    metric: str
    n_pairs: int
    mean_baseline: float | None = None
    mean_candidate: float | None = None
    mean_diff: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    confidence: float | None = None
    ci_method: str | None = None
    p_value: float | None = None
    test: str | None = None
    significant: bool | None = None
    note: str = ""


class Summary(StrictModel):
    total: int
    passed: int
    failed: int
    errors: int
    inconclusive: int
    pass_rate: float | None
    weighted_pass_rate: float | None
    failure_reasons: dict[str, int] = Field(default_factory=dict)
    drift: list[MetricSummary] = Field(default_factory=list)


class RunMetadata(StrictModel):
    driftguard_version: str
    run_id: str
    generated_at: str
    suite_name: str
    suite_version: str
    suite_description: str = ""
    suite_sha256: str
    report_schema_version: int = 1  # 1 = DriftGuard 1.0 reports; 2 = 1.1+
    config: RunConfig
    thresholds: Thresholds


class CaseChange(StrictModel):
    id: str
    old_status: Status | None = None
    new_status: Status | None = None
    similarity_delta: float | None = None
    new_failure_codes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ReportDiff(StrictModel):
    old_run_id: str
    new_run_id: str
    old_suite: str
    new_suite: str
    old_status: Status
    new_status: Status
    pass_rate_delta: float | None = None
    regressions: list[CaseChange] = Field(default_factory=list)
    fixed: list[CaseChange] = Field(default_factory=list)
    changed: list[CaseChange] = Field(default_factory=list)
    added: list[CaseChange] = Field(default_factory=list)
    removed: list[CaseChange] = Field(default_factory=list)
    unchanged: int = 0

    @property
    def has_regressions(self) -> bool:
        """True when a case worsened, disappeared, or a new case does not pass."""
        return bool(self.regressions or self.removed) or any(
            c.new_status is not Status.PASS for c in self.added
        )


class Report(StrictModel):
    metadata: RunMetadata
    status: Status
    summary: Summary
    results: list[CaseResult]

    @model_validator(mode="after")
    def _consistent(self) -> Report:
        if self.summary.total != len(self.results):
            raise ValueError("summary.total does not match the number of results")
        return self
