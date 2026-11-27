-- Phase 5.3.2: institutional authorization foundations ONLY.
-- Run once as project database owner in Supabase SQL Editor.
-- Existing tables, functions, policies, grants and storage remain unchanged.
-- Only self-lookup is exposed to authenticated callers. No mutation RPCs yet.
-- Account-wide status is NOT enforced by existing routes until later integration.
-- Administrative mutation concurrency and audit attribution require later review.
BEGIN;

-- 1. Catalogues --------------------------------------------------------------
CREATE TABLE public.institutional_actors (
    key                 TEXT PRIMARY KEY CHECK (key ~ '^[a-z_]+$'),
    label               TEXT NOT NULL,
    accepts_memberships BOOLEAN NOT NULL DEFAULT FALSE
);
INSERT INTO public.institutional_actors (key, label, accepts_memberships) VALUES
 ('innovation_center', 'Innovation Center', TRUE),
 ('industry_liaison',  'Industry Liaison',  TRUE),
 ('management',        'Management',        TRUE),
 ('industry_partner',  'Industry Partner',  FALSE);

CREATE TABLE public.institutional_permissions (
    key         TEXT PRIMARY KEY CHECK (key ~ '^[a-z_]+(\.[a-z_]+)+$'),
    actor_key   TEXT NOT NULL REFERENCES public.institutional_actors(key),
    description TEXT NOT NULL,
    head_only   BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT institutional_permissions_actor_prefix CHECK (split_part(key, '.', 1) = actor_key),
    CONSTRAINT institutional_permissions_key_actor UNIQUE (key, actor_key)
);
INSERT INTO public.institutional_permissions (key, actor_key, description, head_only) VALUES
 ('innovation_center.inventions.view',             'innovation_center', 'View submitted inventions.', FALSE),
 ('innovation_center.profiles.review',             'innovation_center', 'Review invention profiles against evidence.', FALSE),
 ('innovation_center.profiles.request_correction', 'innovation_center', 'Ask the innovator to correct a profile.', FALSE),
 ('innovation_center.profiles.approve',            'innovation_center', 'Final institutional verification of a profile.', TRUE),
 ('innovation_center.profiles.reject',             'innovation_center', 'Reject an invention profile.', TRUE),
 ('innovation_center.portfolio.view',              'innovation_center', 'View the invention portfolio.', FALSE),
 ('innovation_center.matches.view',                'innovation_center', 'View partner matches.', FALSE),
 ('innovation_center.matches.review',              'innovation_center', 'Review partner matches.', FALSE),
 ('innovation_center.matches.approve',             'innovation_center', 'Approve matches for Industry Liaison.', TRUE),
 ('innovation_center.employees.view',              'innovation_center', 'View Innovation Center staff.', TRUE),
 ('innovation_center.reports.view',                'innovation_center', 'View Innovation Center reports.', FALSE),
 ('industry_liaison.matches.view',                 'industry_liaison',  'View approved partner matches.', FALSE),
 ('industry_liaison.partners.view',                'industry_liaison',  'View partners and public business contacts.', FALSE),
 ('industry_liaison.outreach.draft',               'industry_liaison',  'Draft outreach messages.', FALSE),
 ('industry_liaison.outreach.review',              'industry_liaison',  'Review outreach drafts.', FALSE),
 ('industry_liaison.outreach.approve',             'industry_liaison',  'Approve outreach before sending.', TRUE),
 ('industry_liaison.outreach.send',                'industry_liaison',  'Send approved outreach externally.', TRUE),
 ('industry_liaison.engagement.view',              'industry_liaison',  'View engagement timelines.', FALSE),
 ('industry_liaison.engagement.update',            'industry_liaison',  'Record engagement events.', FALSE),
 ('industry_liaison.employees.view',               'industry_liaison',  'View Industry Liaison staff.', TRUE),
 ('industry_liaison.reports.view',                 'industry_liaison',  'View Industry Liaison reports.', FALSE),
 ('management.overview.view',                      'management',        'View the management overview and KPIs.', FALSE),
 ('management.portfolio.view',                     'management',        'View the portfolio summary.', FALSE),
 ('management.analytics.view',                     'management',        'View trends and analytics.', FALSE),
 ('management.reports.view',                       'management',        'View management reports.', FALSE),
 ('management.reports.export',                     'management',        'Export management reports.', TRUE),
 ('management.performance.view',                   'management',        'View staff and unit performance.', TRUE),
 ('management.employees.view',                     'management',        'View Management staff.', TRUE);

-- 2. Application-wide account status (no row = active) ------------------------
CREATE TABLE public.user_account_status (
    user_id    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'banned')),
    reason     TEXT CHECK (char_length(reason) <= 1000),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by UUID,
    CONSTRAINT user_account_status_not_self CHECK (changed_by IS NULL OR changed_by <> user_id)
);
CREATE INDEX user_account_status_restricted_idx ON public.user_account_status (status) WHERE status <> 'active';
CREATE INDEX user_account_status_changed_by_idx ON public.user_account_status (changed_by);

-- 3. Memberships (one per user and actor) --------------------------------------
CREATE TABLE public.institutional_memberships (
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    actor_key     TEXT NOT NULL REFERENCES public.institutional_actors(key),
    position      TEXT NOT NULL CHECK (position IN ('head', 'employee')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
    status_reason TEXT CHECK (char_length(status_reason) <= 1000),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    UUID,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    UUID,
    PRIMARY KEY (user_id, actor_key),
    CONSTRAINT institutional_memberships_not_self_created CHECK (created_by IS NULL OR created_by <> user_id),
    CONSTRAINT institutional_memberships_not_self_updated CHECK (updated_by IS NULL OR updated_by <> user_id)
);
CREATE INDEX institutional_memberships_actor_idx      ON public.institutional_memberships (actor_key, position, status);
CREATE INDEX institutional_memberships_created_by_idx ON public.institutional_memberships (created_by);
CREATE INDEX institutional_memberships_updated_by_idx ON public.institutional_memberships (updated_by);

-- 4. Employee permission grants (same-actor only, enforced by composite FKs) ---
CREATE TABLE public.institutional_permission_grants (
    user_id        UUID NOT NULL,
    actor_key      TEXT NOT NULL,
    permission_key TEXT NOT NULL,
    granted_by     UUID,
    granted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, permission_key),
    FOREIGN KEY (user_id, actor_key)
        REFERENCES public.institutional_memberships (user_id, actor_key) ON DELETE CASCADE,
    FOREIGN KEY (permission_key, actor_key)
        REFERENCES public.institutional_permissions (key, actor_key) ON DELETE RESTRICT,
    CONSTRAINT institutional_permission_grants_not_self CHECK (granted_by IS NULL OR granted_by <> user_id)
);
CREATE INDEX institutional_permission_grants_membership_idx ON public.institutional_permission_grants (user_id, actor_key);
CREATE INDEX institutional_permission_grants_permission_idx ON public.institutional_permission_grants (permission_key, actor_key);
CREATE INDEX institutional_permission_grants_granted_by_idx ON public.institutional_permission_grants (granted_by);

-- 5. Append-only audit log (no FK to auth.users: history survives deletion) ----
CREATE TABLE public.audit_logs (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id  UUID,
    actor_role     TEXT CHECK (char_length(actor_role) <= 50),
    action         TEXT NOT NULL CHECK (char_length(action) <= 100),
    entity_type    TEXT NOT NULL CHECK (char_length(entity_type) <= 100),
    entity_id      TEXT,
    target_user_id UUID,
    result         TEXT NOT NULL DEFAULT 'succeeded' CHECK (result IN ('succeeded', 'failed', 'denied')),
    details        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_logs_occurred_idx ON public.audit_logs (occurred_at DESC);
CREATE INDEX audit_logs_target_idx   ON public.audit_logs (target_user_id, occurred_at DESC);
CREATE INDEX audit_logs_actor_idx    ON public.audit_logs (actor_user_id, occurred_at DESC);
CREATE INDEX audit_logs_action_idx   ON public.audit_logs (action, occurred_at DESC);

-- 6. Helper: active Administrator AND not restricted application-wide ----------
CREATE FUNCTION public.is_active_administrator(p_user UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT p_user IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.admin_accounts a
                   WHERE a.user_id = p_user AND a.role = 'administrator' AND a.status = 'active')
       AND NOT EXISTS (SELECT 1 FROM public.user_account_status s
                       WHERE s.user_id = p_user AND s.status <> 'active');
$$;

-- 7. Integrity triggers ----------------------------------------------------------
CREATE FUNCTION public.institutional_memberships_guard()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    acting UUID;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.user_id <> OLD.user_id OR NEW.actor_key <> OLD.actor_key) THEN
        RAISE EXCEPTION 'Membership user and actor cannot be changed' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.institutional_actors x
                   WHERE x.key = NEW.actor_key AND x.accepts_memberships) THEN
        RAISE EXCEPTION 'Actor % does not accept memberships', NEW.actor_key USING ERRCODE = '23514';
    END IF;
    acting := CASE WHEN TG_OP = 'INSERT' THEN NEW.created_by ELSE NEW.updated_by END;
    IF NOT public.is_active_administrator(acting) THEN
        RAISE EXCEPTION 'Only an active Administrator can change institutional memberships'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER institutional_memberships_guard
BEFORE INSERT OR UPDATE ON public.institutional_memberships
FOR EACH ROW EXECUTE FUNCTION public.institutional_memberships_guard();

-- A promoted Head receives the actor's permissions automatically: clear grants.
CREATE FUNCTION public.institutional_memberships_clear_grants()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    DELETE FROM public.institutional_permission_grants g
    WHERE g.user_id = NEW.user_id AND g.actor_key = NEW.actor_key;
    RETURN NULL;
END;
$$;
CREATE TRIGGER institutional_memberships_clear_grants
AFTER UPDATE OF position ON public.institutional_memberships
FOR EACH ROW WHEN (NEW.position = 'head' AND OLD.position <> 'head')
EXECUTE FUNCTION public.institutional_memberships_clear_grants();

CREATE FUNCTION public.institutional_permission_grants_guard()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.institutional_memberships m
                   WHERE m.user_id = NEW.user_id AND m.actor_key = NEW.actor_key
                     AND m.position = 'employee') THEN
        RAISE EXCEPTION 'Permissions are assigned to Employees only; Heads receive them automatically'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.institutional_permissions p
               WHERE p.key = NEW.permission_key AND p.head_only) THEN
        RAISE EXCEPTION 'Permission % is reserved for Heads', NEW.permission_key USING ERRCODE = '23514';
    END IF;
    IF NOT public.is_active_administrator(NEW.granted_by) THEN
        RAISE EXCEPTION 'Only an active Administrator can grant permissions' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER institutional_permission_grants_guard
BEFORE INSERT OR UPDATE ON public.institutional_permission_grants
FOR EACH ROW EXECUTE FUNCTION public.institutional_permission_grants_guard();

CREATE FUNCTION public.institutional_permissions_clear_reserved()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    DELETE FROM public.institutional_permission_grants g WHERE g.permission_key = NEW.key;
    RETURN NULL;
END;
$$;
CREATE TRIGGER institutional_permissions_clear_reserved
AFTER UPDATE OF head_only ON public.institutional_permissions
FOR EACH ROW WHEN (NEW.head_only AND NOT OLD.head_only)
EXECUTE FUNCTION public.institutional_permissions_clear_reserved();

-- Only Administrators restrict accounts; the last unrestricted active
-- Administrator can never be suspended or banned.
CREATE FUNCTION public.user_account_status_guard()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF NOT public.is_active_administrator(NEW.changed_by) THEN
        RAISE EXCEPTION 'Only an active Administrator can change account status' USING ERRCODE = '42501';
    END IF;
    IF NEW.status <> 'active'
       AND EXISTS (SELECT 1 FROM public.admin_accounts a
                   WHERE a.user_id = NEW.user_id AND a.role = 'administrator' AND a.status = 'active')
       AND NOT EXISTS (SELECT 1 FROM public.admin_accounts a
                       WHERE a.user_id <> NEW.user_id AND public.is_active_administrator(a.user_id)) THEN
        RAISE EXCEPTION 'The last active Administrator cannot be suspended or banned'
            USING ERRCODE = '23514';
    END IF;
    NEW.changed_at := NOW();
    RETURN NEW;
END;
$$;
CREATE TRIGGER user_account_status_guard
BEFORE INSERT OR UPDATE ON public.user_account_status
FOR EACH ROW EXECUTE FUNCTION public.user_account_status_guard();

-- 8. Automatic audit of every access change -----------------------------------
CREATE FUNCTION public.audit_access_change()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    new_row JSONB := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) END;
    old_row JSONB := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) END;
    row_any JSONB := COALESCE(new_row, old_row);
    acting  UUID;
BEGIN
    acting := auth.uid();
    -- SQL Editor / database maintenance without a caller JWT is recorded as system.
    -- Do not misattribute deletion to the original grantor or creator.
    INSERT INTO public.audit_logs (actor_user_id, actor_role, action, entity_type, entity_id,
                                   target_user_id, details)
    VALUES (acting,
            CASE WHEN public.is_active_administrator(acting) THEN 'administrator' ELSE 'system' END,
            TG_TABLE_NAME || '.' || lower(TG_OP),
            TG_TABLE_NAME,
            COALESCE(row_any ->> 'permission_key', row_any ->> 'actor_key', row_any ->> 'status'),
            NULLIF(row_any ->> 'user_id', '')::uuid,
            jsonb_build_object('old', old_row, 'new', new_row));
    RETURN NULL;
END;
$$;
CREATE TRIGGER audit_institutional_memberships
AFTER INSERT OR UPDATE OR DELETE ON public.institutional_memberships
FOR EACH ROW EXECUTE FUNCTION public.audit_access_change();
CREATE TRIGGER audit_institutional_permission_grants
AFTER INSERT OR UPDATE OR DELETE ON public.institutional_permission_grants
FOR EACH ROW EXECUTE FUNCTION public.audit_access_change();
CREATE TRIGGER audit_user_account_status
AFTER INSERT OR UPDATE OR DELETE ON public.user_account_status
FOR EACH ROW EXECUTE FUNCTION public.audit_access_change();

CREATE FUNCTION public.audit_logs_append_only()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'Audit records cannot be changed or deleted' USING ERRCODE = '42501';
END;
$$;
CREATE TRIGGER audit_logs_no_update_delete
BEFORE UPDATE OR DELETE ON public.audit_logs
FOR EACH ROW EXECUTE FUNCTION public.audit_logs_append_only();
CREATE TRIGGER audit_logs_no_truncate
BEFORE TRUNCATE ON public.audit_logs
FOR EACH STATEMENT EXECUTE FUNCTION public.audit_logs_append_only();

-- 9. Row Level Security (no policies = no access for anon/authenticated) -------
ALTER TABLE public.institutional_actors            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.institutional_permissions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.institutional_memberships       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.institutional_permission_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_account_status             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs                      ENABLE ROW LEVEL SECURITY;

-- 10. Explicit grants -----------------------------------------------------------
REVOKE ALL ON TABLE public.institutional_actors, public.institutional_permissions,
                    public.institutional_memberships, public.institutional_permission_grants,
                    public.user_account_status, public.audit_logs
    FROM PUBLIC, anon, authenticated, service_role;
-- No direct API-role table access is required for this read-only phase.
REVOKE ALL ON SEQUENCE public.audit_logs_id_seq FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.is_active_administrator(UUID),
                       public.institutional_memberships_guard(),
                       public.institutional_memberships_clear_grants(),
                       public.institutional_permission_grants_guard(),
                       public.institutional_permissions_clear_reserved(),
                       public.user_account_status_guard(),
                       public.audit_access_change(),
                       public.audit_logs_append_only()
    FROM PUBLIC, anon, authenticated, service_role;

-- 11. Self-lookup: ONLY the caller's own record; always an object -------------
CREATE FUNCTION public.institutional_get_my_access()
RETURNS JSONB LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT jsonb_build_object(
        'user_id', me.uid,
        'account_status', (SELECT s.status FROM public.user_account_status s WHERE s.user_id = me.uid),
        'memberships', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'actor', m.actor_key, 'position', m.position, 'status', m.status,
                       'permissions', COALESCE((
                           SELECT jsonb_agg(g.permission_key ORDER BY g.permission_key)
                           FROM public.institutional_permission_grants g
                           JOIN public.institutional_permissions p
                             ON p.key = g.permission_key AND p.actor_key = g.actor_key
                           WHERE g.user_id = m.user_id AND g.actor_key = m.actor_key
                             AND NOT p.head_only AND m.position = 'employee'), '[]'::jsonb))
                   ORDER BY m.actor_key)
            FROM public.institutional_memberships m WHERE m.user_id = me.uid), '[]'::jsonb))
    FROM (SELECT auth.uid() AS uid) me
    WHERE me.uid IS NOT NULL;
$$;
REVOKE ALL ON FUNCTION public.institutional_get_my_access() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.institutional_get_my_access() TO authenticated;


-- Mutation RPCs intentionally deferred to the User Management phase.
COMMIT;
