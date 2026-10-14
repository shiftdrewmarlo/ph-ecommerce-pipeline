-- Gold facts.
--   fact_orders       grain: one row per order
--   fact_order_items  grain: one row per order line

create or replace table gold.fact_orders as
with item_totals as (
    select order_id,
           count(*)         as line_count,
           sum(quantity)    as units,
           sum(line_amount) as merchandise_value
    from silver.order_items
    group by order_id
)
select
    row_number() over (order by o.order_id)::integer         as order_key,
    o.order_id,
    o.order_date,
    strftime(o.order_date, '%Y%m%d')::integer                as date_key,
    c.customer_key,
    dc.courier_key,
    o.status,
    o.payment_method,
    o.voucher_code,
    o.voucher_code is not null                               as has_voucher,
    o.shipping_fee,
    coalesce(t.line_count, 0)                                as line_count,
    coalesce(t.units, 0)                                     as units,
    coalesce(t.merchandise_value, 0)::decimal(14, 2)         as merchandise_value,
    (coalesce(t.merchandise_value, 0) + o.shipping_fee)::decimal(14, 2) as order_total,
    d.shipped_date,
    d.delivered_date,
    d.transit_days
from silver.orders o
join gold.dim_customer c       on o.customer_id = c.customer_id
left join item_totals t        on o.order_id = t.order_id
left join silver.deliveries d  on o.order_id = d.order_id
left join gold.dim_courier dc  on d.courier = dc.courier;

create or replace table gold.fact_order_items as
select
    i.order_item_id,
    fo.order_key,
    fo.date_key,
    fo.customer_key,
    p.product_key,
    fo.status as order_status,
    i.quantity,
    i.unit_price,
    i.line_amount
from silver.order_items i
join gold.fact_orders fo on i.order_id = fo.order_id
join gold.dim_product p  on i.product_id = p.product_id;
