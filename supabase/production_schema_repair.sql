-- MediCORE production schema repair
-- Safe to rerun in Supabase SQL Editor.
-- Purpose: repair schema drift between SQLAlchemy models and existing Supabase migrations.
-- This file is additive/idempotent: it does not drop tables, drop columns, or rewrite existing data.

begin;

create extension if not exists "uuid-ossp";

alter table if exists public.catalog_items
    add column if not exists moq numeric(14, 4),
    add column if not exists lead_time_days integer;

alter table if exists public.catalog_items
    alter column price_per_unit drop not null,
    alter column available_qty type numeric(14, 4),
    alter column available_qty drop not null,
    alter column unit drop not null,
    alter column moq type numeric(14, 4);

alter table if exists public.catalog_emails
    add column if not exists body_preview text,
    add column if not exists duplicate_count integer not null default 0;

create unique index if not exists uq_catalog_emails_tenant_raw_email_id
    on public.catalog_emails (tenant_id, raw_email_id);

create index if not exists idx_catalog_emails_tenant_received
    on public.catalog_emails (tenant_id, received_at);

create index if not exists idx_catalog_emails_supplier_id
    on public.catalog_emails (supplier_id);

create index if not exists idx_catalog_emails_status
    on public.catalog_emails (tenant_id, processing_status);

create index if not exists idx_catalog_items_catalog_email_id
    on public.catalog_items (catalog_email_id);

create index if not exists idx_catalog_items_tenant_supplier
    on public.catalog_items (tenant_id, supplier_id);

create index if not exists idx_catalog_items_ingredient
    on public.catalog_items (tenant_id, ingredient_name);

do $$
begin
    if to_regclass('public.catalog_items') is not null then
        if not exists (
            select 1
            from information_schema.table_constraints
            where table_schema = 'public'
              and table_name = 'catalog_items'
              and constraint_name = 'catalog_items_catalog_email_id_fkey'
        ) then
            alter table public.catalog_items
                add constraint catalog_items_catalog_email_id_fkey
                foreign key (catalog_email_id) references public.catalog_emails(id);
        end if;
    end if;
end $$;

commit;

-- Verification query:
-- select column_name, data_type, is_nullable
-- from information_schema.columns
-- where table_schema = 'public'
--   and table_name = 'catalog_items'
--   and column_name in ('moq', 'lead_time_days', 'price_per_unit', 'available_qty', 'unit')
-- order by column_name;
