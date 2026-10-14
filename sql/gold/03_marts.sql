-- Gold marts: pre-aggregated tables the dashboard reads directly.
-- Business definition: revenue is recognised on DELIVERED orders only.

create or replace table gold.mart_daily_sales as
select
    fo.order_date,
    dd.is_double_digit_sale,
    dd.is_payday,
    count(*)                                              as orders,
    count(*) filter (where fo.status = 'delivered')       as delivered_orders,
    count(*) filter (where fo.status = 'cancelled')       as cancelled_orders,
    count(*) filter (where fo.status = 'returned')        as returned_orders,
    sum(fo.order_total)                                   as gmv,
    coalesce(sum(fo.order_total) filter (where fo.status = 'delivered'), 0) as revenue,
    round(avg(fo.order_total) filter (where fo.status = 'delivered'), 2)    as avg_order_value,
    round(count(*) filter (where fo.status = 'cancelled') * 1.0 / count(*), 4) as cancellation_rate
from gold.fact_orders fo
join gold.dim_date dd on fo.date_key = dd.date_key
group by fo.order_date, dd.is_double_digit_sale, dd.is_payday
order by fo.order_date;

create or replace table gold.mart_category_performance as
select
    dd.year_month,
    dp.category,
    sum(fi.quantity)                                                       as units_sold,
    count(distinct fi.order_key)                                           as orders,
    coalesce(sum(fi.line_amount) filter (where fi.order_status = 'delivered'), 0) as revenue,
    coalesce(sum(fi.line_amount) filter (where fi.order_status = 'returned'), 0)  as returned_value,
    round(
        coalesce(sum(fi.line_amount) filter (where fi.order_status = 'returned'), 0) * 1.0
        / nullif(sum(fi.line_amount) filter (where fi.order_status in ('delivered', 'returned')), 0), 4
    )                                                                      as return_rate
from gold.fact_order_items fi
join gold.dim_product dp on fi.product_key = dp.product_key
join gold.dim_date dd    on fi.date_key = dd.date_key
group by dd.year_month, dp.category
order by dd.year_month, dp.category;

create or replace table gold.mart_payment_method_performance as
select
    payment_method,
    count(*)                                                  as orders,
    round(sum(order_total), 2)                                as gmv,
    round(count(*) filter (where status = 'cancelled') * 1.0 / count(*), 4) as cancellation_rate,
    round(count(*) filter (where status = 'failed') * 1.0 / count(*), 4)    as failed_delivery_rate,
    round(count(*) filter (where status = 'returned') * 1.0 / count(*), 4)  as return_rate
from gold.fact_orders
group by payment_method
order by orders desc;

create or replace table gold.mart_courier_performance as
select
    dc.courier,
    count(*)                                                       as shipments,
    count(*) filter (where fo.status = 'delivered')                as delivered,
    count(*) filter (where fo.status = 'failed')                   as failed,
    round(avg(fo.transit_days), 2)                                 as avg_transit_days,
    round(quantile_cont(fo.transit_days, 0.9), 1)                  as p90_transit_days,
    -- SLA: delivered within 5 days of shipping.
    round(count(*) filter (where fo.transit_days <= 5) * 1.0
          / nullif(count(*) filter (where fo.transit_days is not null), 0), 4) as on_time_rate,
    round(count(*) filter (where fo.status = 'failed') * 1.0 / count(*), 4)   as failure_rate
from gold.fact_orders fo
join gold.dim_courier dc on fo.courier_key = dc.courier_key
group by dc.courier
order by shipments desc;

create or replace table gold.mart_region_sales as
select
    c.region,
    count(distinct fo.customer_key)                                         as customers,
    count(*)                                                                as orders,
    coalesce(sum(fo.order_total) filter (where fo.status = 'delivered'), 0) as revenue
from gold.fact_orders fo
join gold.dim_customer c on fo.customer_key = c.customer_key
group by c.region
order by revenue desc;

-- RFM segmentation on delivered orders, measured as of the latest order date in the data.
create or replace table gold.mart_customer_rfm as
with base as (
    select
        customer_key,
        max(order_date)         as last_order_date,
        count(*)                as frequency,
        sum(order_total)        as monetary
    from gold.fact_orders
    where status = 'delivered'
    group by customer_key
),
as_of as (select max(order_date) as d from gold.fact_orders),
scored as (
    select
        b.*,
        date_diff('day', b.last_order_date, a.d)                         as recency_days,
        6 - ntile(5) over (order by date_diff('day', b.last_order_date, a.d)) as r_score,
        ntile(5) over (order by b.frequency)                             as f_score,
        ntile(5) over (order by b.monetary)                              as m_score
    from base b cross join as_of a
)
select
    c.customer_id, c.full_name, c.city, c.region,
    s.recency_days, s.frequency, round(s.monetary, 2) as monetary,
    s.r_score, s.f_score, s.m_score,
    case
        when s.r_score >= 4 and s.f_score >= 4 then 'Champions'
        when s.r_score >= 3 and s.f_score >= 3 then 'Loyal'
        when s.r_score >= 4 and s.f_score <= 2 then 'New / Promising'
        when s.r_score <= 2 and s.f_score >= 4 then 'At Risk'
        when s.r_score <= 2 and s.f_score <= 2 then 'Hibernating'
        else 'Needs Attention'
    end as segment
from scored s
join gold.dim_customer c on s.customer_key = c.customer_key;

-- Monthly cohort retention: share of each first-purchase cohort that buys again in month N.
create or replace table gold.mart_cohort_retention as
with first_orders as (
    select customer_key, date_trunc('month', min(order_date))::date as cohort_month
    from gold.fact_orders
    where status = 'delivered'
    group by customer_key
),
activity as (
    select distinct customer_key, date_trunc('month', order_date)::date as activity_month
    from gold.fact_orders
    where status = 'delivered'
),
cohort_sizes as (
    select cohort_month, count(*) as cohort_size from first_orders group by cohort_month
)
select
    f.cohort_month,
    date_diff('month', f.cohort_month, a.activity_month) as months_since_first,
    count(distinct a.customer_key)                       as active_customers,
    cs.cohort_size,
    round(count(distinct a.customer_key) * 1.0 / cs.cohort_size, 4) as retention_rate
from first_orders f
join activity a      on f.customer_key = a.customer_key
join cohort_sizes cs on f.cohort_month = cs.cohort_month
group by f.cohort_month, months_since_first, cs.cohort_size
order by f.cohort_month, months_since_first;
