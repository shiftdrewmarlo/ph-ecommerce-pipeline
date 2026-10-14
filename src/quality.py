"""Data quality framework.

Each check is a SQL query that returns the number of FAILING rows (0 = pass).
Checks are declared as data, results are persisted to ops.dq_results, and any
failing check with severity "error" stops the pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import duckdb

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Check:
    name: str
    layer: str
    severity: str  # "error" | "warn"
    sql: str       # returns a single integer: number of failing rows


def _unique(layer: str, table: str, col: str) -> Check:
    return Check(f"{table}.{col} is unique", layer, "error",
                 f"select count(*) from (select {col} from {layer}.{table} group by {col} having count(*) > 1)")


def _not_null(layer: str, table: str, col: str) -> Check:
    return Check(f"{table}.{col} is not null", layer, "error",
                 f"select count(*) from {layer}.{table} where {col} is null")


def _accepted(layer: str, table: str, col: str, values: list[str]) -> Check:
    quoted = ", ".join(f"'{v}'" for v in values)
    return Check(f"{table}.{col} in accepted values", layer, "error",
                 f"select count(*) from {layer}.{table} where {col} is null or {col} not in ({quoted})")


def _fk(layer: str, child: str, col: str, parent: str, pcol: str, severity: str = "error") -> Check:
    return Check(f"{child}.{col} references {parent}.{pcol}", layer, severity,
                 f"select count(*) from {layer}.{child} c where c.{col} is not null "
                 f"and not exists (select 1 from gold.{parent} p where p.{pcol} = c.{col})")


CHECKS: list[Check] = [
    # --- silver: keys ---------------------------------------------------------------
    _unique("silver", "customers", "customer_id"),
    _unique("silver", "products", "product_id"),
    _unique("silver", "orders", "order_id"),
    _unique("silver", "order_items", "order_item_id"),
    _unique("silver", "deliveries", "order_id"),
    _not_null("silver", "orders", "order_date"),
    _not_null("silver", "orders", "customer_id"),
    # --- silver: domains ------------------------------------------------------------
    _accepted("silver", "orders", "status",
              ["delivered", "cancelled", "returned", "shipped", "pending", "failed"]),
    _accepted("silver", "orders", "payment_method",
              ["GCash", "COD", "Maya", "Credit Card", "Bank Transfer", "GrabPay"]),
    _accepted("silver", "deliveries", "courier", ["J&T Express", "LBC", "Flash Express", "Ninja Van"]),
    Check("orders.order_date is not in the future", "silver", "error",
          "select count(*) from silver.orders where order_date > current_date"),
    Check("order_items.quantity and unit_price are positive", "silver", "error",
          "select count(*) from silver.order_items where quantity <= 0 or unit_price <= 0"),
    Check("deliveries: delivered_date >= shipped_date", "silver", "error",
          "select count(*) from silver.deliveries where delivered_date < shipped_date"),
    Check("customers.phone matches +639XXXXXXXXX", "silver", "warn",
          "select count(*) from silver.customers "
          "where phone is not null and not regexp_matches(phone, '^\\+639[0-9]{9}$')"),
    Check("customers.city is mapped to a known city", "silver", "warn",
          "select count(*) from silver.customers where not is_city_mapped"),
    # --- reconciliation: nothing disappears silently -------------------------------
    Check("orders: bronze distinct ids = silver + rejected", "silver", "error",
          """select abs(
                (select count(distinct trim(order_id)) from bronze.orders where nullif(trim(order_id), '') is not null)
              - (select count(*) from silver.orders)
              - (select count(*) from silver.rejected_orders))"""),
    Check("order_items: bronze distinct ids = silver + rejected", "silver", "error",
          """select abs(
                (select count(distinct trim(order_item_id)) from bronze.order_items
                  where nullif(trim(order_item_id), '') is not null)
              - (select count(*) from silver.order_items)
              - (select count(*) from silver.rejected_order_items))"""),
    Check("rejected order rate is under 5%", "silver", "warn",
          """select case when (select count(*) from silver.rejected_orders) * 1.0
                              / nullif((select count(*) from bronze.orders), 0) > 0.05 then 1 else 0 end"""),
    # --- gold: referential integrity + totals --------------------------------------
    _fk("gold", "fact_orders", "customer_key", "dim_customer", "customer_key"),
    _fk("gold", "fact_orders", "date_key", "dim_date", "date_key"),
    _fk("gold", "fact_order_items", "order_key", "fact_orders", "order_key"),
    _fk("gold", "fact_order_items", "product_key", "dim_product", "product_key"),
    Check("gold items total = silver items total", "gold", "error",
          """select case when abs((select sum(line_amount) from gold.fact_order_items)
                               - (select sum(line_amount) from silver.order_items)) > 0.01 then 1 else 0 end"""),
    Check("mart revenue = delivered order totals", "gold", "error",
          """select case when abs((select sum(revenue) from gold.mart_daily_sales)
                               - (select sum(order_total) from gold.fact_orders where status = 'delivered')) > 0.01
                        then 1 else 0 end"""),
    Check("retention rates are between 0 and 1", "gold", "error",
          "select count(*) from gold.mart_cohort_retention where retention_rate < 0 or retention_rate > 1"),
]


def run_checks(con: duckdb.DuckDBPyConnection, run_id: str, checks: list[Check] | None = None) -> list[dict]:
    results = []
    now = datetime.now()
    for chk in checks or CHECKS:
        failed = con.execute(chk.sql).fetchone()[0]
        status = "pass" if failed == 0 else "fail"
        results.append({"check_name": chk.name, "layer": chk.layer, "severity": chk.severity,
                        "failed_rows": int(failed), "status": status})
        con.execute("insert into ops.dq_results values (?, ?, ?, ?, ?, ?, ?)",
                    [run_id, now, chk.name, chk.layer, chk.severity, int(failed), status])
        level = logging.INFO if status == "pass" else (logging.ERROR if chk.severity == "error" else logging.WARNING)
        log.log(level, "DQ [%s] %-4s %s (failed_rows=%d)", chk.severity, status.upper(), chk.name, failed)
    return results


class DataQualityError(RuntimeError):
    pass


def enforce(results: list[dict]) -> None:
    errors = [r for r in results if r["status"] == "fail" and r["severity"] == "error"]
    if errors:
        names = "; ".join(r["check_name"] for r in errors)
        raise DataQualityError(f"{len(errors)} blocking data quality check(s) failed: {names}")
