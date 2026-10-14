-- silver.orders / silver.rejected_orders
-- Parses 3 date formats, standardises status + payment method, deduplicates on order_id,
-- then splits rows into "good" and "rejected (with a reason)". Nothing is dropped silently:
-- bronze distinct order_ids = silver.orders + silver.rejected_orders (checked in DQ).
create or replace temp table _orders_stage as
with parsed as (
    select
        trim(order_id)    as order_id,
        trim(customer_id) as customer_id,
        coalesce(
            try_strptime(trim(order_date), '%Y-%m-%d'),
            try_strptime(trim(order_date), '%m/%d/%Y'),
            try_strptime(trim(order_date), '%d-%b-%Y')
        )::date as order_date,
        case lower(trim(status))
            when 'delivered'       then 'delivered'
            when 'completed'       then 'delivered'
            when 'cancelled'       then 'cancelled'
            when 'canceled'        then 'cancelled'
            when 'returned'        then 'returned'
            when 'return'          then 'returned'
            when 'shipped'         then 'shipped'
            when 'in transit'      then 'shipped'
            when 'pending'         then 'pending'
            when 'failed'          then 'failed'
            when 'delivery failed' then 'failed'
        end as status,
        case lower(trim(payment_method))
            when 'gcash'            then 'GCash'
            when 'g-cash'           then 'GCash'
            when 'cod'              then 'COD'
            when 'cash on delivery' then 'COD'
            when 'maya'             then 'Maya'
            when 'paymaya'          then 'Maya'
            when 'credit card'      then 'Credit Card'
            when 'credit_card'      then 'Credit Card'
            when 'cc'               then 'Credit Card'
            when 'bank transfer'    then 'Bank Transfer'
            when 'bank'             then 'Bank Transfer'
            when 'grabpay'          then 'GrabPay'
        end as payment_method,
        nullif(upper(trim(voucher_code)), '')       as voucher_code,
        try_cast(shipping_fee as decimal(10, 2))    as shipping_fee
    from bronze.orders
    where nullif(trim(order_id), '') is not null
),
deduped as (
    select *
    from parsed
    qualify row_number() over (partition by order_id order by order_date nulls last) = 1
)
select
    d.*,
    case
        when d.order_date is null            then 'unparseable_order_date'
        when d.order_date > current_date     then 'future_order_date'
        when d.status is null                then 'unknown_status'
        when d.payment_method is null        then 'unknown_payment_method'
        when c.customer_id is null           then 'orphan_customer'
    end as reject_reason
from deduped d
left join silver.customers c on d.customer_id = c.customer_id;

create or replace table silver.orders as
select order_id, customer_id, order_date, status, payment_method, voucher_code,
       coalesce(shipping_fee, 0) as shipping_fee
from _orders_stage
where reject_reason is null;

create or replace table silver.rejected_orders as
select order_id, customer_id, order_date, status, payment_method, reject_reason
from _orders_stage
where reject_reason is not null;
