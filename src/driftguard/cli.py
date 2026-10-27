"""Command line interface.

Exit codes: PASS=0, FAIL=1, ERROR=2, INCONCLUSIVE=3.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from . import __version__
from .diff import diff_reports
from .engine import compare_fixtures, run_suite
from .errors import DriftGuardError
from .loader import (
    discover_suites,
    load_fixtures,
    load_report,
    load_simulator_config,
    load_suite,
)
from .logging_utils import configure_logging, get_logger
from .models import Fixtures, Report, RunConfig, Status, Suite, worst_status
from .providers import PROVIDERS, Pricing, get_provider
from .reports import (
    REPORT_FORMATS,
    render,
    render_diff_markdown,
    render_diff_text,
    render_text,
    write_report,
)
from .simulator import SimulatorConfig, simulate

log = get_logger("cli")

EPILOG = """exit codes:
  0  PASS          every check passed
  1  FAIL          at least one assertion or drift threshold failed
  2  ERROR         a file, config or evaluation error occurred
  3  INCONCLUSIVE  nothing could be verified (e.g. no cases, or cases with no checks)
"""


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--similarity",
        choices=["lexical", "embedding"],
        default="lexical",
        help="similarity method (embedding needs the 'embeddings' extra)",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="seed for bootstrap/permutation (default 0)"
    )
    parser.add_argument(
        "--resamples",
        type=int,
        default=2000,
        metavar="N",
        help="bootstrap resamples (100-20000, default 2000)",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        metavar="X",
        help="override the suite's minimum text similarity (0-1)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="what to print to stdout (default: text summary)",
    )
    parser.add_argument(
        "--out-dir", metavar="DIR", help="write <suite>.report.json/html files into DIR"
    )
    parser.add_argument(
        "--formats",
        default="json,html",
        metavar="LIST",
        help="comma-separated formats for --out-dir: json,html,junit,md",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="more logging (-vv for debug)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="driftguard",
        description="Detect regressions and drift in LLM app behaviour from saved fixtures.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"driftguard {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = sub.add_parser(
        "run",
        help="run one or more test suites (files or directories)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument("suites", nargs="+", metavar="SUITE", help="suite JSON file(s) or directories")
    _add_run_options(run)

    cmp_ = sub.add_parser(
        "compare",
        help="compare baseline fixtures against candidate fixtures",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cmp_.add_argument("baseline", help="baseline fixtures JSON ({'responses': {id: {...}}})")
    cmp_.add_argument("candidate", help="candidate fixtures JSON")
    cmp_.add_argument(
        "--suite", metavar="SUITE", help="suite providing assertions/weights/thresholds"
    )
    _add_run_options(cmp_)

    rep = sub.add_parser("report", help="render a saved JSON report as text, HTML or JSON")
    rep.add_argument("report", help="report JSON produced by 'run' or 'compare'")
    rep.add_argument("--format", choices=["text", "html", "json", "junit", "md"], default="text")
    rep.add_argument("-o", "--out", metavar="FILE", help="write to FILE instead of stdout")
    rep.add_argument("-v", "--verbose", action="count", default=0)

    sim = sub.add_parser("simulate", help="generate a deterministic simulated suite")
    sim.add_argument("config", help="simulator config JSON")
    sim.add_argument(
        "-o", "--out", metavar="FILE", help="write the suite to FILE (default: stdout)"
    )
    sim.add_argument("--seed", type=int, help="override the config seed")
    sim.add_argument("-v", "--verbose", action="count", default=0)

    rec = sub.add_parser("record", help="record live provider responses into a fixtures file")
    rec.add_argument("suite", help="suite whose case prompts will be sent to the provider")
    rec.add_argument("--provider", choices=PROVIDERS, required=True)
    rec.add_argument("--model", required=True, help="model name (required; no default is assumed)")
    rec.add_argument("-o", "--out", required=True, metavar="FILE")
    rec.add_argument("--max-tokens", type=int, default=1024)
    rec.add_argument(
        "--price-in", type=float, help="USD per 1M prompt tokens (enables cost tracking)"
    )
    rec.add_argument("--price-out", type=float, help="USD per 1M completion tokens")
    rec.add_argument("-v", "--verbose", action="count", default=0)

    dif = sub.add_parser(
        "diff",
        help="compare two saved reports and flag regressions (exit 1 if any case got worse)",
    )
    dif.add_argument("old", help="earlier report JSON (the reference)")
    dif.add_argument("new", help="later report JSON")
    dif.add_argument("--output", choices=["text", "json", "md"], default="text")
    dif.add_argument("-v", "--verbose", action="count", default=0)

    val = sub.add_parser("validate", help="check suite files without running them")
    val.add_argument("suites", nargs="+", metavar="SUITE")
    val.add_argument("-v", "--verbose", action="count", default=0)

    sch = sub.add_parser("schema", help="print the JSON Schema of a file format (for editors/CI)")
    sch.add_argument("kind", choices=["suite", "fixtures", "simulator", "report"])
    sch.add_argument("-v", "--verbose", action="count", default=0)

    srv = sub.add_parser("serve", help="start the API and dashboard")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument(
        "--db", metavar="FILE", help="persist runs in a SQLite file (sets DRIFTGUARD_DB)"
    )
    srv.add_argument("-v", "--verbose", action="count", default=0)
    return parser


def _config_from(args: argparse.Namespace) -> RunConfig:
    return RunConfig(similarity=args.similarity, seed=args.seed, bootstrap_resamples=args.resamples)


def _emit(reports: list[Report], args: argparse.Namespace) -> None:
    if args.out_dir:
        formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
        for fmt in formats:
            if fmt not in REPORT_FORMATS:
                raise DriftGuardError(
                    f"unsupported format {fmt!r}; choose from {', '.join(REPORT_FORMATS)}"
                )
        for report in reports:
            for path in write_report(report, args.out_dir, formats):
                _eprint(f"wrote {path}")
    if args.output == "json":
        payload = [r.model_dump(mode="json") for r in reports]
        print(
            json.dumps(payload[0] if len(payload) == 1 else payload, indent=2, ensure_ascii=False)
        )
    else:
        print("\n".join(render_text(r) for r in reports), end="")


def _prepare(suite: Suite, args: argparse.Namespace) -> Suite:
    if args.min_similarity is not None:
        if not 0 <= args.min_similarity <= 1:
            raise DriftGuardError("--min-similarity must be between 0 and 1")
        thresholds = suite.thresholds.model_copy(update={"min_similarity": args.min_similarity})
        suite = suite.model_copy(update={"thresholds": thresholds})
    return suite


def cmd_run(args: argparse.Namespace) -> int:
    config = _config_from(args)
    try:
        paths = discover_suites(args.suites)
    except DriftGuardError as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    statuses: list[Status] = []
    reports: list[Report] = []
    for path in paths:
        try:
            report = run_suite(_prepare(load_suite(path), args), config)
        except DriftGuardError as exc:
            _eprint(f"ERROR: {path}: {exc}")
            statuses.append(Status.ERROR)
            continue
        reports.append(report)
        statuses.append(report.status)
    try:
        if reports:
            _emit(reports, args)
    except DriftGuardError as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    return worst_status(statuses).exit_code


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        baseline = load_fixtures(args.baseline)
        candidate = load_fixtures(args.candidate)
        suite = load_suite(args.suite) if args.suite else None
        built = _prepare(compare_fixtures(baseline, candidate, suite), args)
        report = run_suite(built, _config_from(args))
        _emit([report], args)
    except DriftGuardError as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    return report.status.exit_code


def cmd_report(args: argparse.Namespace) -> int:
    try:
        report = load_report(args.report)
        content = render(report, args.format)
        if args.out:
            Path(args.out).write_text(content, encoding="utf-8", newline="\n")
            _eprint(f"wrote {args.out}")
        else:
            print(content, end="")
    except (DriftGuardError, OSError) as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    try:
        config = load_simulator_config(args.config)
        if args.seed is not None:
            config = config.model_copy(update={"seed": args.seed})
        suite = simulate(config)
        content = (
            json.dumps(suite.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False)
            + "\n"
        )
        if args.out:
            Path(args.out).write_text(content, encoding="utf-8", newline="\n")
            _eprint(f"wrote {args.out}")
        else:
            print(content, end="")
    except (DriftGuardError, OSError) as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    try:
        suite = load_suite(args.suite)
        pricing = None
        if args.price_in is not None or args.price_out is not None:
            if args.price_in is None or args.price_out is None:
                raise DriftGuardError("--price-in and --price-out must be given together")
            pricing = Pricing(args.price_in, args.price_out)
        provider = get_provider(args.provider, args.model, pricing)
        responses = {}
        for case in suite.cases:
            if not case.prompt.strip():
                _eprint(f"skipping {case.id}: empty prompt")
                continue
            log.info("recording case %s", case.id)
            responses[case.id] = provider.generate(case.prompt, max_tokens=args.max_tokens)
        fixtures = Fixtures(name=f"{args.provider}:{args.model}", responses=responses)
        Path(args.out).write_text(
            json.dumps(fixtures.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _eprint(f"recorded {len(responses)} responses to {args.out}")
    except (DriftGuardError, OSError) as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        result = diff_reports(load_report(args.old), load_report(args.new))
    except DriftGuardError as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    if args.output == "json":
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    elif args.output == "md":
        print(render_diff_markdown(result), end="")
    else:
        print(render_diff_text(result), end="")
    return 1 if result.has_regressions else 0


def cmd_validate(args: argparse.Namespace) -> int:
    worst = 0
    try:
        paths = discover_suites(args.suites)
    except DriftGuardError as exc:
        _eprint(f"ERROR: {exc}")
        return Status.ERROR.exit_code
    for path in paths:
        try:
            suite = load_suite(path)
        except DriftGuardError as exc:
            _eprint(f"INVALID {path}: {exc}")
            worst = Status.ERROR.exit_code
        else:
            print(f"OK {path} ({len(suite.cases)} cases)")
    return worst


def cmd_schema(args: argparse.Namespace) -> int:
    models: dict[str, type[BaseModel]] = {
        "suite": Suite,
        "fixtures": Fixtures,
        "simulator": SimulatorConfig,
        "report": Report,
    }
    print(json.dumps(models[args.kind].model_json_schema(by_alias=True), indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.db:
        os.environ["DRIFTGUARD_DB"] = args.db
    try:
        import uvicorn
    except ImportError:
        _eprint('ERROR: uvicorn is not installed: python -m pip install "driftguard-pro"')
        return Status.ERROR.exit_code
    uvicorn.run("driftguard.api:app", host=args.host, port=args.port, log_level="info")
    return 0


_COMMANDS = {
    "diff": cmd_diff,
    "validate": cmd_validate,
    "schema": cmd_schema,
    "run": cmd_run,
    "compare": cmd_compare,
    "report": cmd_report,
    "simulate": cmd_simulate,
    "record": cmd_record,
    "serve": cmd_serve,
}


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    configure_logging(getattr(args, "verbose", 0))
    try:
        return _COMMANDS[args.command](args)
    except BrokenPipeError:
        # Output closed early (e.g. `| head`): exit quietly without a traceback.
        with contextlib.suppress(OSError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        _eprint("interrupted")
        return Status.ERROR.exit_code
    except Exception as exc:  # last resort: never show a traceback for unexpected errors
        log.exception("unexpected error")
        _eprint(f"ERROR: unexpected {type(exc).__name__}; re-run with -vv for details")
        return Status.ERROR.exit_code


if __name__ == "__main__":
    sys.exit(main())
