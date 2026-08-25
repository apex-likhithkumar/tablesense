# Defense notes

Not shipped with the submission. This is preparation for the panel conversation —
every decision, why it was made, and what I would change with more time.

---

## 1. Why the model writes SQL instead of reading the data

**Chose:** the LLM sees only the schema and emits a `SELECT`. DuckDB computes every number.

**Why:** asking a language model to add up 50,000 rows produces a plausible number with
no way to tell when it is wrong. Moving arithmetic to the database makes that entire class
of failure impossible by construction rather than discouraged by prompting. It also makes
every answer auditable — the query is shown next to the result and can be re-run by hand.

**Cost:** questions that are genuinely not expressible in SQL (fuzzy matching, free-text
sentiment) cannot be answered. I consider that the right trade: refusing is better than
guessing.

**With three more days:** add a second, non-SQL path for text-shaped questions, routed
explicitly and labelled differently in the UI so the user knows which engine answered.

---

## 2. Why DuckDB rather than pandas

**Chose:** load each file as a DuckDB table, generate SQL.

**Why three reasons, in order of weight:**
1. **Cross-file joins are native.** The brief's second criterion is analysis *across* files.
   In SQL that is a `JOIN`. With pandas the model has to reason about merge keys, `how=`,
   and suffix collisions — and when it gets that wrong the result is a silently wrong number,
   not an error.
2. **SQL is validatable.** I can parse it, prove the root node is a `SELECT`, and reject
   anything else. Generated Python can only be sandboxed and hoped about.
3. **DuckDB reads CSV and Excel directly** and does type inference, so ingestion is nearly free.

**Cost:** regression and correlation are clumsier in SQL than in pandas. DuckDB has
`regr_slope` and `corr`, so it is covered, just less elegantly.

---

## 3. Why no RAG

The data is structured. RAG solves a different problem: finding relevant passages in
unstructured text that will not fit in context.

Four specific reasons it is the wrong tool here:
- **Aggregation needs every row; retrieval returns top-k.** "Total revenue" over 20 retrieved
  chunks of 50,000 rows is confidently wrong.
- **Embeddings discard magnitude and order.** `WHERE amount > 5000` and `ORDER BY date` have
  no similarity-search equivalent.
- **Joins do not survive retrieval.** A join is a set operation over keys.
- **It is not verifiable.** SQL is deterministic and re-runnable; "the model read these chunks"
  is not an audit trail.

**Where I would use it:** a data dictionary (PDFs defining what `net_rev_adj` means) is
unstructured text the model needs to *read* — that is RAG, correctly. And beyond roughly
50 tables, schemas stop fitting in the prompt and you retrieve the relevant *schemas* first.
That is schema RAG and it is a real technique. At 4 files it is cost with no benefit.

**Recognition rule:** RAG is for finding, code is for computing.

---

## 4. Model choice

**Chose:** `openai/gpt-oss-120b` on Groq. Open weights, Apache 2.0.

**I got this wrong first, and the correction is the interesting part.** My initial benchmark
of three questions showed gpt-oss at ~17s versus Qwen at ~3s, so I picked Qwen. That
measurement caught gpt-oss on a cold start, and I generalised from three samples.

Running the full 43-question set exhausted Groq's 200,000 tokens-per-day cap on Qwen. The
error message is what exposed the real cause: **Qwen3.6 is a reasoning model**, spending
~4,500 tokens per call on thinking blocks to produce ~150 tokens of SQL. Re-benchmarking
properly:

| Model | Latency | Tokens per call |
|---|---|---|
| qwen/qwen3.6-27b | 15-20s | ~4,500 |
| openai/gpt-oss-20b | 558ms | 621 |
| openai/gpt-oss-120b | 644ms | 632 |

~25x faster, ~7x cheaper, same SQL. Translating a question into SQL does not benefit from a
visible chain of thought - it is a mechanical transformation, not a reasoning problem.

**On the name:** `openai/` is the publisher, not a hosted proprietary model. gpt-oss weights
are published under Apache 2.0 and run locally under Ollama. If the panel raises it, that is
the answer, and the README states it up front rather than hoping nobody looks.

**The lesson worth stating:** a three-sample benchmark is an anecdote. The number that
mattered was tokens per call, and I did not look at it until a rate limit forced me to.

**Provider is swappable in one line.** `groq_base_url` and `model_name` are config. Ollama,
Together and Fireworks all speak the same OpenAI-compatible protocol.

**With three more days:** run the full golden set against three models and pick on measured
accuracy rather than three hand-picked questions.

---

## 5. The guard

**Chose:** parse with `sqlglot`, require the root to be `SELECT` or `UNION`, reject
`INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/Command`, verify every table reference against the
known set, and inject `LIMIT` when absent.

**Why parsing rather than keyword matching:** string matching is not a guard.
`SELECT 'drop table'` trips it and `/*x*/DELETE` slips past it. Only a syntax tree tells you
what a statement actually *is*.

**CTE handling** was a real bug I had to fix: a `WITH recent AS (...)` name appears as a table
reference and would be rejected as unknown. CTE aliases are collected and allowed.

**What it does not do:** column-level permissions. Anyone who can upload can query everything
in what they uploaded. In a multi-tenant deployment this is where row-level security belongs —
in my day job that means Postgres RLS with the tenant id set on the same connection as the query.

---

## 6. Join detection

**Chose:** name similarity as a cheap filter, then verify with an actual value-overlap query.
Keep pairs above 50% overlap.

**Why not names alone:** every table has an `id`. Name matching alone produces false joins,
and a wrong join is a wrong number that looks right.

**Why not overlap alone:** it is O(n²) across every column pair. The name check makes it cheap.

**On the sample data it finds all three real relationships at 100% overlap** and no false ones.

**Ambiguity:** if two columns both plausibly join, both are passed to the model as candidates
and it picks. With more time I would surface the ambiguity to the user rather than let the
model choose silently.

---

## 7. Dates — the bug worth talking about

Pandas reads CSV dates as text, so `order_date` arrived as `VARCHAR`. Every `DATE_TRUNC`,
every date filter, and the entire line-chart path would have failed. The unit tests passed;
the behaviour was broken.

**The fix:** coerce ISO-style date strings on ingest.

**The deliberate limitation:** I do *not* parse `03/04/2026`. Day-first versus month-first is
genuinely ambiguous, and guessing silently corrupts every date filter downstream. An unparsed
date is visibly wrong; a wrongly-parsed one is invisibly wrong.

**Second-order bug:** my first fix checked `dtype != object`, but pandas 3.0 gives text columns
a `str` dtype, so the check never fired and the fix did nothing while looking correct. Now it
tests for what a column is *not* — numeric, datetime, bool.

**Recognition rule:** `dtype == object` is a version-fragile check. Test the property you care
about, not the label.

---

## 8. Chart selection

**Chose:** the model suggests, the code decides from the real result dtypes.

**Why:** a model asked for a chart will usually produce one, including for a single number.
The rules — scalar gets nothing, category + measure under 25 rows gets a bar, a real date
column gets a line — run against actual pandas dtypes and have the final say.

This is a small thing that demonstrates the general principle: **the model's output is an
input to a decision, not the decision.**

---

## 9. The repair loop

When the guard rejects a query or DuckDB throws, the error text goes back to the model and it
tries again. Bounded at two repairs, every attempt written to the run log.

**Why bounded:** an unbounded retry loop against a paid API is an outage and a bill.

**Why it is honest to call this agentic:** it is act → observe failure → correct, which is the
core tool-use loop. It is not a multi-agent system and I would not describe it as one.

---

## 10. Observability

**Chose:** a built-in run log — question, every attempt, the SQL, validation outcome, retry
errors, planning versus query latency, rows returned — visible under each answer in the UI.

**Why not Langfuse:** the trace here is two nodes deep. Langfuse earns its keep on branching
agent runs. Adding it would mean an external service, two API keys, and a network call on the
critical path, in exchange for a dashboard the reviewer cannot see without my credentials.

**Why that answer matters for the role:** not adding a hard dependency on a third-party service
inside a customer's deployment is the instinct, not the tooling.

The env-flag hook is in the README so it is a one-line change if a deployment wants it.

---

## 11. What breaks at scale

| Scale | What happens | What I would do |
|---|---|---|
| ~50 tables | Schemas stop fitting in the prompt | Schema RAG — retrieve the relevant tables first |
| 5M+ rows | Ingest is still fine (DuckDB is columnar); profiling gets slow | Sample for profiling, exact for queries |
| 100 files | Join detection is O(n²) across column pairs | Restrict to declared keys, or cap the pair count |
| Concurrent users | One in-memory DuckDB per session; memory grows linearly | Per-session file-backed databases with eviction |
| Repeat questions | Every question is a fresh model call | Cache the plan keyed on question + schema hash |

---

## 12. Where correctness was traded for time, on purpose

- **Column names are not sanitised.** Quoting is pushed to the model via the schema text.
  Sanitising to snake_case would raise the hit rate but show the user columns that do not
  match their spreadsheet.
- **Only the measure column is compared in evals**, not every column, because column naming is
  the model's choice. Row count plus the measure catches real errors; it would miss a wrong
  label on a correct number.
- **No streaming.** The user waits ~3s with a spinner. Streaming SQL generation would feel
  faster without being faster.
- **Session-scoped only.** No auth, no persistence, no multi-user.

---

## 13. Known weaknesses

Stated before the panel finds them:

1. **Ambiguous date formats are not parsed** — deliberate, but it is still a limitation.
2. **No column-level access control.** Fine for single-user; wrong for a real deployment.
3. **Join detection can produce a false positive** where two unrelated columns share a
   namespace and overlap by coincidence.
4. **The model can write a valid query that answers the wrong question.** The guard proves the
   query is *safe*, not that it is *right*. The eval set is the only defence, and it covers
   43 questions, not every question.
5. **Free-tier latency is variable** — usually 2–4s, occasionally 20s+ under load.
6. **Excel files with multiple sheets** load only the first sheet.
7. **The model occasionally refuses a question it can answer** - roughly 1 run in 50,
   claiming a value is absent when it is present. Hosted inference is not fully
   deterministic even at `temperature=0`. A false refusal is the failure mode I would pick
   if forced to choose, but it is still a failure.
8. **No aggregate-correctness check.** If the model writes `AVG` where the user meant a
   weighted average, nothing catches it.

---

## 14. If I had one more week

In priority order:
1. Replace uploads with live connectors — REST and webhook ingestion from the systems the data
   actually lives in. This is where the integration half of the FDE role would show up.
2. Schema RAG so the app survives past ~50 tables.
3. Per-user row-level permissions, enforced in the database rather than the app.
4. Plan caching keyed on question + schema hash.
5. A second engine for text-shaped questions, explicitly routed.
