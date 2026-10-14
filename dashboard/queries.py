"""SQL used by the dashboard. Kept separate from the UI so it can be tested without Streamlit."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "warehouse" / "warehouse.duckdb"


def connect(db_path: Path = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def kpis(con, start, end) -> dict:
    row = con.execute(
        """
        select
            coalesce(sum(revenue), 0), coalesce(sum(orders), 0),
            coalesce(sum(revenue) / nullif(sum(delivered_orders), 0), 0),
            coalesce(sum(cancelled_orders) * 1.0 / nullif(sum(orders), 0), 0)
        from gold.mart_daily_sales where order_date between ? and ?
        """, [start, end]).fetchone()
    return {"revenue": row[0], "orders": row[1], "aov": row[2], "cancel_rate": row[3]}


def date_bounds(con):
    return con.execute("select min(order_date), max(order_date) from gold.mart_daily_sales").fetchone()


def daily_sales(con, start, end) -> pd.DataFrame:
    return con.execute(
        "select order_date, revenue, orders, is_double_digit_sale from gold.mart_daily_sales "
        "where order_date between ? and ? order by order_date", [start, end]).fetchdf()


def category_revenue(con, start, end) -> pd.DataFrame:
    return con.execute(
        """
        select category, sum(revenue) as revenue, avg(return_rate) as return_rate
        from gold.mart_category_performance
        where year_month between strftime(?::date, '%Y-%m') and strftime(?::date, '%Y-%m')
        group by category order by revenue desc
        """, [start, end]).fetchdf()


def payment_performance(con) -> pd.DataFrame:
    return con.execute("select * from gold.mart_payment_method_performance").fetchdf()


def courier_performance(con) -> pd.DataFrame:
    return con.execute("select * from gold.mart_courier_performance").fetchdf()


def region_sales(con) -> pd.DataFrame:
    return con.execute("select * from gold.mart_region_sales").fetchdf()


def rfm_segments(con) -> pd.DataFrame:
    return con.execute(
        "select segment, count(*) as customers, sum(monetary) as monetary "
        "from gold.mart_customer_rfm group by segment order by monetary desc").fetchdf()


def cohort_retention(con) -> pd.DataFrame:
    return con.execute(
        "select strftime(cohort_month, '%Y-%m') as cohort, months_since_first, retention_rate "
        "from gold.mart_cohort_retention where months_since_first <= 12 order by 1, 2").fetchdf()


def dq_latest(con) -> pd.DataFrame:
    return con.execute(
        """
        select layer, check_name, severity, failed_rows, status
        from ops.dq_results
        where run_id = (select run_id from ops.dq_results order by checked_at desc limit 1)
        order by status desc, layer, check_name
        """).fetchdf()


def rejections(con) -> pd.DataFrame:
    return con.execute(
        """
        select 'orders' as table_name, reject_reason, count(*) as rows from silver.rejected_orders group by all
        union all select 'order_items', reject_reason, count(*) from silver.rejected_order_items group by all
        union all select 'deliveries', reject_reason, count(*) from silver.rejected_deliveries group by all
        order by 1, 3 desc
        """).fetchdf()
