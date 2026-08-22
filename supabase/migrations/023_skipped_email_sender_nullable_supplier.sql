alter table public.catalog_emails
  alter column supplier_id drop not null,
  add column if not exists sender_address text;

update public.catalog_emails ce
set sender_address = s.email_domain
from public.suppliers s
where ce.sender_address is null
  and ce.supplier_id = s.id
  and ce.processing_status not in ('completed', 'partial', 'certificate');
