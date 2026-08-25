"""Question + schema -> a single SELECT, as structured JSON.

The model is a translator, not an accountant: it is never asked for a number,
only for the query that produces one.
"""

import json
import random
import time
from typing import Literal

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError, field_validator

from core.config import settings


class QueryPlan(BaseModel):
    answerable: bool
    reason: str | None = None
    sql: str | None = None
    chart: Literal["bar", "line", "none"] = "none"
    x: str | None = None
    y: str | None = None

    @field_validator("chart", mode="before")
    @classmethod
    def _null_chart_means_none(cls, value):
        """Some models send `null` rather than omitting the field."""
        return "none" if value is None else value


class PlannerError(RuntimeError):
    """The model could not be reached, or returned something unusable."""


# Transient by nature: a hosted model under load returns these, and the right
# response is to wait, not to fail the user's question.
RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)
MAX_TRIES = 4
BASE_BACKOFF_SECONDS = 2.0


def _is_transient(exc: Exception) -> bool:
    """Throttling and server faults are worth waiting out; bad requests are not.

    Hosted providers do not always map 429 to RateLimitError, so the status code
    is checked directly rather than trusting the exception class alone.
    """
    if isinstance(exc, RETRYABLE):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


SYSTEM_PROMPT = """You translate questions about tabular data into a single DuckDB SQL SELECT statement.

RULES
- Reply with JSON only. No prose, no markdown fences.
- Never compute, estimate or state a number yourself. Your only output is SQL.
- Use only the tables and columns in the SCHEMA section. Never invent a column.
- Write exactly one SELECT statement. Never INSERT, UPDATE, DELETE, CREATE, DROP or ALTER.
- When a question needs more than one table, JOIN them using the JOIN CANDIDATES listed.
- Quote every identifier with double quotes, exactly as it is written in the schema.
- Give computed columns a readable alias, e.g. SUM(x) AS total_revenue.
- Date columns are real TIMESTAMPs, so DATE_TRUNC, EXTRACT and date comparisons all work.
- If the schema cannot answer the question, set answerable to false and say in
  `reason` which column or table would have been needed. Do not guess.
- Chart: "bar" when comparing a measure across categories, "line" for a measure
  over time, "none" for a single value or a wide table. Set x and y to the
  result column names that drive it.

REPLY WITH EXACTLY THIS JSON SHAPE
{"answerable": true, "reason": null, "sql": "SELECT ...", "chart": "bar", "x": "region", "y": "revenue"}
"""


def _client() -> OpenAI:
    if not settings.groq_api_key:
        raise PlannerError(
            "No GROQ_API_KEY configured. Copy .env.example to .env and add your key."
        )
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        timeout=settings.llm_timeout_seconds,
    )


def build_user_message(question: str, schema_text: str, repair_error: str | None) -> str:
    parts = [schema_text, f"QUESTION\n{question}"]
    if repair_error:
        parts.append(
            "YOUR PREVIOUS QUERY FAILED\n"
            f"{repair_error}\n"
            "Fix it. Return the corrected JSON."
        )
    return "\n\n".join(parts)


def plan(question: str, schema_text: str, repair_error: str | None = None) -> QueryPlan:
    client = _client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(question, schema_text, repair_error)},
    ]

    last_error: Exception | None = None
    response = None

    for attempt in range(MAX_TRIES):
        try:
            response = client.chat.completions.create(
                model=settings.model_name,
                temperature=settings.llm_temperature,
                response_format={"type": "json_object"},
                messages=messages,
            )
            break
        except Exception as exc:  # noqa: BLE001 - re-raised below unless transient
            if not _is_transient(exc):
                raise PlannerError(f"Could not reach the model: {exc}") from exc
            last_error = exc
            if attempt == MAX_TRIES - 1:
                break
            # Exponential backoff with jitter, so a burst of questions does not
            # retry in lockstep and re-trigger the same rate limit.
            delay = BASE_BACKOFF_SECONDS * (2**attempt) + random.uniform(0, 1)
            time.sleep(delay)

    if response is None:
        raise PlannerError(
            f"Could not reach the model after {MAX_TRIES} attempts: {last_error}"
        ) from last_error

    raw = response.choices[0].message.content or ""

    try:
        return QueryPlan.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PlannerError(f"Model returned unusable JSON: {exc}") from exc
