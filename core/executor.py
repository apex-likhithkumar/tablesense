"""Run validated SQL, bounded by a wall-clock timeout.

DuckDB has no per-statement timeout setting, so a watchdog timer interrupts the
connection instead. Without this one pathological cross join hangs the app.
"""

import threading
import time
from dataclasses import dataclass

import duckdb
import pandas as pd


@dataclass(frozen=True)
class QueryResult:
    frame: pd.DataFrame
    row_count: int
    elapsed_ms: int


class QueryTimeout(RuntimeError):
    pass


class QueryFailed(RuntimeError):
    pass


def execute(con: duckdb.DuckDBPyConnection, sql: str, timeout_seconds: int) -> QueryResult:
    watchdog = threading.Timer(timeout_seconds, con.interrupt)
    watchdog.start()
    started = time.perf_counter()

    try:
        frame = con.execute(sql).fetch_df()
    except duckdb.InterruptException as exc:
        raise QueryTimeout(
            f"Query exceeded the {timeout_seconds}s limit and was cancelled."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - message is fed back to the model for repair
        raise QueryFailed(str(exc)) from exc
    finally:
        watchdog.cancel()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return QueryResult(frame=frame, row_count=len(frame), elapsed_ms=elapsed_ms)
