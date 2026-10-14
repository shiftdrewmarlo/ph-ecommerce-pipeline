-- silver.deliveries / silver.rejected_deliveries
create or replace temp table _deliveries_stage as
with parsed as (
    select
        trim(order_id) as order_id,
        case replace(lower(trim(courier)), ' ', '')
            when 'j&t'          then 'J&T Express'
            when 'j&texpress'   then 'J&T Express'
            when 'jnt'          then 'J&T Express'
            when 'lbc'          then 'LBC'
            when 'flash'        then 'Flash Express'
            when 'flashexpress' then 'Flash Express'
            when 'ninjavan'     then 'Ninja Van'
        end as courier,
        coalesce(try_strptime(trim(shipped_date), '%Y-%m-%d'),
                 try_strptime(trim(shipped_date), '%m/%d/%Y'))::date as shipped_date,
        coalesce(try_strptime(nullif(trim(delivered_date), ''), '%Y-%m-%d'),
                 try_strptime(nullif(trim(delivered_date), ''), '%m/%d/%Y'))::date as delivered_date
    from bronze.deliveries
    where nullif(trim(order_id), '') is not null
),
deduped as (
    select * from parsed
    qualify row_number() over (partition by order_id order by shipped_date nulls last) = 1
)
select
    d.*,
    case
        when o.order_id is null                          then 'orphan_order'
        when d.courier is null                           then 'unknown_courier'
        when d.shipped_date is null                      then 'unparseable_shipped_date'
        when d.delivered_date < d.shipped_date           then 'delivered_before_shipped'
    end as reject_reason
from deduped d
left join silver.orders o on d.order_id = o.order_id;

create or replace table silver.deliveries as
select order_id, courier, shipped_date, delivered_date,
       date_diff('day', shipped_date, delivered_date) as transit_days
from _deliveries_stage
where reject_reason is null;

create or replace table silver.rejected_deliveries as
select order_id, courier, shipped_date, delivered_date, reject_reason
from _deliveries_stage
where reject_reason is not null;
