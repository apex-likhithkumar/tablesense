# Tablesense

Upload several CSV or Excel files, ask analytical questions in plain English, and get an
answer you can check — with the query that produced it shown underneath.

Built for the Darwinbox Forward Deployed Engineer take-home.

---

## The idea in one line

**The model is a translator, not an accountant.** It sees only your schema and writes SQL.
DuckDB does every calculation. No number in this app was produced by a language model.

---

## Quick start

```bash
git clone <repo-url> && cd tablesense

uv venv
uv pip install -e ".[dev]"

cp .env.example .env        # add your free Groq key from console.groq.com/keys

python data/make_samples.py # generates the four demo files
streamlit run app.py
```

Then upload everything in `data/samples/` and ask something like
*"Which product category earned the most revenue from repeat customers?"*

---

## Tech stack

| Tool | Job | Why this one |
|---|---|---|
| **Python 3.11** | Everything | One language end to end |
| **Streamlit** | Web UI | Upload, chat and charts built in — a working interface in ~50 lines rather than ~500 of frontend that earns nothing on the brief |
| **DuckDB** | Storage + compute | Runs in-process, nothing to host. Reads CSV and Excel directly, joins across files natively, does all the arithmetic |
| **gpt-oss-120b via Groq** | Writes the SQL | Open weights, Apache 2.0 - see the note below. Hosted, so no multi-GB download; sub-second planning uncontended |
| **sqlglot** | Validates the SQL | Parses to a syntax tree so a query can be *proven* read-only, rather than pattern-matched for scary words |
| **Pydantic v2** | Boundary contracts | The model's output is parsed into a typed object or rejected |
| **Plotly** | Charts | Native Streamlit integration with enough control to label axes properly |
| **pytest** | Tests | 38 unit tests on the three modules with real logic |

> **On the model name.** `openai/gpt-oss-120b` is an *open-weight* model released under
> Apache 2.0 - the weights are published, downloadable from Hugging Face, and it runs locally
> under Ollama. The `openai/` prefix is the publisher, not a hosted proprietary endpoint. It
> was chosen over `qwen/qwen3.6-27b` after benchmarking: Qwen is a reasoning model that spent
> most of each call on thinking tokens, costing ~25x the latency and ~7x the tokens for the
> same SQL. Translating a question into SQL does not benefit from a visible chain of thought.

The model provider is swappable in one line — `groq_base_url` and `model_name` in
`core/config.py`. Ollama, Together and Fireworks all speak the same OpenAI-compatible protocol.

---

## Delta on top of the LLM

The brief's fourth criterion is a single undefined sentence. This is my reading of it:
everything below is something a raw model call would not give you, and every item is visible
in the running app.

### 1. The model never computes

It emits SQL; DuckDB computes. Arithmetic hallucination is architecturally impossible rather
than prompt-discouraged. The model's entire output surface is six fields:

```python
class QueryPlan(BaseModel):
    answerable: bool
    reason:     str | None
    sql:        str | None
    chart:      Literal["bar", "line", "none"]
    x:          str | None
    y:          str | None
```

### 2. Every query is validated before it runs

`core/guard.py` parses the SQL with `sqlglot` and enforces: exactly one statement, root must be
`SELECT` or `UNION`, no `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER`, no `ATTACH`/`COPY`/`PRAGMA`,
every table reference must be one that was actually uploaded, and `LIMIT` is injected when absent.

Keyword matching is not a guard — `SELECT 'drop table'` would trip it and `/*x*/DELETE` would
slip past. Only a syntax tree tells you what a statement really is.

### 3. Join keys are detected, not guessed

`core/profile.py` finds column pairs across files whose names look related, then **verifies the
relationship with an actual value-overlap query** before offering it to the model. Name matching
alone produces false joins — every table has an `id` — and a wrong join is a wrong number that
looks right.

On the sample data it finds all three real relationships at 100% overlap and no false ones.

### 4. Chart choice is deterministic

The model suggests a chart; `core/charts.py` decides from the **actual result dtypes**. A single
number never gets a chart no matter what the model asks for. A real date column produces a line,
a category with a measure produces a bar, and more than 25 categories produces nothing.

The model's output is an input to a decision, not the decision.

### 5. It refuses

Three exits, none of which invent a number:
- the model marks the question unanswerable and names the column it would have needed
- the guard rejects the SQL twice after repair attempts
- the query returns zero rows — reported as *"No rows matched"*, explicitly not *"the total is 0"*

### 6. Everything is logged, and correctness is measured

Every question records the SQL, each attempt and why it failed, validation outcome, planning
and query latency, and rows returned — visible under **Run details** in the UI. Any answer can
be reproduced without shell access.

And the golden eval set below turns correctness into a number rather than a feeling.

---

## How correctness is measured

`evals/golden.yaml` holds 43 questions written **before** the implementation. Expected answers
come from **hand-written oracle SQL**, never from the app — so a wrong model query cannot
quietly become the expected answer.

```bash
python evals/run_evals.py
```

Coverage mirrors the brief's own list — totals, averages, filters, comparisons, trends — plus
cross-file joins and six deliberately unanswerable questions, because refusal is a behaviour
that needs testing like any other.

### Results

Last full run: **43 of 43 passed (100%)**, every one on the first attempt - no repair
loop needed.

| | |
|---|---|
| Questions | 43 (37 computed, 6 deliberately unanswerable) |
| Passed | 43 (100%) |
| Needed a repair attempt | 0 |
| Median latency | 3.1 s |
| Fastest / slowest | 0.7 s / 11.4 s |

The slower tail is Groq free-tier throttling, not model time - the planner backs off and
retries on 429s. Uncontended, a question answers in well under a second.

**On a 100% pass rate.** A suite that cannot fail is worthless, so it was verified by
deliberately corrupting two oracles - flipping a filter and reversing a sort order. Both
were caught. The suite fails when it should.

**Known flake, roughly 1 run in 50:** the model occasionally refuses a question it can
answer, claiming a value is absent when it is present. Hosted inference is not perfectly
deterministic even at `temperature=0`. It is a false refusal rather than a wrong number,
which is the failure mode I would choose if forced to pick one.

**Two earlier rounds of failures came from the harness, not the app** - it compared rows
positionally when both orderings were valid, and compared the last column when the app
legitimately returned an extra one. The fix was to the test, not the product. That is the
single most useful thing the eval set did: without it, the temptation would have been to
"fix" a correct prompt to satisfy a broken oracle.

Unit tests, separately:

```bash
python -m pytest -q      # 38 tests: guard, profiling, chart selection, ingest
```

---

## Assumptions

The brief is deliberately vague and says outright that scoping is what's being assessed. So
these are written down rather than asked about:

| Assumption | Why |
|---|---|
| Files have a header row | Universal for exported spreadsheets; a headerless file is a different product |
| Related files share key columns, though names may differ | Verified by value overlap rather than trusted |
| ISO dates only (`2026-05-17`) | `03/04/2026` is genuinely ambiguous — guessing day-first vs month-first silently corrupts every date filter |
| One analyst per session, no auth | Single-session tool; multi-user needs row-level permissions, which is a different design |
| The uploader may see all uploaded data | No column-level access control |
| English-language questions | The model handles others, but nothing is tested |
| Data fits comfortably in memory | DuckDB is in-process; ~50MB per file is the practical ceiling |
| First sheet only for Excel workbooks | Multi-sheet selection is UI work with no rubric value |

## Deliberately out of scope

Authentication · persistence between sessions · concurrent users · saved dashboards · editing
the data · **RAG**.

On that last one: the data is structured, so a query engine is the right tool, not retrieval.
Aggregation needs every row while retrieval returns top-k; embeddings discard magnitude and
ordering, so `WHERE amount > 5000` has no similarity-search equivalent; and joins do not survive
retrieval at all. RAG would earn its place here for a data dictionary — unstructured text the
model needs to *read* — or as **schema RAG** beyond roughly 50 tables, where schemas stop fitting
in the prompt. At four files it is cost with no benefit.

---

## What I'd build next

1. **Live connectors instead of uploads** — REST and webhook ingestion from the systems the data
   actually lives in, rather than a file the user exported by hand.
2. **Schema RAG** so the app survives past ~50 tables, where schemas no longer fit in context.
3. **Row-level permissions enforced in the database**, not the application — so a bug in the app
   cannot leak one user's rows into another's answer.
4. **Plan caching** keyed on question + schema hash. Repeat questions currently pay full latency.
5. **A second engine for text-shaped questions**, explicitly routed and visibly labelled, so
   questions SQL cannot express stop being refusals.

---

## Optional tracing

The built-in run log is the default so the app has **no external dependencies at runtime**.
Langfuse tracing sits behind `LANGFUSE_*` environment variables for deployments that want it.

That is a deliberate choice, not an omission: the trace here is two nodes deep, and adding a
third-party service on the critical path of a customer deployment costs more than the dashboard
is worth.

---

## Project layout

```
app.py                  Streamlit UI. Rendering and session state only.
core/
  config.py             typed settings — keys, caps, timeouts
  ingest.py             uploaded files -> DuckDB tables, ISO date coercion
  profile.py            column profiling + value-verified join detection
  planner.py            the only LLM call: question + schema -> QueryPlan
  guard.py              SQL validation, read-only enforcement
  executor.py           runs SQL with a wall-clock timeout
  charts.py             chart choice from real result dtypes
  runlog.py             per-question record
  answer.py             orchestration + bounded repair loop
data/make_samples.py    deterministic sample data (fixed seed)
evals/golden.yaml       42 questions with hand-written oracle SQL
evals/run_evals.py      scores them, prints a pass rate
tests/                  38 unit tests
```
