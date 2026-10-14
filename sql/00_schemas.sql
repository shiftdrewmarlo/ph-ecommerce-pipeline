-- Medallion layers + reference data + pipeline metadata.
create schema if not exists bronze;  -- raw, as received (all VARCHAR)
create schema if not exists ref;     -- seed / lookup tables kept in git
create schema if not exists silver;  -- cleaned, typed, deduplicated
create schema if not exists gold;    -- star schema + analytics marts
create schema if not exists ops;     -- run log and data quality results

create table if not exists ops.run_log (
    run_id       varchar,
    step         varchar,
    started_at   timestamp,
    duration_s   double,
    status       varchar,
    detail       varchar
);

create table if not exists ops.dq_results (
    run_id       varchar,
    checked_at   timestamp,
    check_name   varchar,
    layer        varchar,
    severity     varchar,   -- error = fails the pipeline, warn = reported only
    failed_rows  bigint,
    status       varchar    -- pass | fail
);

-- DuckDB has no INITCAP; this macro title-cases each space-separated word.
create or replace macro title_case(s) as
    array_to_string(list_transform(string_split(lower(trim(s)), ' '), w -> upper(w[1:1]) || w[2:]), ' ');
