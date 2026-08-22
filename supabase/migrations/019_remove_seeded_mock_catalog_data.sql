delete from public.catalog_items
where raw_payload ->> 'source' = 'mock_extracted_catalogue'
   or catalog_email_id in (
        select id
        from public.catalog_emails
        where raw_email_id like 'core-mock-catalog-%'
   );

delete from public.catalog_emails
where raw_email_id like 'core-mock-catalog-%';

delete from public.suppliers s
where s.email_domain like '%.example'
  and not exists (
      select 1
      from public.catalog_emails ce
      where ce.supplier_id = s.id
  )
  and not exists (
      select 1
      from public.catalog_items ci
      where ci.supplier_id = s.id
  );
