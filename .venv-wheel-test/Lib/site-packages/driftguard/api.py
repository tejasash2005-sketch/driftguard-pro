"""FastAPI backend and dashboard host."""

from __future__ import annotations

import hmac
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import Response as HttpResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .diff import diff_reports
from .engine import compare_fixtures, run_suite
from .errors import DriftGuardError, NotFoundError, SuiteLoadError
from .loader import load_suite
from .logging_utils import get_logger
from .models import CaseResult, Fixtures, Report, ReportDiff, RunConfig, Status, Suite
from .reports import render
from .simulator import SimulatorConfig, simulate
from .store import RunStore, RunStoreProtocol, SqliteRunStore

log = get_logger("api")

PACKAGE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = PACKAGE_DIR / "dashboard"
EXAMPLES_DIR = PACKAGE_DIR / "examples"
_EXAMPLE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: Suite | None = None
    example: str | None = Field(default=None, description="Name of a bundled example suite")
    config: RunConfig = Field(default_factory=RunConfig)

    @model_validator(mode="after")
    def _exactly_one(self) -> RunRequest:
        if (self.suite is None) == (self.example is None):
            raise ValueError("provide exactly one of 'suite' or 'example'")
        if self.example is not None and not _EXAMPLE_NAME.match(self.example):
            raise ValueError("example must match ^[A-Za-z0-9_-]{1,64}$")
        return self


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline: Fixtures
    candidate: Fixtures
    suite: Suite | None = None
    config: RunConfig = Field(default_factory=RunConfig)


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: SimulatorConfig
    run: bool = False
    run_config: RunConfig = Field(default_factory=RunConfig)


class RunListItem(BaseModel):
    run_id: str
    suite_name: str
    status: Status
    generated_at: str
    total: int
    passed: int
    failed: int
    pass_rate: float | None


class TrendPoint(BaseModel):
    run_id: str
    generated_at: str
    status: Status
    total: int
    pass_rate: float | None
    weighted_pass_rate: float | None


class SimulateResponse(BaseModel):
    suite: Suite
    report: Report | None = None


SUITE_EXAMPLES = ("demo", "regression")


def _example_names() -> list[str]:
    """Bundled example *suites* (the other example files are fixtures/configs)."""
    return [name for name in SUITE_EXAMPLES if (EXAMPLES_DIR / f"{name}.json").is_file()]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


MIN_TOKEN_CHARS = 16
DEFAULT_MAX_BODY = 10 * 1024 * 1024
RunId = Annotated[str, PathParam(pattern=r"^[a-f0-9]{12}$")]


class BodyLimitMiddleware:
    """Pure-ASGI request body limit: rejects with 413 before the app parses anything."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        too_big = bool(declared and declared.isdigit() and int(declared) > self.max_bytes)
        chunks: list[Message] = []
        if not too_big:
            total = 0
            while True:
                message = await receive()
                chunks.append(message)
                if message["type"] != "http.request":
                    break
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    too_big = True
                    break
                if not message.get("more_body", False):
                    break
        if too_big:
            response = _error(
                413, "payload_too_large", f"request body exceeds {self.max_bytes} bytes"
            )
            await response(scope, receive, send)
            return
        replay = iter(chunks)

        async def replayed() -> Message:
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        await self.app(scope, replayed, send)


def _store_from_env() -> RunStoreProtocol:
    db = os.environ.get("DRIFTGUARD_DB", "").strip()
    return SqliteRunStore(db) if db else RunStore()


def create_app(
    store: RunStoreProtocol | None = None,
    *,
    api_token: str | None = None,
    max_body_bytes: int | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``api_token`` (default: env ``DRIFTGUARD_API_TOKEN``) enables bearer-token auth on every
    ``/api/*`` route except ``/api/health`` and ``/api/config``. ``store`` defaults to a
    SQLite store when ``DRIFTGUARD_DB`` is set, otherwise to a bounded in-memory store.
    """
    token = api_token if api_token is not None else os.environ.get("DRIFTGUARD_API_TOKEN", "")
    token = token.strip()
    if token and len(token) < MIN_TOKEN_CHARS:
        raise DriftGuardError(f"DRIFTGUARD_API_TOKEN must be at least {MIN_TOKEN_CHARS} characters")
    limit = max_body_bytes or int(os.environ.get("DRIFTGUARD_MAX_BODY_BYTES", DEFAULT_MAX_BODY))
    app = FastAPI(
        title="DriftGuard Pro API",
        version=__version__,
        description="Run LLM regression suites, inspect results and fetch reports.",
    )
    runs: RunStoreProtocol = store or _store_from_env()
    app.state.store = runs
    app.add_middleware(BodyLimitMiddleware, max_bytes=limit)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return _error(404, "not_found", str(exc))

    @app.exception_handler(DriftGuardError)
    async def _domain(_: Request, exc: DriftGuardError) -> JSONResponse:
        return _error(400, "bad_request", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__)
        return _error(500, "internal_error", "Internal server error")

    open_paths = {"/api/health", "/api/config"}

    @app.middleware("http")
    async def _security(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if token and path.startswith("/api/") and path not in open_paths:
            header = request.headers.get("authorization", "")
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                supplied.strip().encode(), token.encode()
            ):
                response = _error(401, "unauthorized", "missing or invalid bearer token")
                response.headers["WWW-Authenticate"] = "Bearer"
                return response
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", DASHBOARD_CSP)
        return response

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/config", tags=["meta"])
    def config() -> dict[str, object]:
        return {
            "version": __version__,
            "auth_required": bool(token),
            "persistent": isinstance(runs, SqliteRunStore),
        }

    @app.get("/api/examples", tags=["meta"])
    def examples() -> dict[str, list[str]]:
        return {"examples": _example_names()}

    @app.post("/api/runs", response_model=Report, status_code=201, tags=["runs"])
    def create_run(body: RunRequest) -> Report:
        suite = body.suite
        if suite is None:
            name = body.example or ""
            if name not in _example_names():
                raise NotFoundError(f"unknown example: {name}")
            suite = load_suite(EXAMPLES_DIR / f"{name}.json")
        report = run_suite(suite, body.config)
        runs.add(report)
        return report

    @app.get("/api/runs", response_model=list[RunListItem], tags=["runs"])
    def list_runs(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        suite: Annotated[str | None, Query(max_length=200)] = None,
    ) -> list[RunListItem]:
        return [
            RunListItem(
                run_id=r.metadata.run_id,
                suite_name=r.metadata.suite_name,
                status=r.status,
                generated_at=r.metadata.generated_at,
                total=r.summary.total,
                passed=r.summary.passed,
                failed=r.summary.failed,
                pass_rate=r.summary.pass_rate,
            )
            for r in runs.list(limit=limit, offset=offset, suite=suite)
        ]

    @app.get("/api/runs/{run_id}", response_model=Report, tags=["runs"])
    def get_run(run_id: RunId) -> Report:
        return runs.get(run_id)

    @app.delete("/api/runs/{run_id}", status_code=204, tags=["runs"])
    def delete_run(run_id: RunId) -> HttpResponse:
        runs.delete(run_id)
        return HttpResponse(status_code=204)

    @app.get("/api/runs/{run_id}/failures", response_model=list[CaseResult], tags=["runs"])
    def get_failures(run_id: RunId) -> list[CaseResult]:
        return [r for r in runs.get(run_id).results if r.status is not Status.PASS]

    @app.get("/api/runs/{run_id}/report", tags=["reports"])
    def get_report(
        run_id: RunId,
        format: Annotated[Literal["json", "html", "junit", "md"], Query()] = "json",
    ) -> HttpResponse:
        report = runs.get(run_id)
        content = render(report, format)
        media = {
            "json": "application/json",
            "html": "text/html; charset=utf-8",
            "junit": "application/xml",
            "md": "text/markdown; charset=utf-8",
        }[format]
        suffix = {"json": "json", "html": "html", "junit": "junit.xml", "md": "md"}[format]
        headers = {"Content-Disposition": f'inline; filename="driftguard-{run_id}.{suffix}"'}
        if format == "html":
            headers["Content-Security-Policy"] = REPORT_CSP
        return HttpResponse(content, media_type=media, headers=headers)

    @app.get("/api/diff", response_model=ReportDiff, tags=["runs"])
    def diff(
        old: Annotated[str, Query(pattern=r"^[a-f0-9]{12}$")],
        new: Annotated[str, Query(pattern=r"^[a-f0-9]{12}$")],
    ) -> ReportDiff:
        return diff_reports(runs.get(old), runs.get(new))

    @app.get("/api/trends", response_model=list[TrendPoint], tags=["runs"])
    def trends(
        suite: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=200)] = 30,
    ) -> list[TrendPoint]:
        """Pass-rate history for one suite name, oldest first."""
        points = [
            TrendPoint(
                run_id=r.metadata.run_id,
                generated_at=r.metadata.generated_at,
                status=r.status,
                total=r.summary.total,
                pass_rate=r.summary.pass_rate,
                weighted_pass_rate=r.summary.weighted_pass_rate,
            )
            for r in runs.list(limit=limit, suite=suite)
        ]
        return list(reversed(points))

    @app.post("/api/compare", response_model=Report, status_code=201, tags=["runs"])
    def compare(body: CompareRequest) -> Report:
        report = run_suite(compare_fixtures(body.baseline, body.candidate, body.suite), body.config)
        runs.add(report)
        return report

    @app.post("/api/simulate", response_model=SimulateResponse, tags=["simulator"])
    def simulate_endpoint(body: SimulateRequest) -> SimulateResponse:
        suite = simulate(body.config)
        report = None
        if body.run:
            report = run_suite(suite, body.run_config)
            runs.add(report)
        return SimulateResponse(suite=suite, report=report)

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        index = DASHBOARD_DIR / "index.html"
        if not index.is_file():  # pragma: no cover - packaging problem
            raise SuiteLoadError("dashboard assets are missing from this installation")
        return FileResponse(index, media_type="text/html")

    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")
    return app


app = create_app()

__all__ = ["RunStore", "SqliteRunStore", "app", "create_app"]
