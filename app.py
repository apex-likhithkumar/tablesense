"""Tablesense - ask analytical questions of your spreadsheets.

This file renders and holds session state. All logic lives in core/.
"""

import os

import duckdb
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Tablesense", page_icon="calculator", layout="wide")

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
    "Which city generated the most revenue?",
]


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


def render_chart(frame, spec) -> None:
    figure = (
        px.bar(frame, x=spec.x, y=spec.y)
        if spec.kind == "bar"
        else px.line(frame, x=spec.x, y=spec.y, markers=True)
    )
    figure.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340)
    st.plotly_chart(figure, use_container_width=True)


def render_run_details(record) -> None:
    label = (
        f"Run details - {record.status}, {record.total_ms} ms, "
        f"{len(record.attempts)} attempt(s)"
    )
    with st.expander(label):
        rows = record.row_count if record.row_count is not None else "-"
        st.caption(
            f"planning {record.plan_ms} ms | query {record.query_ms} ms | rows returned {rows}"
        )
        for attempt in record.attempts:
            st.markdown(f"**Attempt {attempt.number} - {attempt.outcome}**")
            if attempt.sql:
                st.code(attempt.sql, language="sql")
            if attempt.error:
                st.caption(attempt.error)


def render_exchange(entry) -> None:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        st.write(entry["headline"])
        if entry["frame"] is not None and not entry["frame"].empty:
            st.dataframe(entry["frame"], use_container_width=True, hide_index=True)
        if entry["chart"] is not None:
            render_chart(entry["frame"], entry["chart"])
        if entry["record"].final_sql:
            with st.expander("SQL that produced this"):
                st.code(entry["record"].final_sql, language="sql")
        render_run_details(entry["record"])


def ask(question: str) -> None:
    answer = answer_question(
        get_connection(),
        question,
        st.session_state.schema_text,
        {t.name for t in st.session_state.tables},
    )
    record = answer.record

    if record.status == "answered":
        headline = f"{record.row_count:,} row(s) in {record.total_ms} ms"
    elif record.status == "empty":
        headline = record.message
    elif record.status == "refused":
        headline = f"I can't answer that from this data. {record.message}"
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
    st.sidebar.divider()
    st.sidebar.caption(f"Model: `{settings.model_name}`")

# ---------------------------------------------------------------- main

if not st.session_state.get("tables"):
    st.title("Ask your spreadsheets a question")
    st.markdown(
        "Upload two or more related files in the sidebar, then ask in plain English.\n\n"
        "Questions are answered by running SQL against your data. "
        "**The model writes the query; the database does the arithmetic** - "
        "so every number comes from your files, not from a language model."
    )
    st.info("Sample files to try are in `data/samples/` in the repo.", icon="i")
    st.stop()

with st.expander("What was loaded", expanded=not st.session_state.get("history")):
    for profile in st.session_state.profiles:
        st.markdown(f"**`{profile.name}`** - {profile.rows:,} rows, {len(profile.columns)} columns")
        st.dataframe(
            [
                {
                    "column": c.name,
                    "type": c.dtype,
                    "distinct": c.distinct,
                    "null %": c.null_pct,
                    "examples": ", ".join(c.samples[:3]),
                }
                for c in profile.columns
            ],
            use_container_width=True,
            hide_index=True,
        )

    if st.session_state.joins:
        st.markdown("**Detected relationships**")
        for join in st.session_state.joins:
            st.caption(
                f"`{join.left_table}.{join.left_column}` = "
                f"`{join.right_table}.{join.right_column}` - {join.overlap:.0%} value overlap"
            )

if not st.session_state.get("history"):
    st.markdown("**Try one of these**")
    columns = st.columns(len(EXAMPLES))
    for column, example in zip(columns, EXAMPLES):
        if column.button(example, use_container_width=True):
            with st.spinner("Writing the query..."):
                ask(example)
            st.rerun()

st.divider()

for entry in st.session_state.get("history", []):
    render_exchange(entry)

question = st.chat_input("Ask a question about your data")

if question:
    with st.spinner("Writing the query..."):
        ask(question)
    st.rerun()
