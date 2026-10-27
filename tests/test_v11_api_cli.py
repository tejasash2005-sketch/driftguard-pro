from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import driftguard.cli as cli_module
from driftguard.api import create_app
from driftguard.cli import main
from driftguard.errors import DriftGuardError
from driftguard.store import RunStore, SqliteRunStore

from .conftest import EXAMPLES

TOKEN = "t" * 24


def suite_body(name: str = "api", candidate: str = "hello") -> dict:
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


def mk(**kw) -> TestClient:
    return TestClient(create_app(RunStore(), **kw), raise_server_exceptions=False)


# ------------------------------------------------------------------ auth


def test_auth_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DRIFTGUARD_API_TOKEN", raising=False)
    c = mk()
    assert c.get("/api/runs").status_code == 200
    assert c.get("/api/config").json()["auth_required"] is False


def test_token_auth() -> None:
    c = mk(api_token=TOKEN)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/config").json() == {
        "version": c.get("/api/health").json()["version"],
        "auth_required": True,
        "persistent": False,
    }
    assert c.get("/").status_code == 200  # dashboard shell is public; data is not
    assert c.get("/static/app.js").status_code == 200
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": TOKEN},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer "},
    ):
        resp = c.get("/api/runs", headers=headers)
        assert resp.status_code == 401, headers
        assert resp.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in resp.text
    good = {"Authorization": f"Bearer {TOKEN}"}
    assert c.get("/api/runs", headers=good).status_code == 200
    assert c.post("/api/runs", json={"example": "demo"}).status_code == 401
    assert c.post("/api/runs", json={"example": "demo"}, headers=good).status_code == 201
    assert c.delete("/api/runs/" + "0" * 12).status_code == 401


def test_token_from_env_and_minimum_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRIFTGUARD_API_TOKEN", TOKEN)
    assert TestClient(create_app(RunStore())).get("/api/runs").status_code == 401
    with pytest.raises(DriftGuardError, match="at least 16"):
        create_app(RunStore(), api_token="short")


# ------------------------------------------------------------------ body limit


def test_body_limit_content_length() -> None:
    c = mk(max_body_bytes=2000)
    big = {"suite": suite_body(candidate="x" * 5000)}
    resp = c.post("/api/runs", json=big)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large"
    assert c.post("/api/runs", json={"example": "demo"}).status_code == 201


def test_body_limit_chunked_without_content_length() -> None:
    c = mk(max_body_bytes=2000)

    def chunks():
        yield b'{"suite": '
        for _ in range(10):
            yield b" " * 1000
        yield b"{}}"

    resp = c.post("/api/runs", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413


# ------------------------------------------------------------------ new endpoints


def test_pagination_delete_and_filter() -> None:
    c = mk()
    ids = []
    for i in range(4):
        body = c.post(
            "/api/runs", json={"suite": suite_body(f"s{i % 2}", candidate=f"hello {i}")}
        ).json()
        ids.append(body["metadata"]["run_id"])
    assert [r["run_id"] for r in c.get("/api/runs").json()] == ids[::-1]
    assert len(c.get("/api/runs", params={"limit": 2}).json()) == 2
    assert len(c.get("/api/runs", params={"limit": 2, "offset": 3}).json()) == 1
    assert len(c.get("/api/runs", params={"suite": "s1"}).json()) == 2
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        assert c.get("/api/runs", params=bad).status_code == 422
    assert c.delete(f"/api/runs/{ids[0]}").status_code == 204
    assert c.get(f"/api/runs/{ids[0]}").status_code == 404
    assert c.delete(f"/api/runs/{ids[0]}").status_code == 404
    assert c.delete("/api/runs/not-an-id").status_code == 422


def test_diff_endpoint() -> None:
    c = mk()
    good = c.post("/api/runs", json={"suite": suite_body("s", "hello")}).json()["metadata"][
        "run_id"
    ]
    bad_suite = suite_body("s", "")
    bad = c.post("/api/runs", json={"suite": bad_suite}).json()["metadata"]["run_id"]
    d = c.get("/api/diff", params={"old": good, "new": bad}).json()
    assert [x["id"] for x in d["regressions"]] == ["a"]
    assert c.get("/api/diff", params={"old": good, "new": good}).json()["regressions"] == []
    assert c.get("/api/diff", params={"old": good, "new": "0" * 12}).status_code == 404
    assert c.get("/api/diff", params={"old": "zz", "new": good}).status_code == 422
    assert c.get("/api/diff", params={"old": good}).status_code == 422


def test_trends_endpoint() -> None:
    c = mk()
    for text in ("one", "", "three"):
        body = suite_body("trend", text)
        body["cases"][0]["baseline"] = {"text": text}  # no text drift: only non_empty can fail
        c.post("/api/runs", json={"suite": body})
    c.post("/api/runs", json={"suite": suite_body("other", "x")})
    points = c.get("/api/trends", params={"suite": "trend"}).json()
    assert [p["pass_rate"] for p in points] == [1.0, 0.0, 1.0]  # oldest first
    assert c.get("/api/trends", params={"suite": "none"}).json() == []
    assert c.get("/api/trends").status_code == 422


def test_report_formats_endpoint() -> None:
    c = mk()
    rid = c.post("/api/runs", json={"example": "regression"}).json()["metadata"]["run_id"]
    junit = c.get(f"/api/runs/{rid}/report", params={"format": "junit"})
    assert junit.headers["content-type"].startswith("application/xml")
    assert ET.fromstring(junit.text).get("failures") == "3"
    md = c.get(f"/api/runs/{rid}/report", params={"format": "md"})
    assert md.headers["content-type"].startswith("text/markdown") and "**FAIL**" in md.text


def test_sqlite_backed_app_persists_across_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFTGUARD_DB", str(tmp_path / "x" / "runs.db"))
    first = TestClient(create_app())
    rid = first.post("/api/runs", json={"example": "demo"}).json()["metadata"]["run_id"]
    assert first.get("/api/config").json()["persistent"] is True
    second = TestClient(create_app())  # simulates a process restart
    assert second.get(f"/api/runs/{rid}").json()["metadata"]["run_id"] == rid
    assert isinstance(second.app.state.store, SqliteRunStore)  # type: ignore[attr-defined]


def test_dashboard_has_new_ui_hooks() -> None:
    page = mk().get("/").text
    for hook in ("compare-select", "trend", "token-form", "btn-delete"):
        assert hook in page, hook
    js = mk().get("/static/app.js").text
    assert "innerHTML" not in js and "Authorization" in js and "sessionStorage" in js


# ------------------------------------------------------------------ CLI


def run_report(tmp_path: Path, suite_name: str, candidate: str, out: str) -> Path:
    suite = {
        "name": suite_name,
        "cases": [
            {"id": "a", "assertions": [{"type": "non_empty"}], "candidate": {"text": candidate}},
            {"id": "b", "assertions": [{"type": "non_empty"}], "candidate": {"text": "fine"}},
        ],
    }
    path = tmp_path / f"{out}.suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    main(["run", str(path), "--out-dir", str(tmp_path / out), "--formats", "json"])
    return next((tmp_path / out).glob("*.json"))


def test_cli_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = run_report(tmp_path, "s", "ok", "good")
    bad = run_report(tmp_path, "s", "", "bad")
    capsys.readouterr()
    assert main(["diff", str(good), str(good)]) == 0
    assert "no regressions" in capsys.readouterr().out
    assert main(["diff", str(good), str(bad)]) == 1
    assert "[REGRESSED] a: PASS -> FAIL" in capsys.readouterr().out
    assert main(["diff", str(bad), str(good)]) == 0  # improvement only
    capsys.readouterr()
    assert main(["diff", str(good), str(bad), "--output", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["regressions"][0]["id"] == "a"
    assert main(["diff", str(good), str(bad), "--output", "md"]) == 1
    assert "## DriftGuard diff" in capsys.readouterr().out
    assert main(["diff", str(good), str(tmp_path / "nope.json")]) == 2
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{bad json", encoding="utf-8")
    assert main(["diff", str(good), str(malformed)]) == 2
    assert "malformed JSON" in capsys.readouterr().err
    incompatible = run_report(tmp_path, "another-suite", "ok", "incompatible")
    assert main(["diff", str(good), str(incompatible)]) == 2
    assert "different suites" in capsys.readouterr().err


def test_offline_regression_gate_demo() -> None:
    root = EXAMPLES.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "regression_gate_demo.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "candidate-acceptable: PASS" in result.stdout
    assert "candidate-degraded: FAIL" in result.stdout
    assert "drift:similarity" in result.stdout and "drift:latency" in result.stdout


def test_cli_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(EXAMPLES / "demo.json"), str(EXAMPLES / "regression.json")]) == 0
    assert capsys.readouterr().out.count("OK ") == 2
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"name": "x", "cases": [{"id": "a", "assertions": [{"type": "nope"}]}]})
    )
    assert main(["validate", str(EXAMPLES / "demo.json"), str(bad)]) == 2
    captured = capsys.readouterr()
    assert "INVALID" in captured.err and "OK" in captured.out
    assert main(["validate", str(tmp_path / "missing.json")]) == 2


@pytest.mark.parametrize("kind", ["suite", "fixtures", "simulator", "report"])
def test_cli_schema(kind: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", kind]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["type"] == "object" and "properties" in schema


def test_suite_schema_validates_shipped_example(capsys: pytest.CaptureFixture[str]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    main(["schema", "suite"])
    schema = json.loads(capsys.readouterr().out)
    jsonschema.validate(json.loads((EXAMPLES / "demo.json").read_text()), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"name": "x", "cases": [{"id": "a", "assertions": [{"type": "nope"}]}]}, schema
        )


def test_cli_new_formats(tmp_path: Path) -> None:
    out = tmp_path / "o"
    assert (
        main(
            [
                "run",
                str(EXAMPLES / "regression.json"),
                "--out-dir",
                str(out),
                "--formats",
                "junit,md",
            ]
        )
        == 1
    )
    assert sorted(p.name for p in out.iterdir()) == [
        "simulated-regression.junit.xml",
        "simulated-regression.report.md",
    ]
    ET.parse(out / "simulated-regression.junit.xml")
    rep = tmp_path / "r.json"
    main(
        ["run", str(EXAMPLES / "demo.json"), "--out-dir", str(tmp_path / "d"), "--formats", "json"]
    )
    rep = next((tmp_path / "d").glob("*.json"))
    assert main(["report", str(rep), "--format", "junit", "-o", str(tmp_path / "j.xml")]) == 0
    assert main(["report", str(rep), "--format", "md", "-o", str(tmp_path / "m.md")]) == 0


def test_cli_serve_db_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    import sys
    import types

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: seen.update(k))
    )
    monkeypatch.delenv("DRIFTGUARD_DB", raising=False)
    assert main(["serve", "--db", "/tmp/x.db", "--port", "9999"]) == 0
    assert os.environ["DRIFTGUARD_DB"] == "/tmp/x.db" and seen["port"] == 9999
    monkeypatch.delenv("DRIFTGUARD_DB", raising=False)


def test_cli_broken_pipe_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_args):
        raise BrokenPipeError

    monkeypatch.setitem(cli_module._COMMANDS, "schema", boom)
    # dup2 onto a real fd would clobber pytest's capture; make it a no-op
    monkeypatch.setattr(cli_module.os, "dup2", lambda *a: None)
    monkeypatch.setattr(cli_module.sys.stdout, "fileno", lambda: 1, raising=False)
    assert main(["schema", "suite"]) == 0
