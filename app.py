"""Tablesense - ask analytical questions of your spreadsheets.

This file renders and holds session state. All logic lives in core/.
"""

import html
import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Tablesense", page_icon="\U0001F9EE", layout="wide")

# Streamlit Cloud injects secrets rather than a .env file.
try:
    if "GROQ_API_KEY" in st.secrets:
        os.environ.setdefault("GROQ_API_KEY", st.secrets["GROQ_API_KEY"])
except Exception:  # noqa: BLE001 - no secrets file locally, which is fine
    pass

from core.answer import answer_question  # noqa: E402 - must follow the secrets shim
from core.config import settings  # noqa: E402
from core.ingest import load_files  # noqa: E402
from core.profile import find_join_candidates, profile_table, schema_context  # noqa: E402

EXAMPLES = [
    "What is the total revenue across all orders?",
    "Which product category earned the most revenue from repeat customers?",
    "Show total revenue by month.",
    "How many customers are in each city?",
]

# Ledger-terminal palette: gold is reserved for figures, everything else stays
# quiet. Charts are themed to match so they do not look bolted on.
CHART_INK = "#93A0BC"
CHART_GRID = "#222D4A"
CHART_SERIES = ["#E5B567", "#5FBF9B", "#7FA6E8", "#E0785C", "#B58BD6"]


def load_stylesheet() -> None:
    css = Path(__file__).parent / "assets" / "style.css"
    if css.exists():
        st.markdown(f"<style>{css.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


load_stylesheet()


def get_connection() -> duckdb.DuckDBPyConnection:
    if "con" not in st.session_state:
        st.session_state.con = duckdb.connect(":memory:")
    return st.session_state.con


def ingest(uploaded) -> None:
    con = get_connection()
    loaded, failed = load_files(con, uploaded)

    for failure in failed:
        st.sidebar.error(f"{failure.source_filename}: {failure.error}")
    if not loaded:
        return

    profiles = [profile_table(con, t.name, settings.sample_values_per_column) for t in loaded]
    joins = find_join_candidates(
        con, profiles, settings.min_join_overlap, settings.max_join_candidates
    )

    st.session_state.tables = loaded
    st.session_state.profiles = profiles
    st.session_state.joins = joins
    st.session_state.schema_text = schema_context(profiles, joins)
    st.session_state.history = []


def format_scalar(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    return str(value)


def render_result(frame: pd.DataFrame) -> None:
    """A single number is an answer, not a table. Anything else is a table."""
    if frame is None or frame.empty:
        return

    if frame.shape == (1, 1):
        label = str(frame.columns[0]).replace("_", " ").strip().title()
        st.metric(label, format_scalar(frame.iloc[0, 0]))
        return

    st.dataframe(frame, hide_index=True, use_container_width=len(frame.columns) > 2)


def render_chart(frame, spec) -> None:
    common = dict(x=spec.x, y=spec.y, color_discrete_sequence=CHART_SERIES)
    figure = (
        px.bar(frame, **common)
        if spec.kind == "bar"
        else px.line(frame, markers=True, **common)
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Public Sans, sans-serif", color=CHART_INK, size=12),
        margin=dict(l=0, r=0, t=14, b=0),
        height=330,
        hoverlabel=dict(
            bgcolor="#131A2E", bordercolor="#222D4A", font_family="JetBrains Mono, monospace"
        ),
    )
    axis = dict(gridcolor=CHART_GRID, zeroline=False, linecolor=CHART_GRID, title=None)
    figure.update_xaxes(**axis)
    figure.update_yaxes(**axis)
    if spec.kind == "line":
        figure.update_traces(line=dict(width=2), marker=dict(size=5))
    else:
        figure.update_traces(marker_line_width=0)
    st.plotly_chart(figure, use_container_width=True)


def render_run_details(record) -> None:
    label = (
        f"Run details - {record.status}, {record.total_ms} ms, "
        f"{len(record.attempts)} attempt(s)"
    )
    with st.expander(label):
        rows = record.row_count if record.row_count is not None else "-"
        st.caption(
            f"planning {record.plan_ms} ms | query {record.query_ms} ms | "
            f"rows returned {rows} | model {settings.model_name}"
        )
        for attempt in record.attempts:
            st.markdown(f"**Attempt {attempt.number} - {attempt.outcome}**")
            if attempt.sql:
                st.code(attempt.sql, language="sql")
            if attempt.error:
                st.caption(attempt.error)


def render_exchange(entry, number: int, total: int) -> None:
    record = entry["record"]
    live = " &middot; <span class='live'>latest</span>" if number == total else ""

    st.markdown(
        f"<p class='ts-index'>Q{number:02d}{live}</p>"
        f"<p class='ts-question'>{html.escape(entry['question'])}</p>",
        unsafe_allow_html=True,
    )

    if record.status == "refused":
        st.warning(entry["headline"])
    elif record.status == "failed":
        st.error(entry["headline"])
    elif record.status == "empty":
        st.info(entry["headline"])
    else:
        st.markdown(
            f"<p class='ts-meta'><b>{record.row_count:,}</b> row(s) &middot; "
            f"<b>{record.total_ms:,}</b> ms &middot; "
            f"{len(record.attempts)} attempt(s)</p>",
            unsafe_allow_html=True,
        )

    render_result(entry["frame"])

    if entry["chart"] is not None:
        render_chart(entry["frame"], entry["chart"])

    if record.final_sql:
        with st.expander("SQL that produced this"):
            st.code(record.final_sql, language="sql")

    render_run_details(record)
    st.divider()


def ask(question: str) -> None:
    answer = answer_question(
        get_connection(),
        question,
        st.session_state.schema_text,
        {t.name for t in st.session_state.tables},
    )
    record = answer.record

    if record.status == "answered":
        headline = f"{record.row_count:,} row(s) in {record.total_ms:,} ms"
    elif record.status == "empty":
        headline = record.message
    elif record.status == "refused":
        headline = f"Can't answer that from this data. {record.message}"
    else:
        headline = record.message or "Something went wrong."

    st.session_state.history.append(
        {
            "question": question,
            "headline": headline,
            "frame": answer.frame,
            "chart": answer.chart,
            "record": record,
        }
    )


# ---------------------------------------------------------------- sidebar

st.sidebar.title("Tablesense")
st.sidebar.caption("Upload spreadsheets, ask questions in plain English.")

uploaded = st.sidebar.file_uploader(
    "CSV or Excel files",
    type=["csv", "tsv", "txt", "xlsx", "xls"],
    accept_multiple_files=True,
)

if uploaded and st.sidebar.button("Load files", type="primary", use_container_width=True):
    with st.spinner("Reading and profiling..."):
        ingest(uploaded)

if st.session_state.get("tables"):
    st.sidebar.divider()
    st.sidebar.markdown("**Loaded tables**")
    for table in st.session_state.tables:
        st.sidebar.caption(f"`{table.name}` - {table.rows:,} rows | {table.source_filename}")

    if st.session_state.get("history"):
        st.sidebar.divider()
        if st.sidebar.button("Clear questions", use_container_width=True):
            st.session_state.history = []
            st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(f"Model: `{settings.model_name}`")

# ---------------------------------------------------------------- main

MASTHEAD = """
<div class="ts-mast">
  <div>
    <p class="ts-word">Table<em>sense</em></p>
    <p class="ts-thesis">The model writes the query &middot; the database does the arithmetic</p>
  </div>
  <span class="ts-badge">{badge}</span>
</div>
"""

if not st.session_state.get("tables"):
    st.markdown(MASTHEAD.format(badge="awaiting data"), unsafe_allow_html=True)
    st.title("Ask your spreadsheets a question")
    st.markdown(
        "Upload two or more related files in the sidebar, then ask in plain English.\n\n"
        "Questions are answered by running SQL against your data. "
        "**The model writes the query; the database does the arithmetic** - "
        "so every number comes from your files, not from a language model."
    )
    st.info("Sample files to try are in `data/samples/` in the repo.")
    st.stop()

_tables = st.session_state.get("tables", [])
_rows = sum(t.rows for t in _tables)
st.markdown(
    MASTHEAD.format(badge=f"{len(_tables)} tables &middot; {_rows:,} rows"),
    unsafe_allow_html=True,
)

with st.expander("What was loaded", expanded=not st.session_state.get("history")):
    for profile in st.session_state.profiles:
        st.markdown(f"**`{profile.name}`** - {profile.rows:,} rows, {len(profile.columns)} columns")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "column": c.name,
                        "type": c.dtype,
                        "distinct": c.distinct,
                        "null %": c.null_pct,
                        "examples": ", ".join(c.samples[:3]),
                    }
                    for c in profile.columns
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    if st.session_state.joins:
        st.markdown("**Detected relationships** - found automatically, verified by value overlap")
        for join in st.session_state.joins:
            st.caption(
                f"`{join.left_table}.{join.left_column}` = "
                f"`{join.right_table}.{join.right_column}` - {join.overlap:.0%} overlap"
            )

# One place decides what to ask, so there is a single rerun path.
pending: str | None = None

if not st.session_state.get("history"):
    st.markdown("<p class='ts-eyebrow'>Try one of these</p>", unsafe_allow_html=True)
    for row_start in (0, 2):
        left, right = st.columns(2)
        for column, example in zip((left, right), EXAMPLES[row_start : row_start + 2]):
            if column.button(example, use_container_width=True):
                pending = example

typed = st.chat_input("Ask a question about your data")
if typed:
    pending = typed

if pending:
    with st.status(f"{pending}", expanded=True) as status:
        st.write("Writing the query...")
        ask(pending)
        status.update(label="Done", state="complete", expanded=False)
    st.rerun()

# Newest first: the answer you just asked for is at the top of the page, so the
# docked input never hides it and there is nothing to scroll to.
history = st.session_state.get("history", [])
if history:
    st.divider()
    total = len(history)
    for offset, entry in enumerate(reversed(history)):
        render_exchange(entry, number=total - offset, total=total)
