"""End-to-end tests: run the whole pipeline once (see conftest) and assert on the results."""
from __future__ import annotations

import duckdb
import pytest

from src import quality


def scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def test_all_data_quality_checks_pass(build):
    assert build.summary["checks_failed"] == 0
    assert build.summary["checks_passed"] == len(quality.CHECKS)


def test_nothing_disappears_silently(built_warehouse):
    con = built_warehouse
    bronze_ids = scalar(con, "select count(distinct trim(order_id)) from bronze.orders")
    kept = scalar(con, "select count(*) from silver.orders")
    rejected = scalar(con, "select count(*) from silver.rejected_orders")
    assert bronze_ids == kept + rejected


def test_cleaning_actually_removed_the_mess(built_warehouse):
    con = built_warehouse
    assert scalar(con, "select count(*) from bronze.orders") > scalar(con, "select count(*) from silver.orders")
    assert scalar(con, "select count(distinct status) from silver.orders") == 6
    assert scalar(con, "select count(distinct payment_method) from silver.orders") == 6
    assert scalar(con, "select count(distinct category) from silver.products") == 7
    assert scalar(con, "select count(*) from silver.customers where not is_city_mapped") == 0


def test_star_schema_is_referentially_intact(built_warehouse):
    con = built_warehouse
    assert scalar(con, """select count(*) from gold.fact_orders f
                          left join gold.dim_customer c using (customer_key) where c.customer_key is null""") == 0
    assert scalar(con, """select count(*) from gold.fact_order_items f
                          left join gold.dim_product p using (product_key) where p.product_key is null""") == 0
    assert scalar(con, "select count(*) from gold.fact_orders") == scalar(con, "select count(*) from silver.orders")


def test_revenue_reconciles_between_fact_and_marts(built_warehouse):
    con = built_warehouse
    fact = scalar(con, "select sum(order_total) from gold.fact_orders where status = 'delivered'")
    mart = scalar(con, "select sum(revenue) from gold.mart_daily_sales")
    assert float(fact) == pytest.approx(float(mart), abs=0.01)


def test_rfm_segments_cover_every_buying_customer(built_warehouse):
    con = built_warehouse
    buyers = scalar(con, "select count(distinct customer_key) from gold.fact_orders where status = 'delivered'")
    assert scalar(con, "select count(*) from gold.mart_customer_rfm") == buyers
    assert scalar(con, "select count(*) from gold.mart_customer_rfm where segment is null") == 0


def test_every_cohort_starts_at_100_percent_retention(built_warehouse):
    con = built_warehouse
    assert scalar(con, "select min(retention_rate) from gold.mart_cohort_retention where months_since_first = 0") == 1.0


def test_run_log_records_every_step(built_warehouse):
    con = built_warehouse
    steps = scalar(con, "select count(*) from ops.run_log where status = 'success'")
    assert steps >= 10
    assert scalar(con, "select count(*) from ops.run_log where status = 'failed'") == 0


def test_pipeline_is_idempotent(build, built_warehouse, tmp_path):
    """Re-running on the same raw files must produce identical row counts."""
    from src import pipeline

    db2 = tmp_path / "again.duckdb"
    pipeline.run(db_path=db2, raw_dir=build.raw_dir)
    con2 = duckdb.connect(str(db2), read_only=True)
    try:
        for table in ("silver.orders", "gold.fact_order_items", "gold.mart_customer_rfm"):
            sql = f"select count(*) from {table}"
            assert scalar(con2, sql) == scalar(built_warehouse, sql)
    finally:
        con2.close()
