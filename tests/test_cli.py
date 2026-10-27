from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from driftguard import __version__
from driftguard.cli import main

from .conftest import EXAMPLES


def write_suite(tmp: Path, name: str, cases: list[dict]) -> Path:
    p = tmp / name
    p.write_text(json.dumps({"name": name, "cases": cases}), encoding="utf-8")
    return p


PASS_CASE = {"id": "a", "assertions": [{"type": "non_empty"}], "candidate": {"text": "hi"}}
FAIL_CASE = {"id": "a", "assertions": [{"type": "non_empty"}], "candidate": {"text": ""}}
ERR_CASE = {"id": "a", "assertions": [{"type": "non_empty"}]}  # no candidate
INC_CASE = {"id": "a", "candidate": {"text": "hi"}}  # no checks at all


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "COMMAND" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    assert "exit codes" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0 and __version__ in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["run", "--help"])
    assert info.value.code == 0 and "--out-dir" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("case", "code"), [(PASS_CASE, 0), (FAIL_CASE, 1), (ERR_CASE, 2), (INC_CASE, 3)]
)
def test_run_exit_codes(tmp_path: Path, case: dict, code: int) -> None:
    assert main(["run", str(write_suite(tmp_path, "s.json", [case]))]) == code


def test_exit_code_for_empty_suite_is_inconclusive(tmp_path: Path) -> None:
    assert main(["run", str(write_suite(tmp_path, "e.json", []))]) == 3


def test_usage_error_exit_code_is_error() -> None:
    with pytest.raises(SystemExit) as info:
        main(["run"])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        main(["bogus"])
    assert info.value.code == 2


def test_missing_file_and_malformed_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", str(tmp_path / "missing.json")]) == 2
    assert "file not found" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert main(["run", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "malformed JSON" in err and "Traceback" not in err


def test_batch_run_worst_status_and_isolation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = write_suite(tmp_path, "ok.json", [PASS_CASE])
    bad = write_suite(tmp_path, "bad.json", [FAIL_CASE])
    assert main(["run", str(ok), str(bad)]) == 1
    out = capsys.readouterr().out
    assert out.count("DriftGuard report") == 2
    assert main(["run", str(ok), str(tmp_path / "missing.json")]) == 2  # error wins, ok still ran
    assert "Status: PASS" in capsys.readouterr().out


def test_run_directory(tmp_path: Path) -> None:
    d = tmp_path / "suites"
    d.mkdir()
    write_suite(d, "a.json", [PASS_CASE])
    write_suite(d, "b.json", [PASS_CASE])
    assert main(["run", str(d)]) == 0
    assert main(["run", str(tmp_path / "suites" / "..")]) in (0, 1, 2, 3)


def test_out_dir_and_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "reports"
    code = main(["run", str(EXAMPLES / "demo.json"), "--out-dir", str(out), "--output", "json"])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "PASS"
    assert sorted(p.name for p in out.iterdir()) == [
        "demo-support-bot.report.html",
        "demo-support-bot.report.json",
    ]
    assert (
        main(["run", str(EXAMPLES / "demo.json"), "--out-dir", str(out), "--formats", "pdf"]) == 2
    )


def test_min_similarity_override(tmp_path: Path) -> None:
    case = {
        "id": "a",
        "baseline": {"text": "the cat sat"},
        "candidate": {"text": "the cat sat down now"},
    }
    path = write_suite(tmp_path, "s.json", [case])
    assert main(["run", str(path), "--min-similarity", "0.99"]) == 1
    assert main(["run", str(path), "--min-similarity", "0.1"]) == 0
    assert main(["run", str(path), "--min-similarity", "7"]) == 2


def test_embedding_unavailable_is_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    try:
        import sentence_transformers  # noqa: F401

        pytest.skip("optional extra installed")
    except ImportError:
        pass
    path = write_suite(tmp_path, "s.json", [PASS_CASE])
    assert main(["run", str(path), "--similarity", "embedding"]) == 2
    assert "embeddings" in capsys.readouterr().err


def test_compare_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, cand = str(EXAMPLES / "baseline.json"), str(EXAMPLES / "candidate.json")
    assert main(["compare", base, cand, "--suite", str(EXAMPLES / "demo.json")]) == 1
    assert "missing keys: eta_days" in capsys.readouterr().out
    assert main(["compare", base, base]) == 0
    assert main(["compare", base, str(tmp_path / "nope.json")]) == 2


def test_report_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r"
    assert (
        main(["run", str(EXAMPLES / "regression.json"), "--out-dir", str(out), "--formats", "json"])
        == 1
    )
    capsys.readouterr()
    report_json = next(out.glob("*.json"))
    assert main(["report", str(report_json)]) == 0
    assert "Status: FAIL" in capsys.readouterr().out
    html_path = tmp_path / "out.html"
    assert main(["report", str(report_json), "--format", "html", "-o", str(html_path)]) == 0
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert main(["report", str(tmp_path / "nope.json")]) == 2
    other = tmp_path / "notreport.json"
    other.write_text("{}", encoding="utf-8")
    assert main(["report", str(other)]) == 2


def test_simulate_command_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert main(["simulate", str(EXAMPLES / "simulator.json"), "-o", str(a)]) == 0
    assert main(["simulate", str(EXAMPLES / "simulator.json"), "-o", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    assert main(["run", str(a)]) == 1
    c = tmp_path / "c.json"
    assert main(["simulate", str(EXAMPLES / "simulator.json"), "--seed", "999", "-o", str(c)]) == 0
    assert c.read_bytes() != a.read_bytes()
    assert main(["simulate", str(tmp_path / "missing.json")]) == 2


def test_record_command_with_fake_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    suite = write_suite(
        tmp_path, "s.json", [{"id": "a", "prompt": "hi"}, {"id": "b", "prompt": ""}]
    )
    out = tmp_path / "fx.json"
    assert main(["record", str(suite), "--provider", "openai", "--model", "m", "-o", str(out)]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err  # no key -> clean error, no traceback

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890abcdef")

    class Completions:
        def create(self, **kw):
            msg = types.SimpleNamespace(content="answer")
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=msg)],
                usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2),
            )

    class Client:
        def __init__(self, api_key, **settings):
            self.chat = types.SimpleNamespace(completions=Completions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=Client))
    assert (
        main(
            [
                "record",
                str(suite),
                "--provider",
                "openai",
                "--model",
                "m",
                "-o",
                str(out),
                "--price-in",
                "1",
                "--price-out",
                "2",
            ]
        )
        == 0
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert list(data["responses"]) == ["a"] and data["responses"]["a"]["cost_usd"] is not None
    assert "sk-test" not in out.read_text(encoding="utf-8")
    assert (
        main(
            [
                "record",
                str(suite),
                "--provider",
                "openai",
                "--model",
                "m",
                "-o",
                str(out),
                "--price-in",
                "1",
            ]
        )
        == 2
    )
