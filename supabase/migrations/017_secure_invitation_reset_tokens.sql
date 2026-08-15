-- Migration 017: tenant-scope invite/reset RLS and store reset tokens as hashes.

create extension if not exists pgcrypto;

-- Hash any existing plaintext tokens in place. New application code stores the
-- SHA-256 hex digest directly in these columns.
update public.employee_invitations
set token = encode(digest(token, 'sha256'), 'hex')
where token !~ '^[0-9a-f]{64}$';

update public.password_resets
set token = encode(digest(token, 'sha256'), 'hex')
where token !~ '^[0-9a-f]{64}$';

drop policy if exists admin_manage_invitations on public.employee_invitations;
create policy admin_manage_invitations on public.employee_invitations
    for all to authenticated
    using (
        exists (
            select 1
            from public.profiles
            where profiles.id = auth.uid()
              and profiles.role = 'admin'
              and profiles.tenant_id = employee_invitations.tenant_id
              and profiles.status = 'Active'
        )
    )
    with check (
        exists (
            select 1
            from public.profiles
            where profiles.id = auth.uid()
              and profiles.role = 'admin'
              and profiles.tenant_id = employee_invitations.tenant_id
              and profiles.status = 'Active'
        )
    );

drop policy if exists manage_password_resets on public.password_resets;
create policy manage_password_resets on public.password_resets
    for all to authenticated
    using (
        user_id = auth.uid()
        or exists (
            select 1
            from public.profiles admin_profile
            join public.profiles target_profile
              on target_profile.id = password_resets.user_id
            where admin_profile.id = auth.uid()
              and admin_profile.role = 'admin'
              and admin_profile.status = 'Active'
              and target_profile.tenant_id = admin_profile.tenant_id
        )
    )
    with check (
        user_id = auth.uid()
        or exists (
            select 1
            from public.profiles admin_profile
            join public.profiles target_profile
              on target_profile.id = password_resets.user_id
            where admin_profile.id = auth.uid()
              and admin_profile.role = 'admin'
              and admin_profile.status = 'Active'
              and target_profile.tenant_id = admin_profile.tenant_id
        )
    );
