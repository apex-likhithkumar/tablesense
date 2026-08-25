"""What happened on one question. Makes any answer reproducible without shell access."""

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["answered", "empty", "refused", "failed"]


@dataclass(frozen=True)
class Attempt:
    number: int
    sql: str | None
    outcome: str  # "ok" | "guard_rejected" | "query_failed" | "timeout" | "refused"
    error: str | None = None


@dataclass
class RunRecord:
    question: str
    status: Status
    attempts: list[Attempt] = field(default_factory=list)
    final_sql: str | None = None
    row_count: int | None = None
    plan_ms: int = 0
    query_ms: int = 0
    message: str | None = None

    @property
    def total_ms(self) -> int:
        return self.plan_ms + self.query_ms
