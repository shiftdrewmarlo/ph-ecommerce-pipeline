-- silver.order_items / silver.rejected_order_items
create or replace temp table _items_stage as
with parsed as (
    select
        trim(order_item_id)                  as order_item_id,
        trim(order_id)                       as order_id,
        trim(product_id)                     as product_id,
        try_cast(quantity as integer)        as quantity,
        try_cast(unit_price as decimal(12, 2)) as unit_price
    from bronze.order_items
    where nullif(trim(order_item_id), '') is not null
),
deduped as (
    select * from parsed
    qualify row_number() over (partition by order_item_id order by order_id) = 1
)
select
    i.*,
    case
        when i.quantity is null or i.quantity <= 0     then 'invalid_quantity'
        when i.unit_price is null or i.unit_price <= 0 then 'invalid_unit_price'
        when o.order_id is null                        then 'orphan_order'
        when p.product_id is null                      then 'orphan_product'
    end as reject_reason
from deduped i
left join silver.orders   o on i.order_id = o.order_id
left join silver.products p on i.product_id = p.product_id;

create or replace table silver.order_items as
select order_item_id, order_id, product_id, quantity, unit_price,
       quantity * unit_price as line_amount
from _items_stage
where reject_reason is null;

create or replace table silver.rejected_order_items as
select order_item_id, order_id, product_id, quantity, unit_price, reject_reason
from _items_stage
where reject_reason is not null;
