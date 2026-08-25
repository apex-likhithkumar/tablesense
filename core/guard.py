"""Prove a query is a read before it runs.

Pattern-matching for scary words is not a guard - `SELECT 'drop table'` would
trip it and `/*x*/DELETE` would slip past. This parses to a syntax tree and
checks structure instead.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Root must be one of these. Everything else is rejected outright.
ALLOWED_ROOTS = (exp.Select, exp.Union)

# Belt and braces: even nested, these never appear in a read.
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,  # catches ATTACH, PRAGMA, SET, COPY and anything unparsed
)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None = None
    error: str | None = None


def validate(sql: str, known_tables: set[str], row_cap: int) -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, error="The model returned an empty query.")

    try:
        statements = [
            s
            for s in sqlglot.parse(sql, read="duckdb", error_level=sqlglot.ErrorLevel.RAISE)
            if s is not None
        ]
    except Exception as exc:  # noqa: BLE001 - message is fed back to the model for repair
        return GuardResult(False, error=f"Could not parse the SQL: {exc}")

    if len(statements) != 1:
        return GuardResult(
            False,
            error=f"Expected exactly one statement, got {len(statements)}.",
        )

    tree = statements[0]

    if not isinstance(tree, ALLOWED_ROOTS):
        return GuardResult(
            False,
            error=f"Only SELECT queries are allowed. Got {type(tree).__name__.upper()}.",
        )

    for node_type in FORBIDDEN_NODES:
        if next(tree.find_all(node_type), None) is not None:
            return GuardResult(
                False,
                error=f"Only SELECT queries are allowed. Found {node_type.__name__.upper()}.",
            )

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    known = {t.lower() for t in known_tables}

    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in known and name not in cte_names:
            available = ", ".join(sorted(known_tables))
            return GuardResult(
                False,
                error=f"Unknown table '{table.name}'. Available tables: {available}.",
            )

    if tree.args.get("limit") is None:
        tree = tree.limit(row_cap)

    return GuardResult(True, sql=tree.sql(dialect="duckdb"))
