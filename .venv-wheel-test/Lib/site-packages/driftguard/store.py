"""Run storage backends: bounded in-memory (default) and SQLite (opt-in persistence)."""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

from .errors import NotFoundError
from .models import Report

MAX_STORED_RUNS = 200


class RunStoreProtocol(Protocol):
    def add(self, report: Report) -> None: ...
    def get(self, run_id: str) -> Report: ...
    def list(
        self, limit: int | None = None, offset: int = 0, suite: str | None = None
    ) -> list[Report]: ...
    def delete(self, run_id: str) -> None: ...


class RunStore:
    """Thread-safe, bounded, in-memory store (newest first when listing)."""

    def __init__(self, max_runs: int = MAX_STORED_RUNS) -> None:
        self._max = max_runs
        self._runs: OrderedDict[str, Report] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, report: Report) -> None:
        with self._lock:
            run_id = report.metadata.run_id
            self._runs.pop(run_id, None)
            self._runs[run_id] = report
            while len(self._runs) > self._max:
                self._runs.popitem(last=False)

    def get(self, run_id: str) -> Report:
        with self._lock:
            report = self._runs.get(run_id)
        if report is None:
            raise NotFoundError(f"run not found: {run_id}")
        return report

    def list(
        self, limit: int | None = None, offset: int = 0, suite: str | None = None
    ) -> list[Report]:
        with self._lock:
            items = list(reversed(self._runs.values()))
        if suite is not None:
            items = [r for r in items if r.metadata.suite_name == suite]
        return items[offset : None if limit is None else offset + limit]

    def delete(self, run_id: str) -> None:
        with self._lock:
            if self._runs.pop(run_id, None) is None:
                raise NotFoundError(f"run not found: {run_id}")


class SqliteRunStore:
    """Durable store backed by a single SQLite file (stdlib only, parameterized SQL)."""

    def __init__(self, path: str | Path, max_runs: int = MAX_STORED_RUNS) -> None:
        self._path = Path(path)
        self._max = max_runs
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS runs ("
                    "seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT UNIQUE NOT NULL, "
                    "suite_name TEXT NOT NULL, payload TEXT NOT NULL)"
                )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def add(self, report: Report) -> None:
        payload = report.model_dump_json()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("DELETE FROM runs WHERE run_id = ?", (report.metadata.run_id,))
                    conn.execute(
                        "INSERT INTO runs (run_id, suite_name, payload) VALUES (?, ?, ?)",
                        (report.metadata.run_id, report.metadata.suite_name, payload),
                    )
                    conn.execute(
                        "DELETE FROM runs WHERE seq NOT IN "
                        "(SELECT seq FROM runs ORDER BY seq DESC LIMIT ?)",
                        (self._max,),
                    )
            finally:
                conn.close()

    def get(self, run_id: str) -> Report:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            raise NotFoundError(f"run not found: {run_id}")
        return Report.model_validate_json(row[0])

    def list(
        self, limit: int | None = None, offset: int = 0, suite: str | None = None
    ) -> list[Report]:
        sql = "SELECT payload FROM runs"
        args: list[object] = []
        if suite is not None:
            sql += " WHERE suite_name = ?"
            args.append(suite)
        sql += " ORDER BY seq DESC LIMIT ? OFFSET ?"
        args += [-1 if limit is None else limit, offset]
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, args).fetchall()
            finally:
                conn.close()
        return [Report.model_validate_json(r[0]) for r in rows]

    def delete(self, run_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            finally:
                conn.close()
        if cur.rowcount == 0:
            raise NotFoundError(f"run not found: {run_id}")
