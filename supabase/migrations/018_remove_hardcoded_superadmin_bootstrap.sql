-- Migration 018: Remove hardcoded superadmin bootstrap from handle_new_user trigger
-- Ensures superadmin role cannot be claimed via registration and requires operator seeding

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
DECLARE
    v_tenant_id uuid;
    v_role text;
    v_org text;
    v_status text;
BEGIN
    -- Check if role metadata is specified
    v_role := coalesce(new.raw_user_meta_data->>'role', 'employee');
    v_org := coalesce(new.raw_user_meta_data->>'organisation', '');
    v_status := 'Active'; -- Employees default to Active once invited
    
    -- If it's an employee registering, look up their invitation details
    IF v_role = 'employee' THEN
        SELECT tenant_id INTO v_tenant_id FROM public.employee_invitations 
        WHERE LOWER(email) = LOWER(new.email) AND status = 'Pending Activation' LIMIT 1;
        
        -- Get organization from the inviting admin's profile
        IF v_tenant_id IS NOT NULL THEN
            SELECT organisation INTO v_org FROM public.profiles WHERE id = v_tenant_id;
        END IF;
    END IF;
    
    -- If no invite was found, they are self-registering a workspace as an Admin
    -- All self-registrations default to 'Pending Approval' for security
    IF v_tenant_id IS NULL THEN
        v_tenant_id := new.id;
        v_role := 'admin';
        v_status := 'Pending Approval';
    END IF;

    INSERT INTO public.profiles (id, full_name, organisation, role, tenant_id, status)
    VALUES (
        new.id,
        coalesce(new.raw_user_meta_data->>'full_name', ''),
        v_org,
        v_role,
        v_tenant_id,
        v_status
    )
    ON CONFLICT (id) DO UPDATE SET
        full_name = EXCLUDED.full_name,
        organisation = EXCLUDED.organisation;

    INSERT INTO public.email_sync_settings (user_id)
    VALUES (new.id)
    ON CONFLICT (user_id) DO NOTHING;

    -- Update invitation status to Active if this was an invite registration
    IF v_role = 'employee' THEN
        UPDATE public.employee_invitations 
        SET status = 'Active' 
        WHERE LOWER(email) = LOWER(new.email);
    END IF;

    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
