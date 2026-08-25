# Tablesense — approach, decisions, and what's next

## Approach

Upload CSV/Excel files, ask analytical questions in plain English, get an answer with the
query that produced it.

Everything follows from one decision: **the model is a translator, not an accountant.** The
LLM never sees a data row and never produces a number. It sees only the schema and emits a
single `SELECT`; DuckDB does every calculation.

That inverts where the risk sits. Asking a model to add up 50,000 rows yields a plausible
figure with no way to detect when it's wrong. Asking it to write `SUM(quantity * unit_price)`
yields either valid SQL or a loud failure — no confidently-wrong middle ground. It also makes
every answer auditable: the query is shown beside the result and can be re-run by hand.

The pipeline is: profile the uploaded tables → send schema and detected join keys to the model
→ **validate the returned SQL** → execute with a timeout → pick a chart from the real result
types → log everything. Guard rejections and database errors are fed back to the model for up
to two repairs; after that the app refuses rather than guessing.

## Key decisions

**DuckDB and SQL, not pandas.** Cross-file analysis is the brief's second criterion, and in
SQL that's a `JOIN`. With generated pandas the model must reason about merge keys, and when it
gets that wrong the result is a silently wrong number rather than an error. SQL is also
*provably* safe: `core/guard.py` parses it with `sqlglot` and requires a single `SELECT` over
known tables. Keyword matching wouldn't do — `SELECT 'drop table'` trips it and `/*x*/DELETE`
slips past. Only a syntax tree tells you what a statement is.

**Join keys are verified, not guessed.** Candidate keys are found by name similarity, then
confirmed with an actual value-overlap query. Every table has an `id`; name matching alone
invents joins, and a wrong join is a wrong number that looks right. On the sample data this
finds all three real relationships at 100% overlap and no false ones.

**No RAG.** The data is structured. Aggregation needs every row while retrieval returns top-k;
embeddings discard magnitude and ordering, so `WHERE amount > 5000` has no similarity
equivalent; and joins don't survive retrieval. RAG would earn its place for a data dictionary,
or as schema RAG beyond ~50 tables where schemas stop fitting in context. At four files it's
cost with no benefit.

**An open-weight model, benchmarked rather than assumed.** Qwen3.6-27B (Apache 2.0) on Groq,
chosen over gpt-oss-120b after comparing both on a three-table join, a time-series
aggregation, and an unanswerable question — comparable accuracy, roughly 5× lower latency,
better chart hints. Provider is one config line; Ollama and Together speak the same protocol.

**Correctness is measured, not asserted.** 43 questions written before the implementation,
with expected answers from hand-written oracle SQL — so a wrong model query can't quietly
become the expected answer. Two rounds of failures came from my *harness*, not the app: it
compared rows positionally when both orderings were valid, and compared the last column when
the app legitimately returned an extra one. Fixing the test rather than the product was the
right call, and finding that out is exactly why the eval set exists.

## Known limitations

Ambiguous dates like `03/04/2026` are deliberately left unparsed — guessing day-first versus
month-first silently corrupts every date filter, and an unparsed date is visibly wrong while a
mis-parsed one is invisibly wrong. There's no column-level access control, so it suits one
analyst rather than a team. The guard proves a query is *safe*, not that it answers the
*intended* question — the eval set is the only defence there, and it covers 43 questions, not
every question. Free-tier latency is variable: usually a few seconds, occasionally 20 seconds
under load.

## What I'd build next

1. **Live connectors instead of uploads** — REST and webhook ingestion from the systems the
   data actually lives in, rather than a file someone exported by hand.
2. **Schema RAG** past ~50 tables, where schemas no longer fit in the prompt.
3. **Row-level permissions enforced in the database**, not the application, so an app bug can't
   leak one user's rows into another's answer.
4. **Plan caching** keyed on question + schema hash — repeat questions currently pay full
   model latency.
5. **A second engine for text-shaped questions**, explicitly routed and labelled, so questions
   SQL can't express stop being refusals.
