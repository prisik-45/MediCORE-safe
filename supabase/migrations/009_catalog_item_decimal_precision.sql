alter table catalog_items
    add column if not exists moq numeric(14, 4),
    add column if not exists lead_time_days integer,
    alter column available_qty type numeric(14, 4),
    alter column moq type numeric(14, 4);
