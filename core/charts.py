"""Decide whether a result deserves a chart, and which one.

The model supplies a hint, but the decision is made here against the real
column dtypes. A model that wants a chart of a single number does not get one.
"""

from dataclasses import dataclass

import pandas as pd
from pandas.api import types as ptypes


@dataclass(frozen=True)
class ChartSpec:
    kind: str  # "bar" | "line"
    x: str
    y: str


def choose(frame: pd.DataFrame, hint: str, max_categories: int) -> ChartSpec | None:
    if frame is None or frame.empty:
        return None

    # A single number is an answer, not a chart.
    if frame.shape == (1, 1):
        return None

    if len(frame.columns) > 3:
        return None

    numeric = [c for c in frame.columns if ptypes.is_numeric_dtype(frame[c])]
    temporal = [c for c in frame.columns if ptypes.is_datetime64_any_dtype(frame[c])]
    categorical = [c for c in frame.columns if c not in numeric and c not in temporal]

    if not numeric:
        return None

    measure = numeric[-1]

    # A real date column wins over a categorical one: time is the better axis.
    if temporal:
        return ChartSpec(kind="line", x=temporal[0], y=measure)

    if categorical and len(frame) <= max_categories:
        kind = "line" if hint == "line" else "bar"
        return ChartSpec(kind=kind, x=categorical[0], y=measure)

    return None
