"""Streamlit dashboard over the gold marts.   Run:  streamlit run dashboard/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import queries as q  # noqa: E402

st.set_page_config(page_title="PH E-commerce Analytics", page_icon="📦", layout="wide")

if not q.DEFAULT_DB.exists():
    st.error("Warehouse not found. Run `make pipeline` first.")
    st.stop()

con = q.connect()
min_d, max_d = q.date_bounds(con)

st.title("PH E-commerce Analytics")
st.caption("Synthetic data · revenue is recognised on delivered orders · built from the gold marts in DuckDB")

with st.sidebar:
    st.header("Filters")
    start, end = st.date_input("Order date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)

k = q.kpis(con, start, end)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Revenue", f"₱{k['revenue']:,.0f}")
c2.metric("Orders", f"{k['orders']:,}")
c3.metric("Avg order value", f"₱{k['aov']:,.0f}")
c4.metric("Cancellation rate", f"{k['cancel_rate']:.1%}")

tab_sales, tab_ops, tab_customers, tab_quality = st.tabs(["Sales", "Operations", "Customers", "Data quality"])

with tab_sales:
    daily = q.daily_sales(con, start, end)
    fig = px.line(daily, x="order_date", y="revenue", title="Daily revenue (delivered orders)")
    sale_days = daily[daily["is_double_digit_sale"]]
    fig.add_scatter(x=sale_days["order_date"], y=sale_days["revenue"], mode="markers",
                    name="Double-digit sale day (9.9, 10.10 …)")
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    cat = q.category_revenue(con, start, end)
    left.plotly_chart(px.bar(cat, x="revenue", y="category", orientation="h", title="Revenue by category")
                      .update_yaxes(autorange="reversed"), width="stretch")
    region = q.region_sales(con)
    right.plotly_chart(px.bar(region, x="revenue", y="region", orientation="h", title="Revenue by region (all time)")
                       .update_yaxes(autorange="reversed"), width="stretch")

with tab_ops:
    left, right = st.columns(2)
    pay = q.payment_performance(con)
    fig_pay = px.bar(pay, x="payment_method", y="cancellation_rate", title="Cancellation rate by payment method")
    left.plotly_chart(fig_pay.update_yaxes(tickformat=".0%"), width="stretch")
    cour = q.courier_performance(con)
    fig_cour = px.bar(cour, x="courier", y="on_time_rate", title="On-time rate by courier (≤ 5 days in transit)")
    right.plotly_chart(fig_cour.update_yaxes(tickformat=".0%", range=[0, 1]), width="stretch")
    st.dataframe(cour, width="stretch", hide_index=True)

with tab_customers:
    left, right = st.columns(2)
    seg = q.rfm_segments(con)
    left.plotly_chart(px.bar(seg, x="customers", y="segment", orientation="h", title="Customers per RFM segment")
                      .update_yaxes(autorange="reversed"), width="stretch")
    right.plotly_chart(px.pie(seg, values="monetary", names="segment", title="Revenue share by RFM segment"),
                       width="stretch")
    coh = q.cohort_retention(con)
    heat = coh.pivot(index="cohort", columns="months_since_first", values="retention_rate")
    st.plotly_chart(px.imshow(heat, aspect="auto", color_continuous_scale="Blues", zmin=0, zmax=0.4,
                              labels={"x": "Months since first purchase", "y": "Cohort", "color": "Retention"},
                              title="Monthly cohort retention (scale capped at 40% so month 1+ is readable)"),
                    width="stretch")

with tab_quality:
    dq = q.dq_latest(con)
    passed = int((dq["status"] == "pass").sum())
    st.metric("Checks passing (latest run)", f"{passed} / {len(dq)}")
    st.dataframe(dq, width="stretch", hide_index=True)
    st.subheader("Rows quarantined by the silver layer")
    st.caption("Bad rows are never dropped silently — each is stored with a reject reason.")
    st.dataframe(q.rejections(con), width="stretch", hide_index=True)
