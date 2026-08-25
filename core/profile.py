"""Describe the loaded tables well enough that the model can write correct SQL.

The model never sees rows - only column names, types, a handful of sample values,
and the join candidates found here.
"""

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    null_pct: float
    distinct: int
    samples: list[str]


@dataclass(frozen=True)
class TableProfile:
    name: str
    rows: int
    columns: list[ColumnProfile]


@dataclass(frozen=True)
class JoinCandidate:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    overlap: float


def names_look_related(left: str, right: str) -> bool:
    """Cheap name heuristic, run before the expensive overlap query."""
    a, b = left.lower(), right.lower()
    if a == b:
        return True
    a_stem = a[:-3] if a.endswith("_id") else a
    b_stem = b[:-3] if b.endswith("_id") else b
    if a_stem and a_stem == b_stem:
        return True
    return a.endswith(f"_{b}") or b.endswith(f"_{a}")


def _is_joinable_type(dtype: str) -> bool:
    d = dtype.upper()
    return any(token in d for token in ("INT", "VARCHAR", "TEXT", "STRING", "UUID"))


def profile_table(con: duckdb.DuckDBPyConnection, table: str, sample_size: int) -> TableProfile:
    rows = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    described = con.execute(f'DESCRIBE "{table}"').fetchall()

    columns: list[ColumnProfile] = []
    for row in described:
        column_name, column_type = row[0], row[1]
        nulls, distinct = con.execute(
            f'SELECT COUNT(*) FILTER (WHERE "{column_name}" IS NULL), '
            f'COUNT(DISTINCT "{column_name}") FROM "{table}"'
        ).fetchone()
        samples = con.execute(
            f'SELECT DISTINCT "{column_name}" FROM "{table}" '
            f'WHERE "{column_name}" IS NOT NULL LIMIT {sample_size}'
        ).fetchall()
        columns.append(
            ColumnProfile(
                name=column_name,
                dtype=column_type,
                null_pct=round((nulls / rows) * 100, 2) if rows else 0.0,
                distinct=distinct,
                samples=[str(s[0]) for s in samples],
            )
        )

    return TableProfile(name=table, rows=rows, columns=columns)


def find_join_candidates(
    con: duckdb.DuckDBPyConnection,
    profiles: list[TableProfile],
    min_overlap: float,
    limit: int,
) -> list[JoinCandidate]:
    """Find column pairs across tables whose values actually overlap.

    Name similarity alone produces false positives (every table has an `id`),
    so a name match only earns the column pair an overlap query.
    """
    candidates: list[JoinCandidate] = []

    for i, left in enumerate(profiles):
        for right in profiles[i + 1 :]:
            for lc in left.columns:
                if not _is_joinable_type(lc.dtype) or lc.distinct == 0:
                    continue
                for rc in right.columns:
                    if not _is_joinable_type(rc.dtype) or rc.distinct == 0:
                        continue
                    if not names_look_related(lc.name, rc.name):
                        continue

                    shared = con.execute(
                        f"SELECT COUNT(*) FROM ("
                        f'  SELECT DISTINCT "{lc.name}" AS v FROM "{left.name}" '
                        f'  WHERE "{lc.name}" IS NOT NULL'
                        f"  INTERSECT"
                        f'  SELECT DISTINCT "{rc.name}" AS v FROM "{right.name}" '
                        f'  WHERE "{rc.name}" IS NOT NULL'
                        f")"
                    ).fetchone()[0]

                    overlap = shared / min(lc.distinct, rc.distinct)
                    if overlap >= min_overlap:
                        candidates.append(
                            JoinCandidate(
                                left.name, lc.name, right.name, rc.name, round(overlap, 3)
                            )
                        )

    candidates.sort(key=lambda c: c.overlap, reverse=True)
    return candidates[:limit]


def schema_context(profiles: list[TableProfile], joins: list[JoinCandidate]) -> str:
    """The exact text handed to the model. Columns are shown quoted on purpose."""
    lines: list[str] = ["SCHEMA", ""]

    for profile in profiles:
        lines.append(f'TABLE "{profile.name}"  ({profile.rows} rows)')
        for column in profile.columns:
            sample_text = ", ".join(column.samples[:3])
            null_note = f", {column.null_pct}% null" if column.null_pct else ""
            lines.append(
                f'  "{column.name}"  {column.dtype}'
                f"  ({column.distinct} distinct{null_note})"
                f"  e.g. {sample_text}"
            )
        lines.append("")

    if joins:
        lines.append("JOIN CANDIDATES (verified by value overlap)")
        for join in joins:
            lines.append(
                f"  {join.left_table}.{join.left_column} = "
                f"{join.right_table}.{join.right_column}"
                f"  ({join.overlap:.0%} overlap)"
            )
        lines.append("")

    return "\n".join(lines)
