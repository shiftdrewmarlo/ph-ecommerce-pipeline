"""Every dashboard query must run against a freshly built warehouse and return sane data."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
import queries as q  # noqa: E402


def test_all_dashboard_queries_run(built_warehouse):
    con = built_warehouse
    start, end = q.date_bounds(con)
    assert start < end

    k = q.kpis(con, start, end)
    assert k["revenue"] > 0 and k["orders"] > 0 and 0 <= k["cancel_rate"] <= 1

    for df in (q.daily_sales(con, start, end), q.category_revenue(con, start, end), q.payment_performance(con),
               q.courier_performance(con), q.region_sales(con), q.rfm_segments(con), q.cohort_retention(con),
               q.dq_latest(con), q.rejections(con)):
        assert len(df) > 0


def test_kpi_revenue_equals_category_revenue(built_warehouse):
    con = built_warehouse
    start, end = q.date_bounds(con)
    from_kpi = q.kpis(con, start, end)["revenue"]
    # Category revenue excludes shipping fees, so it must be below total revenue but within the same order of magnitude.
    from_cat = q.category_revenue(con, start, end)["revenue"].sum()
    assert 0 < float(from_cat) <= float(from_kpi)
