-- Phase 5.2.2: isolated administrator access schema
-- Run once in the Supabase SQL Editor as the project database owner.
-- No existing tables, grants, functions, or buckets are modified.
-- Phase 5.3 must separately authorize and audit every account mutation.
BEGIN;

CREATE TABLE public.admin_permissions (
    key text PRIMARY KEY CHECK (key ~ '^[a-z]+(\.[a-z_]+)+$'),
    description text NOT NULL,
    administrator_only boolean NOT NULL DEFAULT false
);

INSERT INTO public.admin_permissions (key, description, administrator_only) VALUES
    ('organizations.view', 'View organizations and approved profiles.', FALSE),
    ('organizations.create', 'Register new organizations.', FALSE),
    ('organizations.edit', 'Edit organization registration details.', FALSE),
    ('organizations.archive', 'Archive and restore organizations.', FALSE),
    ('organizations.documents.upload', 'Upload organization supporting documents.', FALSE),
    ('organizations.documents.view', 'View organization supporting documents.', FALSE),
    ('organizations.profiles.generate', 'Request AI-generated profile drafts.', FALSE),
    ('organizations.profiles.edit', 'Edit profile drafts before review.', FALSE),
    ('organizations.profiles.approve', 'Approve a draft as the official profile.', TRUE),
    ('organizations.profiles.reject', 'Reject an organization profile draft.', TRUE),
    ('agents.collection.execute', 'Run the Data Collection Agent on demand.', FALSE),
    ('agents.collection.schedule', 'Configure automatic collection schedules.', FALSE),
    ('agents.collection.history', 'View collection runs and errors.', FALSE),
    ('sources.view', 'View the data source registry.', FALSE),
    ('sources.manage', 'Manage data sources.', FALSE),
    ('users.view', 'View user accounts.', FALSE),
    ('users.edit', 'Edit user account details.', TRUE),
    ('users.suspend', 'Suspend user accounts.', TRUE),
    ('users.ban', 'Ban user accounts.', TRUE),
    ('users.restore', 'Restore suspended or banned accounts.', TRUE),
    ('users.delete', 'Delete user accounts.', TRUE),
    ('roles.manage', 'Assign and remove administrative roles.', TRUE),
    ('permissions.manage', 'Assign and remove Admin Employee permissions.', TRUE),
    ('audit.view', 'View administrative audit logs.', FALSE);

CREATE TABLE public.admin_accounts (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('administrator', 'admin_employee')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'banned')),
    status_reason text CHECK (char_length(status_reason) <= 1000),
    status_changed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    CONSTRAINT admin_accounts_not_self_created CHECK (created_by IS NULL OR created_by <> user_id),
    CONSTRAINT admin_accounts_not_self_updated CHECK (updated_by IS NULL OR updated_by <> user_id)
);

CREATE INDEX admin_accounts_role_status_idx ON public.admin_accounts (role, status);
CREATE INDEX admin_accounts_created_by_idx ON public.admin_accounts (created_by);
CREATE INDEX admin_accounts_updated_by_idx ON public.admin_accounts (updated_by);

CREATE TABLE public.admin_permission_grants (
    user_id uuid NOT NULL REFERENCES public.admin_accounts(user_id) ON DELETE CASCADE,
    permission_key text NOT NULL REFERENCES public.admin_permissions(key) ON UPDATE CASCADE ON DELETE RESTRICT,
    granted_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission_key),
    CONSTRAINT admin_permission_grants_not_self_granted CHECK (granted_by IS NULL OR granted_by <> user_id)
);

CREATE INDEX admin_permission_grants_permission_idx ON public.admin_permission_grants (permission_key);
CREATE INDEX admin_permission_grants_granted_by_idx ON public.admin_permission_grants (granted_by);

-- Integrity guard for owner-managed accounts. This is not an actor-authentication
-- mechanism. Future mutation endpoints must bind actors to verified identities
-- and serialize last-administrator checks across concurrent changes.
CREATE FUNCTION public.admin_accounts_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    actor uuid;
    removes_active_admin boolean := false;
BEGIN
    IF TG_OP = 'INSERT' THEN
        actor := NEW.created_by;
    ELSIF TG_OP = 'UPDATE' THEN
        actor := NEW.updated_by;
        NEW.updated_at := now();
        IF OLD.status IS DISTINCT FROM NEW.status THEN
            NEW.status_changed_at := now();
        END IF;
        removes_active_admin := OLD.role = 'administrator' AND OLD.status = 'active'
            AND (NEW.role <> 'administrator' OR NEW.status <> 'active');
        IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
            RAISE EXCEPTION 'Administrative account identity cannot be changed';
        END IF;
    ELSE
        removes_active_admin := OLD.role = 'administrator' AND OLD.status = 'active';
    END IF;

    IF actor IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.admin_accounts a
        WHERE a.user_id = actor AND a.role = 'administrator' AND a.status = 'active'
    ) THEN
        RAISE EXCEPTION 'Recorded actor must be an active Administrator' USING ERRCODE = '42501';
    END IF;

    IF removes_active_admin THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.admin_accounts a
            WHERE a.user_id <> OLD.user_id AND a.role = 'administrator' AND a.status = 'active'
        ) THEN
            RAISE EXCEPTION 'The last active Administrator cannot be removed or restricted' USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER admin_accounts_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.admin_accounts
FOR EACH ROW EXECUTE FUNCTION public.admin_accounts_guard();

CREATE FUNCTION public.admin_permission_grants_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.admin_accounts a
        WHERE a.user_id = NEW.user_id AND a.role = 'admin_employee'
    ) THEN
        RAISE EXCEPTION 'Permissions can only be assigned to Admin Employee accounts' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.admin_permissions p
        WHERE p.key = NEW.permission_key AND p.administrator_only
    ) THEN
        RAISE EXCEPTION 'Permission % is reserved for Administrators', NEW.permission_key USING ERRCODE = '23514';
    END IF;
    IF NEW.granted_by IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.admin_accounts a
        WHERE a.user_id = NEW.granted_by AND a.role = 'administrator' AND a.status = 'active'
    ) THEN
        RAISE EXCEPTION 'Recorded grantor must be an active Administrator' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER admin_permission_grants_guard
BEFORE INSERT OR UPDATE ON public.admin_permission_grants
FOR EACH ROW EXECUTE FUNCTION public.admin_permission_grants_guard();

CREATE FUNCTION public.admin_accounts_clear_grants()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.role <> 'admin_employee' THEN
        DELETE FROM public.admin_permission_grants WHERE user_id = NEW.user_id;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER admin_accounts_clear_grants
AFTER UPDATE OF role ON public.admin_accounts
FOR EACH ROW WHEN (OLD.role IS DISTINCT FROM NEW.role)
EXECUTE FUNCTION public.admin_accounts_clear_grants();

CREATE FUNCTION public.admin_permissions_clear_reserved()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    DELETE FROM public.admin_permission_grants WHERE permission_key = NEW.key;
    RETURN NULL;
END;
$$;

CREATE TRIGGER admin_permissions_clear_reserved
AFTER UPDATE OF administrator_only ON public.admin_permissions
FOR EACH ROW WHEN (NEW.administrator_only AND NOT OLD.administrator_only)
EXECUTE FUNCTION public.admin_permissions_clear_reserved();

ALTER TABLE public.admin_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_permission_grants ENABLE ROW LEVEL SECURITY;

-- No direct API access, including service_role, is needed in Phase 5.2.
REVOKE ALL ON TABLE public.admin_permissions, public.admin_accounts,
    public.admin_permission_grants FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.admin_accounts_guard(),
    public.admin_permission_grants_guard(), public.admin_accounts_clear_grants(),
    public.admin_permissions_clear_reserved() FROM PUBLIC, anon, authenticated, service_role;

-- Exact RPC contract used by Claude's authorization service.
CREATE FUNCTION public.admin_get_my_access()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT jsonb_build_object(
        'user_id', a.user_id,
        'role', a.role,
        'status', a.status,
        'permissions', COALESCE((
            SELECT jsonb_agg(g.permission_key ORDER BY g.permission_key)
            FROM public.admin_permission_grants g
            JOIN public.admin_permissions p ON p.key = g.permission_key
            WHERE g.user_id = a.user_id AND NOT p.administrator_only
        ), '[]'::jsonb)
    )
    FROM public.admin_accounts a
    WHERE a.user_id = (SELECT auth.uid());
$$;

REVOKE ALL ON FUNCTION public.admin_get_my_access() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.admin_get_my_access() TO authenticated;

COMMIT;
