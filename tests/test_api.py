from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from driftguard.api import RunStore, create_app
from driftguard.engine import run_suite

from .conftest import EXAMPLES, make_case, make_suite


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(RunStore()), raise_server_exceptions=False)


def suite_payload(candidate: str = "hello", name: str = "api-suite") -> dict:
    return {
        "name": name,
        "cases": [
            {
                "id": "a",
                "assertions": [{"type": "non_empty"}],
                "baseline": {"text": "hello"},
                "candidate": {"text": candidate},
            }
        ],
    }


def test_health_and_examples(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/examples").json() == {"examples": ["demo", "regression"]}


def test_run_example_and_inspect(client: TestClient) -> None:
    created = client.post("/api/runs", json={"example": "regression"})
    assert created.status_code == 201
    report = created.json()
    run_id = report["metadata"]["run_id"]
    assert report["status"] == "FAIL" and report["summary"]["total"] == 8

    listing = client.get("/api/runs").json()
    assert listing[0]["run_id"] == run_id and listing[0]["status"] == "FAIL"

    assert client.get(f"/api/runs/{run_id}").json() == report
    failures = client.get(f"/api/runs/{run_id}/failures").json()
    assert failures and all(f["status"] != "PASS" for f in failures)

    as_json = client.get(f"/api/runs/{run_id}/report", params={"format": "json"})
    assert as_json.headers["content-type"].startswith("application/json")
    assert as_json.json()["metadata"]["run_id"] == run_id
    as_html = client.get(f"/api/runs/{run_id}/report", params={"format": "html"})
    assert as_html.headers["content-type"].startswith("text/html")
    assert "DriftGuard" not in as_html.text or "simulated-regression" in as_html.text
    assert "default-src 'none'" in as_html.headers["content-security-policy"]


def test_run_inline_suite_matches_engine(client: TestClient) -> None:
    body = suite_payload()
    api_report = client.post("/api/runs", json={"suite": body, "config": {"seed": 3}}).json()
    from driftguard.models import RunConfig, Suite

    local = run_suite(Suite.model_validate(body), RunConfig(seed=3))
    assert api_report["metadata"]["run_id"] == local.metadata.run_id
    assert api_report["status"] == "PASS"


def test_run_demo_passes(client: TestClient) -> None:
    assert client.post("/api/runs", json={"example": "demo"}).json()["status"] == "PASS"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"suite": suite_payload(), "example": "demo"},
        {"example": "../../etc/passwd"},
        {"example": "demo.json"},
        {"example": "a" * 100},
        {"suite": {"name": "", "cases": []}},
        {"suite": {"name": "s", "cases": [{"id": "x"}, {"id": "x"}]}},
        {"suite": {"name": "s", "cases": [{"id": "x", "weight": -1}]}},
        {"suite": suite_payload(), "config": {"bootstrap_resamples": 10**9}},
        {"suite": suite_payload(), "surprise": 1},
    ],
)
def test_invalid_run_requests_are_rejected(client: TestClient, body: dict) -> None:
    resp = client.post("/api/runs", json=body)
    assert resp.status_code == 422, resp.text


def test_unknown_example_is_404_and_malformed_json_is_422(client: TestClient) -> None:
    resp = client.post("/api/runs", json={"example": "nope"})
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"
    assert (
        client.post(
            "/api/runs", content="{bad", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert client.post("/api/runs", json=[1, 2]).status_code == 422
    assert client.post("/api/runs").status_code == 422


def test_not_found_and_bad_ids(client: TestClient) -> None:
    assert client.get("/api/runs/" + "0" * 12).status_code == 404
    assert client.get("/api/runs/NOT-A-VALID-ID").status_code == 422
    assert client.get("/api/runs/" + "0" * 12 + "/report").status_code == 404
    assert client.get("/api/runs/" + "0" * 12 + "/failures").status_code == 404
    run_id = client.post("/api/runs", json={"example": "demo"}).json()["metadata"]["run_id"]
    assert client.get(f"/api/runs/{run_id}/report", params={"format": "pdf"}).status_code == 422


def test_empty_listing(client: TestClient) -> None:
    assert client.get("/api/runs").json() == []


def test_empty_suite_is_inconclusive_not_a_crash(client: TestClient) -> None:
    report = client.post("/api/runs", json={"suite": {"name": "empty", "cases": []}}).json()
    assert report["status"] == "INCONCLUSIVE" and report["summary"]["pass_rate"] is None


def test_compare_endpoint(client: TestClient) -> None:
    base = json.loads((EXAMPLES / "baseline.json").read_text())
    cand = json.loads((EXAMPLES / "candidate.json").read_text())
    suite = json.loads((EXAMPLES / "demo.json").read_text())
    resp = client.post("/api/compare", json={"baseline": base, "candidate": cand, "suite": suite})
    assert resp.status_code == 201 and resp.json()["status"] == "FAIL"
    assert client.post("/api/compare", json={"baseline": {}, "candidate": cand}).status_code == 422


def test_simulate_endpoint(client: TestClient) -> None:
    config = json.loads((EXAMPLES / "simulator.json").read_text())
    first = client.post("/api/simulate", json={"config": config}).json()
    second = client.post("/api/simulate", json={"config": config}).json()
    assert first == second and first["report"] is None and len(first["suite"]["cases"]) == 8
    with_run = client.post("/api/simulate", json={"config": config, "run": True}).json()
    assert with_run["report"]["status"] == "FAIL"
    assert client.post("/api/simulate", json={"config": {"cases": []}}).status_code == 422


def test_run_store_is_bounded() -> None:
    store = RunStore(max_runs=2)
    reports = [run_suite(make_suite(make_case(), name=f"s{i}")) for i in range(3)]
    for r in reports:
        store.add(r)
    assert [r.metadata.suite_name for r in store.list()] == ["s2", "s1"]


def test_unhandled_errors_return_generic_500(monkeypatch: pytest.MonkeyPatch) -> None:
    import driftguard.api as api_module

    def boom(*a, **k):
        raise RuntimeError("secret internal detail sk-leak-1234567890")

    monkeypatch.setattr(api_module, "run_suite", boom)
    c = TestClient(create_app(RunStore()), raise_server_exceptions=False)
    resp = c.post("/api/runs", json={"suite": suite_payload()})
    assert resp.status_code == 500
    assert resp.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}


def test_domain_errors_map_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    import driftguard.api as api_module
    from driftguard.errors import DriftGuardError

    def bad(*a, **k):
        raise DriftGuardError("nope")

    monkeypatch.setattr(api_module, "run_suite", bad)
    c = TestClient(create_app(RunStore()), raise_server_exceptions=False)
    resp = c.post("/api/runs", json={"suite": suite_payload()})
    assert resp.status_code == 400 and resp.json()["error"]["message"] == "nope"


def test_dashboard_and_static_assets(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "DriftGuard" in page.text and "/static/app.js" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "innerHTML" not in js.text  # no markup injection sink
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/../api.py").status_code in (400, 404)
    assert client.get("/static/nope.js").status_code == 404
    assert "/api/runs" in client.get("/openapi.json").text
