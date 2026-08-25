"""Turn uploaded files into DuckDB tables.

Column names are preserved exactly as they appear in the file. The schema text
shows them quoted, so the model copies the quoting rather than guessing at it.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
from pandas.api import types as ptypes

CSV_SUFFIXES = {".csv", ".txt", ".tsv"}
EXCEL_SUFFIXES = {".xlsx", ".xls"}


@dataclass(frozen=True)
class LoadedTable:
    name: str
    source_filename: str
    rows: int


@dataclass(frozen=True)
class LoadFailure:
    source_filename: str
    error: str


# Only ISO-style dates are coerced. Ambiguous formats like 03/04/2026 are left as
# text on purpose - guessing day-first vs month-first silently corrupts every
# date filter, and a wrong date is worse than an unparsed one.
ISO_DATE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def coerce_date_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn ISO date strings into real dates.

    pandas reads CSV dates as text, which leaves DATE_TRUNC and every date
    comparison broken downstream.
    """
    for column in frame.columns:
        series = frame[column]
        # pandas 3 gives text columns a `str` dtype rather than `object`, so test
        # for what a column is not, rather than for one specific text dtype.
        if (
            ptypes.is_numeric_dtype(series)
            or ptypes.is_datetime64_any_dtype(series)
            or ptypes.is_bool_dtype(series)
        ):
            continue

        present = series.dropna()
        if present.empty:
            continue

        sample = present.astype(str).head(200)
        if not sample.str.match(ISO_DATE).all():
            continue

        converted = pd.to_datetime(frame[column], errors="coerce")
        if converted.notna().sum() >= len(present) * 0.95:
            frame[column] = converted

    return frame


def table_name_from(filename: str) -> str:
    """`Sales Data 2026.csv` -> `sales_data_2026`. Always a safe SQL identifier."""
    stem = Path(filename).stem.lower()
    name = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    if not name:
        name = "table"
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def load_files(con: duckdb.DuckDBPyConnection, files) -> tuple[list[LoadedTable], list[LoadFailure]]:
    """Load each file as its own table.

    One unreadable file must not kill the session, so failures are collected
    and returned rather than raised.
    """
    loaded: list[LoadedTable] = []
    failed: list[LoadFailure] = []
    used: set[str] = set()

    for file in files:
        try:
            suffix = Path(file.name).suffix.lower()
            if suffix in CSV_SUFFIXES:
                sep = "\t" if suffix == ".tsv" else ","
                frame = pd.read_csv(file, sep=sep)
            elif suffix in EXCEL_SUFFIXES:
                frame = pd.read_excel(file)
            else:
                failed.append(LoadFailure(file.name, f"Unsupported file type '{suffix}'."))
                continue

            frame = coerce_date_columns(frame)

            if frame.empty:
                failed.append(LoadFailure(file.name, "File has no rows."))
                continue

            base = table_name_from(file.name)
            name = base
            counter = 2
            while name in used:
                name = f"{base}_{counter}"
                counter += 1
            used.add(name)

            con.register("_staging", frame)
            con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _staging')
            con.unregister("_staging")

            loaded.append(LoadedTable(name=name, source_filename=file.name, rows=len(frame)))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            failed.append(LoadFailure(file.name, str(exc)))

    return loaded, failed
