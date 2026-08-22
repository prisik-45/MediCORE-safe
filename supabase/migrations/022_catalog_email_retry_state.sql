alter table public.catalog_emails
  add column if not exists retry_count integer not null default 0,
  add column if not exists last_attempt_at timestamptz;

create index if not exists idx_catalog_emails_retry_status
  on public.catalog_emails (tenant_id, processing_status, retry_count, last_attempt_at);
