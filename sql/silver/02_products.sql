-- silver.products: canonical category names and a typed, positive price.
create or replace table silver.products as
select
    trim(product_id)   as product_id,
    trim(product_name) as product_name,
    case replace(lower(trim(category)), ' and ', ' & ')
        when 'electronics'   then 'Electronics'
        when 'beauty'        then 'Beauty'
        when 'home & living' then 'Home & Living'
        when 'fashion'       then 'Fashion'
        when 'grocery'       then 'Grocery'
        when 'sports'        then 'Sports'
        when 'toys'          then 'Toys'
        else title_case(trim(category))
    end                                      as category,
    try_cast(unit_price as decimal(12, 2))   as unit_price
from bronze.products
where nullif(trim(product_id), '') is not null
  and try_cast(unit_price as decimal(12, 2)) > 0
qualify row_number() over (partition by trim(product_id) order by _loaded_at) = 1;
