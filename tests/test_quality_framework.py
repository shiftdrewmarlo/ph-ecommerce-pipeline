"""The DQ framework itself must catch bad data — otherwise green checks mean nothing."""
from __future__ import annotations

import pytest

from src import quality


def test_unique_check_detects_duplicates(mem):
    mem.execute("create table silver.orders as select * from (values ('O1'), ('O1'), ('O2')) t(order_id)")
    results = quality.run_checks(mem, "t1", [quality._unique("silver", "orders", "order_id")])
    assert results[0]["status"] == "fail" and results[0]["failed_rows"] == 1


def test_accepted_values_check_detects_unknown_and_null(mem):
    mem.execute("create table silver.orders as select * from (values ('delivered'), ('weird'), (null)) t(status)")
    results = quality.run_checks(mem, "t2", [quality._accepted("silver", "orders", "status", ["delivered"])])
    assert results[0]["failed_rows"] == 2


def test_results_are_persisted(mem):
    mem.execute("create table silver.orders as select 'O1' as order_id")
    quality.run_checks(mem, "t3", [quality._unique("silver", "orders", "order_id")])
    assert mem.execute("select count(*) from ops.dq_results where run_id = 't3'").fetchone()[0] == 1


def test_enforce_raises_only_for_blocking_failures():
    warn_only = [{"check_name": "x", "severity": "warn", "status": "fail"}]
    quality.enforce(warn_only)  # must not raise
    blocking = warn_only + [{"check_name": "y", "severity": "error", "status": "fail"}]
    with pytest.raises(quality.DataQualityError, match="y"):
        quality.enforce(blocking)
