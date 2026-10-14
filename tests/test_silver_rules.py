"""Unit tests for individual silver SQL files, run against tiny hand-written bronze tables."""
from __future__ import annotations

import pytest

from src import config


def _run(con, layer_file: str) -> None:
    con.execute((config.SQL_DIR / "silver" / layer_file).read_text())


@pytest.fixture()
def customers_mem(mem):
    mem.execute("create table ref.city_mapping as select * from (values "
                "('quezon city','Quezon City','Metro Manila','NCR'), ('qc','Quezon City','Metro Manila','NCR')"
                ") t(raw_value, city, province, region)")
    mem.execute("""create table bronze.customers (customer_id varchar, first_name varchar, last_name varchar,
                   email varchar, phone varchar, city varchar, signup_date varchar, updated_at varchar)""")
    return mem


def test_phone_numbers_are_normalised_to_e164(customers_mem):
    rows = [
        ("C1", "a", "b", "A@X.COM", "+639171234567", "QC", "2025-01-01", "2026-01-01 00:00:00"),
        ("C2", "a", "b", "b@x.com", "09171234567", "QC", "2025-01-01", "2026-01-01 00:00:00"),
        ("C3", "a", "b", "c@x.com", "9171234567", "QC", "2025-01-01", "2026-01-01 00:00:00"),
        ("C4", "a", "b", "d@x.com", "+63 917 123 4567", "QC", "2025-01-01", "2026-01-01 00:00:00"),
        ("C5", "a", "b", "e@x.com", "12345", "QC", "2025-01-01", "2026-01-01 00:00:00"),
        ("C6", "a", "b", "f@x.com", "", "QC", "2025-01-01", "2026-01-01 00:00:00"),
    ]
    customers_mem.executemany("insert into bronze.customers values (?,?,?,?,?,?,?,?)", rows)
    _run(customers_mem, "01_customers.sql")
    got = dict(customers_mem.execute("select customer_id, phone from silver.customers").fetchall())
    assert [got[f"C{i}"] for i in range(1, 5)] == ["+639171234567"] * 4
    assert got["C5"] is None and got["C6"] is None


def test_duplicate_customers_keep_latest_version(customers_mem):
    customers_mem.executemany("insert into bronze.customers values (?,?,?,?,?,?,?,?)", [
        ("C1", "juan", "DELA CRUZ", "old@x.com", "", "qc", "2025-01-01", "2026-01-01 00:00:00"),
        ("C1", "juan", "DELA CRUZ", "new@x.com", "", "Quezon City", "01/01/2025", "2026-06-01 00:00:00"),
    ])
    _run(customers_mem, "01_customers.sql")
    rows = customers_mem.execute("select email, last_name, city, signup_date::varchar from silver.customers").fetchall()
    assert rows == [("new@x.com", "Dela Cruz", "Quezon City", "2025-01-01")]


def test_unmapped_city_is_flagged_not_dropped(customers_mem):
    customers_mem.execute("insert into bronze.customers values "
                          "('C1','a','b','a@x.com','','Atlantis','2025-01-01','2026-01-01 00:00:00')")
    _run(customers_mem, "01_customers.sql")
    assert customers_mem.execute("select city, is_city_mapped from silver.customers").fetchone() == ("Unknown", False)


def test_orders_parse_dates_normalise_values_and_reject_with_reason(mem):
    mem.execute("create table silver.customers as select 'C1' as customer_id")
    mem.execute("""create table bronze.orders (order_id varchar, customer_id varchar, order_date varchar,
                   status varchar, payment_method varchar, voucher_code varchar, shipping_fee varchar)""")
    mem.executemany("insert into bronze.orders values (?,?,?,?,?,?,?)", [
        ("O1", "C1", "2025-03-14", "Delivered", "G-Cash", "", "49"),
        ("O2", "C1", "03/14/2025", "canceled", "cash on delivery", "freeship", "0"),
        ("O3", "C1", "14-Mar-2025", "COMPLETED", "CC", "", "99"),
        ("O4", "C1", "not a date", "delivered", "gcash", "", "0"),
        ("O5", "C1", "2031-01-15", "delivered", "gcash", "", "0"),
        ("O6", "C9", "2025-03-14", "delivered", "gcash", "", "0"),
        ("O1", "C1", "2025-03-14", "Delivered", "G-Cash", "", "49"),  # exact duplicate
    ])
    _run(mem, "03_orders.sql")

    good = {r[0]: r[1:] for r in mem.execute(
        "select order_id, order_date::varchar, status, payment_method, voucher_code from silver.orders").fetchall()}
    assert good == {
        "O1": ("2025-03-14", "delivered", "GCash", None),
        "O2": ("2025-03-14", "cancelled", "COD", "FREESHIP"),
        "O3": ("2025-03-14", "delivered", "Credit Card", None),
    }
    rejected = dict(mem.execute("select order_id, reject_reason from silver.rejected_orders").fetchall())
    assert rejected == {"O4": "unparseable_order_date", "O5": "future_order_date", "O6": "orphan_customer"}


def test_order_items_reject_bad_quantities_and_prices(mem):
    mem.execute("create table silver.orders as select 'O1' as order_id")
    mem.execute("create table silver.products as select 'P1' as product_id")
    mem.execute("create table bronze.order_items (order_item_id varchar, order_id varchar, product_id varchar, "
                "quantity varchar, unit_price varchar)")
    mem.executemany("insert into bronze.order_items values (?,?,?,?,?)", [
        ("I1", "O1", "P1", "2", "100.50"),
        ("I2", "O1", "P1", "0", "100"),
        ("I3", "O1", "P1", "", "100"),
        ("I4", "O1", "P1", "1", "-1"),
        ("I5", "O9", "P1", "1", "100"),
        ("I6", "O1", "P9", "1", "100"),
    ])
    _run(mem, "04_order_items.sql")
    assert mem.execute("select order_item_id, line_amount from silver.order_items").fetchall() == [("I1", 201.00)]
    reasons = dict(mem.execute("select order_item_id, reject_reason from silver.rejected_order_items").fetchall())
    assert reasons == {"I2": "invalid_quantity", "I3": "invalid_quantity", "I4": "invalid_unit_price",
                       "I5": "orphan_order", "I6": "orphan_product"}
