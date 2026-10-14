# Design decisions

Short notes on the choices behind this project and what they cost.

## DuckDB as the warehouse
**Why:** zero infrastructure, a single file, columnar and fast enough for tens of millions of rows, and it reads CSV directly. Anyone can clone the repo and reproduce the result in seconds.
**Trade-off:** it is a single-writer embedded database, so it does not model concurrent users or a networked warehouse. The SQL is standard enough to move to Postgres, Snowflake or BigQuery with small dialect edits (`try_strptime`, `qualify`, `generate_series`).

## Medallion layers (bronze / silver / gold)
**Why:** each layer has one job. Bronze preserves exactly what arrived (so a cleaning bug can always be fixed by re-running silver). Silver makes decisions about types and validity. Gold is shaped for questions, not for storage.
**Trade-off:** more tables than a single transform script, but every layer can be inspected and tested on its own.

## Bronze is all VARCHAR
Loading with inferred types would silently turn `"03/14/2025"` into a failure or a wrong date, and `""` into NULL. Reading everything as text moves every coercion decision into visible SQL in silver.

## Quarantine instead of delete
Bad rows go to `silver.rejected_*` with a `reject_reason`. A reconciliation check asserts `bronze distinct ids = silver + rejected`, so row loss is always explained. This is also what makes data quality reportable ("0.8% of orders rejected, mostly orphan customers") rather than invisible.

## SQL-first transformations, Python only for orchestration
Business logic lives in `.sql` files that run in filename order. They read like analytics code, are easy to review, and port to dbt almost mechanically. Python handles file loading, ordering, logging and data quality execution.

## Declarative data quality checks
Checks are data (`Check(name, layer, severity, sql)`), not scattered asserts. Adding a rule is one line, results are persisted per run in `ops.dq_results`, and severity separates "stop the pipeline" from "tell someone".

## Seeds for reference data
City spelling → city / province / region lives in `seeds/city_mapping.csv`, version-controlled and used by both the generator and the pipeline. A test asserts the seed is clean (unique, lowercase keys), because a duplicate key would silently fan out rows in the join.

## Full refresh, idempotent
Every run rebuilds all tables. At this size it takes seconds and removes a whole class of state bugs. A test re-runs the pipeline and checks identical row counts. **First thing to change at scale:** incremental loads keyed on `_loaded_at`.

## Revenue recognition
Revenue counts only `delivered` orders (including shipping fees in `order_total`). Returned orders are excluded from revenue and tracked separately as `return_rate`. Stating the rule explicitly prevents the classic "why doesn't this match finance" argument.

## Known limitations
- Synthetic data: findings validate the pipeline, not the real world.
- No slowly changing dimensions: a customer's latest city overwrites history.
- `current_date` is used to reject future-dated orders, so the pipeline's output for the same input can change if a source date ever falls between the run date and "tomorrow". The generator uses a far-future date for this anomaly to keep tests stable.
