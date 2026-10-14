-- silver.customers
-- Cleans names/emails/phones, standardises city -> province -> region through the
-- ref.city_mapping seed, and keeps only the most recent version of each customer_id.
create or replace table silver.customers as
with parsed as (
    select
        trim(customer_id)                                   as customer_id,
        title_case(trim(first_name))                           as first_name,
        title_case(trim(last_name))                            as last_name,
        nullif(lower(trim(email)), '')                      as email,
        regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g') as phone_digits,
        lower(trim(city))                                   as city_key,
        coalesce(
            try_strptime(trim(signup_date), '%Y-%m-%d'),
            try_strptime(trim(signup_date), '%m/%d/%Y')
        )::date                                             as signup_date,
        try_cast(updated_at as timestamp)                   as updated_at
    from bronze.customers
    where nullif(trim(customer_id), '') is not null
),
latest as (
    select *
    from parsed
    qualify row_number() over (partition by customer_id order by updated_at desc nulls last) = 1
)
select
    l.customer_id,
    l.first_name,
    l.last_name,
    l.first_name || ' ' || l.last_name as full_name,
    l.email,
    -- Normalise PH mobile numbers to E.164 (+639XXXXXXXXX); anything else becomes NULL.
    case
        when starts_with(l.phone_digits, '63') and length(l.phone_digits) = 12 then '+' || l.phone_digits
        when starts_with(l.phone_digits, '09') and length(l.phone_digits) = 11 then '+63' || substr(l.phone_digits, 2)
        when starts_with(l.phone_digits, '9')  and length(l.phone_digits) = 10 then '+63' || l.phone_digits
    end                                  as phone,
    coalesce(m.city, 'Unknown')          as city,
    coalesce(m.province, 'Unknown')      as province,
    coalesce(m.region, 'Unknown')        as region,
    m.city is not null                   as is_city_mapped,
    l.signup_date,
    l.updated_at
from latest l
left join ref.city_mapping m on l.city_key = m.raw_value;
