"""plan -> guard -> execute, with a bounded repair loop.

Every failure the guard or the database produces is fed back to the model as
text. After `max_repair_attempts` the app refuses rather than guessing.
"""

import time
from dataclasses import dataclass

import duckdb
import pandas as pd

from core import charts, executor, guard, planner
from core.config import settings
from core.runlog import Attempt, RunRecord


@dataclass
class Answer:
    record: RunRecord
    frame: pd.DataFrame | None = None
    chart: charts.ChartSpec | None = None


def answer_question(
    con: duckdb.DuckDBPyConnection,
    question: str,
    schema_text: str,
    known_tables: set[str],
) -> Answer:
    record = RunRecord(question=question, status="failed")
    repair_error: str | None = None
    total_attempts = 1 + settings.max_repair_attempts

    for attempt_number in range(1, total_attempts + 1):
        started = time.perf_counter()
        try:
            query_plan = planner.plan(question, schema_text, repair_error=repair_error)
        except planner.PlannerError as exc:
            record.plan_ms += int((time.perf_counter() - started) * 1000)
            record.status = "failed"
            record.message = str(exc)
            record.attempts.append(Attempt(attempt_number, None, "query_failed", str(exc)))
            return Answer(record=record)
        record.plan_ms += int((time.perf_counter() - started) * 1000)

        if not query_plan.answerable:
            record.status = "refused"
            record.message = query_plan.reason or "That can't be answered from the uploaded data."
            record.attempts.append(Attempt(attempt_number, None, "refused", record.message))
            return Answer(record=record)

        checked = guard.validate(query_plan.sql or "", known_tables, settings.max_rows_returned)
        if not checked.ok:
            repair_error = checked.error
            record.attempts.append(
                Attempt(attempt_number, query_plan.sql, "guard_rejected", checked.error)
            )
            continue

        try:
            result = executor.execute(con, checked.sql, settings.query_timeout_seconds)
        except executor.QueryTimeout as exc:
            record.attempts.append(Attempt(attempt_number, checked.sql, "timeout", str(exc)))
            record.status = "failed"
            record.message = str(exc)
            return Answer(record=record)
        except executor.QueryFailed as exc:
            repair_error = str(exc)
            record.attempts.append(Attempt(attempt_number, checked.sql, "query_failed", str(exc)))
            continue

        record.attempts.append(Attempt(attempt_number, checked.sql, "ok"))
        record.final_sql = checked.sql
        record.query_ms = result.elapsed_ms
        record.row_count = result.row_count

        if result.row_count == 0:
            record.status = "empty"
            record.message = "No rows matched that question."
            return Answer(record=record, frame=result.frame)

        record.status = "answered"
        chart = charts.choose(
            result.frame, hint=query_plan.chart, max_categories=settings.max_bar_categories
        )
        return Answer(record=record, frame=result.frame, chart=chart)

    record.status = "failed"
    record.message = (
        f"Could not build a valid query after {total_attempts} attempts. "
        "Try rephrasing, or check that the data contains what the question needs."
    )
    return Answer(record=record)
