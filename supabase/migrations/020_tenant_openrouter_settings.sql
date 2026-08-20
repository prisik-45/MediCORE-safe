-- Migration 020: tenant-scoped OpenRouter settings for production AI routing.
-- API keys are encrypted by the backend before storage; never expose encrypted values to browser clients.

create table if not exists public.tenant_ai_settings (
    tenant_id uuid primary key references public.profiles(id) on delete cascade,
    provider text not null default 'openrouter',
    encrypted_api_key text,
    api_key_last4 text,
    vision_model text not null,
    text_model text not null,
    updated_by uuid references public.profiles(id) on delete set null,
    updated_at timestamptz not null default now(),
    constraint tenant_ai_settings_provider_openrouter check (provider = 'openrouter'),
    constraint tenant_ai_settings_model_lengths check (
        length(vision_model) between 2 and 255
        and length(text_model) between 2 and 255
    )
);

create index if not exists idx_tenant_ai_settings_updated_by
    on public.tenant_ai_settings (updated_by);

alter table public.tenant_ai_settings enable row level security;

create or replace function public.set_tenant_ai_settings_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop policy if exists admin_manage_own_tenant_ai_settings on public.tenant_ai_settings;
create policy admin_manage_own_tenant_ai_settings
on public.tenant_ai_settings
for all
using (
    exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role = 'admin'
          and profiles.status = 'Active'
          and profiles.tenant_id = tenant_ai_settings.tenant_id
    )
)
with check (
    exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role = 'admin'
          and profiles.status = 'Active'
          and profiles.tenant_id = tenant_ai_settings.tenant_id
    )
);

drop trigger if exists set_tenant_ai_settings_updated_at on public.tenant_ai_settings;
create trigger set_tenant_ai_settings_updated_at
before update on public.tenant_ai_settings
for each row
execute function public.set_tenant_ai_settings_updated_at();
