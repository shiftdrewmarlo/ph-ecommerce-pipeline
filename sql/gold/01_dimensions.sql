-- Gold dimensions (star schema). Surrogate keys are deterministic: ordered by the natural key.

create or replace table gold.dim_date as
select
    strftime(d, '%Y%m%d')::integer              as date_key,
    d::date                                     as date,
    year(d)                                     as year,
    quarter(d)                                  as quarter,
    month(d)                                    as month,
    strftime(d, '%B')                           as month_name,
    strftime(d, '%Y-%m')                        as year_month,
    isodow(d)                                   as iso_day_of_week,
    strftime(d, '%A')                           as day_name,
    isodow(d) in (6, 7)                         as is_weekend,
    -- PH e-commerce calendar: 9.9, 10.10, 11.11, 12.12 mega-sales and 15th/30th paydays.
    (day(d) = month(d))                         as is_double_digit_sale,
    (day(d) = 15 or d::date = last_day(d::date)) as is_payday
from generate_series(date '2025-01-01', date '2026-12-31', interval 1 day) t(d);

create or replace table gold.dim_customer as
select
    row_number() over (order by customer_id)::integer as customer_key,
    customer_id, full_name, email, phone, city, province, region, signup_date
from silver.customers;

create or replace table gold.dim_product as
select
    row_number() over (order by product_id)::integer as product_key,
    product_id, product_name, category, unit_price as list_price
from silver.products;

create or replace table gold.dim_courier as
select
    row_number() over (order by courier)::integer as courier_key,
    courier
from (select distinct courier from silver.deliveries);
