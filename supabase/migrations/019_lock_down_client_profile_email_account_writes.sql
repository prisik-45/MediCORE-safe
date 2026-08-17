-- Migration 019: Restrict direct client writes to trusted auth/profile and mailbox connection tables.
-- Backend service-role APIs remain responsible for role/status/tenant changes and IMAP validation.

-- Profiles: authenticated users may update only their display name directly.
-- Trusted authorization fields such as role, status, tenant_id, and organisation must not be mutable
-- through Supabase client credentials.
REVOKE UPDATE ON TABLE public.profiles FROM anon, authenticated;
GRANT UPDATE (full_name) ON TABLE public.profiles TO authenticated;

DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
CREATE POLICY "Users can update own profile"
    ON public.profiles
    FOR UPDATE TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- Email accounts: direct client writes bypass backend IMAP host/port validation.
-- The frontend uses backend /api/email-accounts endpoints, so direct Supabase writes are disabled.
REVOKE INSERT, UPDATE, DELETE ON TABLE public.email_accounts FROM anon, authenticated;

DROP POLICY IF EXISTS "Users can manage own email accounts" ON public.email_accounts;
CREATE POLICY "Users can view own email accounts"
    ON public.email_accounts
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);
