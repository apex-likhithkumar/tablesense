# Tablesense — approach, key decisions, what's next

## Approach

Upload CSV/Excel files, ask analytical questions in plain English, get an answer with the
query that produced it.

Everything follows from one decision: **the model is a translator, not an accountant.** It
never sees a data row and never produces a number. It sees only the schema and emits a single
`SELECT`; DuckDB does every calculation.

That inverts where the risk sits. A model asked to add up 50,000 rows returns a plausible
figure with no way to detect when it's wrong. A model asked to write `SUM(quantity * unit_price)`
returns either valid SQL or a loud failure — no confidently-wrong middle ground. Every answer
is auditable: the query sits beside the result and can be re-run by hand.

Pipeline: profile the uploaded tables → send schema and detected join keys to the model →
**validate the returned SQL** → execute with a timeout → choose a chart from the real result
types → log everything. Guard rejections and database errors feed back to the model for up to
two repairs; after that the app refuses rather than guesses.

## Key decisions

**DuckDB and SQL, not pandas.** Cross-file analysis is a `JOIN`. With generated pandas the
model must reason about merge keys, and when it's wrong the result is a silently wrong number
rather than an error. SQL is also *provably* safe — `core/guard.py` parses it and requires a
single `SELECT` over known tables. Keyword matching wouldn't do: `SELECT 'drop table'` trips
it and `/*x*/DELETE` slips past.

**Join keys are verified, not guessed.** Candidates are found by name similarity, then
confirmed by an actual value-overlap query. Every table has an `id`; names alone invent joins.
On the sample data this finds all three real relationships at 100% overlap and no false ones.

**No RAG.** The data is structured. Aggregation needs every row while retrieval returns top-k,
and embeddings discard the magnitude and ordering that filters depend on. RAG would earn its
place for a data dictionary, or as schema RAG beyond ~50 tables.

**An open-weight model, benchmarked twice.** gpt-oss-120b (Apache 2.0). My first three-question
benchmark pointed at Qwen3.6; the full eval run then exhausted a daily token cap and revealed
why — Qwen is a reasoning model burning ~4,500 tokens of thinking to emit ~150 tokens of SQL.
gpt-oss produces the same SQL ~25× faster on ~7× fewer tokens.

**Correctness is measured.** 43 questions written before the implementation, with expected
answers from hand-written oracle SQL so a wrong model query can't become the expected answer.
Currently 43/43. Two earlier rounds of failures were bugs in my *harness*, not the app — it
compared rows positionally when both orderings were valid. Fixing the test rather than the
product was the point of having one.

**Known limits:** ambiguous dates like `03/04/2026` are deliberately left unparsed; there's no
column-level access control; the guard proves a query is safe, not that it answers the intended
question.

## What I'd build next

1. **Live connectors instead of uploads** — REST and webhook ingestion from the systems the data
   actually lives in.
2. **Schema RAG** past ~50 tables, where schemas stop fitting in the prompt.
3. **Row-level permissions enforced in the database**, so an application bug can't leak one
   user's rows into another's answer.
4. **Plan caching** keyed on question + schema hash.
