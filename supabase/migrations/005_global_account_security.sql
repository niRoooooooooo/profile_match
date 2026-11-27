-- Profile Match | Phase 5.4.3B — database access restrictions
-- Reviewed against the supplied live RLS, grants, functions and bucket inventory.
-- Execute once in the Supabase SQL Editor as the database owner, after review.
-- No account status, invention, profile, storage object or auth records are changed.
-- Does not complete FastAPI service-role protection; that is a separate code change.

BEGIN;
SET LOCAL lock_timeout = '5s';

-- Fail before changes if the deployed schema is different or a restricted account
-- already exists. The latter requires a coordinated API/database rollout review.
DO $preflight$
DECLARE
    target record;
BEGIN
    FOR target IN SELECT * FROM (VALUES
        ('public', 'inventions'),
        ('public', 'invention_documents'),
        ('public', 'invention_profile_drafts'),
        ('public', 'invention_profiles'),
        ('public', 'user_profiles'),
        ('public', 'user_account_status'),
        ('storage', 'objects')
    ) AS t(schema_name, table_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = target.schema_name
              AND c.relname = target.table_name
              AND c.relrowsecurity
        ) THEN
            RAISE EXCEPTION 'Missing table or disabled RLS: %.%',
                target.schema_name, target.table_name;
        END IF;
    END LOOP;

    IF (SELECT count(*) FROM storage.buckets
        WHERE id IN ('invention-document', 'invention-profiles')
          AND public IS FALSE) <> 2 THEN
        RAISE EXCEPTION 'Expected both existing private invention buckets';
    END IF;

    IF EXISTS (SELECT 1 FROM public.user_account_status
               WHERE status IS DISTINCT FROM 'active') THEN
        RAISE EXCEPTION 'Restricted accounts already exist; review coordinated rollout before applying';
    END IF;

    IF pg_catalog.to_regprocedure('public.is_account_active()') IS NOT NULL THEN
        RAISE EXCEPTION 'public.is_account_active() already exists; inspect before continuing';
    END IF;

    -- Confirm the reported permissive policies are still present; never replace them.
    FOR target IN SELECT * FROM (VALUES
        ('public','inventions','Create own inventions','INSERT'),
        ('public','inventions','Delete own inventions','DELETE'),
        ('public','inventions','Read own inventions','SELECT'),
        ('public','inventions','Update own inventions','UPDATE'),
        ('public','invention_documents','Add own documents','INSERT'),
        ('public','invention_documents','Read own documents','SELECT'),
        ('public','invention_profile_drafts','Create own invention profile drafts','INSERT'),
        ('public','invention_profile_drafts','Read own invention profile drafts','SELECT'),
        ('public','invention_profile_drafts','Update own invention profile drafts','UPDATE'),
        ('public','invention_profiles','Create own invention profiles','INSERT'),
        ('public','invention_profiles','Read own invention profiles','SELECT'),
        ('public','invention_profiles','Update own invention profiles','UPDATE'),
        ('public','user_profiles','Read own user profile','SELECT'),
        ('storage','objects','Delete own invention files','DELETE'),
        ('storage','objects','Read own invention files','SELECT'),
        ('storage','objects','Upload own invention files','INSERT')
    ) AS t(schema_name, table_name, policy_name, command_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_policies p
            WHERE p.schemaname = target.schema_name
              AND p.tablename = target.table_name
              AND p.policyname = target.policy_name
              AND p.cmd = target.command_name
              AND p.permissive = 'PERMISSIVE'
              AND p.roles = ARRAY['authenticated']::name[]
        ) THEN
            RAISE EXCEPTION 'Expected policy not found: %.% / %',
                target.schema_name, target.table_name, target.policy_name;
        END IF;
    END LOOP;
END;
$preflight$;

-- Self-only status lookup. No user-id argument, no arbitrary user lookup.
-- An authenticated account with no status row is active, by existing design.
-- Unknown/null stored status is restricted. Missing authentication is denied.
-- Fixed search path and row_security=off: if the function owner cannot read the
-- protected status table without RLS, the query errors instead of treating a
-- hidden status record as absent. The owner must be a trusted DB role.
CREATE FUNCTION public.is_account_active()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
SET row_security = off
AS $function$
    SELECT me.uid IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.user_account_status AS s
        WHERE s.user_id = me.uid
          AND s.status IS DISTINCT FROM 'active'
    )
    FROM (SELECT auth.uid() AS uid) AS me;
$function$;

REVOKE ALL ON FUNCTION public.is_account_active() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.is_account_active() TO authenticated;

-- Add restrictions to all existing Innovator tables. These do not grant access.
CREATE POLICY pm_active_account_required ON public.inventions
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((SELECT public.is_account_active()))
    WITH CHECK ((SELECT public.is_account_active()));

CREATE POLICY pm_active_account_required ON public.invention_documents
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((SELECT public.is_account_active()))
    WITH CHECK ((SELECT public.is_account_active()));

CREATE POLICY pm_active_account_required ON public.invention_profile_drafts
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((SELECT public.is_account_active()))
    WITH CHECK ((SELECT public.is_account_active()));

CREATE POLICY pm_active_account_required ON public.invention_profiles
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((SELECT public.is_account_active()))
    WITH CHECK ((SELECT public.is_account_active()));

CREATE POLICY pm_active_account_required ON public.user_profiles
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((SELECT public.is_account_active()))
    WITH CHECK ((SELECT public.is_account_active()));

-- Both actual private buckets; other storage buckets are not affected.
-- Existing storage ownership rules stay intact. No profile-bucket permission
-- is created for authenticated users (server-managed submissions remain so).
CREATE POLICY pm_active_account_invention_storage ON storage.objects
    AS RESTRICTIVE FOR ALL TO authenticated
    USING (
        bucket_id NOT IN ('invention-document', 'invention-profiles')
        OR (SELECT public.is_account_active())
    )
    WITH CHECK (
        bucket_id NOT IN ('invention-document', 'invention-profiles')
        OR (SELECT public.is_account_active())
    );

-- Ordinary browser roles need no DDL-like privileges on these tables.
-- Existing data constraints, triggers and CRUD grants are not altered.
-- Do not revoke service_role privileges or modify system storage grants.
REVOKE TRUNCATE, TRIGGER, REFERENCES ON TABLE
    public.inventions,
    public.invention_documents,
    public.invention_profile_drafts,
    public.invention_profiles,
    public.user_profiles
FROM PUBLIC, anon, authenticated;

-- Transactional postconditions: fail rather than silently leave inherited
-- whole-table privileges, a misconfigured definer, or incomplete restrictions.
DO $verify$
DECLARE
    target text;
    client_role text;
    privilege_name text;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_roles r ON r.oid = p.proowner
        JOIN pg_catalog.pg_class c ON c.oid = 'public.user_account_status'::regclass
        WHERE p.oid = 'public.is_account_active()'::regprocedure
          AND p.prosecdef
          AND (r.rolsuper OR r.rolbypassrls OR
               (p.proowner = c.relowner AND NOT c.relforcerowsecurity))
    ) THEN
        RAISE EXCEPTION 'Status helper owner cannot safely bypass status-table RLS';
    END IF;

    IF NOT pg_catalog.has_function_privilege('authenticated', 'public.is_account_active()', 'EXECUTE')
       OR pg_catalog.has_function_privilege('anon', 'public.is_account_active()', 'EXECUTE') THEN
        RAISE EXCEPTION 'Unexpected status-helper EXECUTE privileges';
    END IF;

    FOREACH target IN ARRAY ARRAY['public.inventions','public.invention_documents',
        'public.invention_profile_drafts','public.invention_profiles','public.user_profiles']
    LOOP
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated']
        LOOP
            FOREACH privilege_name IN ARRAY ARRAY['TRUNCATE','TRIGGER','REFERENCES']
            LOOP
                IF pg_catalog.has_table_privilege(client_role, target, privilege_name) THEN
                    RAISE EXCEPTION 'Unexpected inherited privilege: % / % / %',
                        client_role, target, privilege_name;
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;

    IF (SELECT count(*) FROM pg_catalog.pg_policies
        WHERE permissive = 'RESTRICTIVE' AND cmd = 'ALL'
          AND roles = ARRAY['authenticated']::name[]
          AND ((schemaname = 'public' AND policyname = 'pm_active_account_required'
                AND tablename IN ('inventions','invention_documents','invention_profile_drafts',
                                  'invention_profiles','user_profiles'))
               OR (schemaname = 'storage' AND tablename = 'objects'
                   AND policyname = 'pm_active_account_invention_storage'))) <> 6 THEN
        RAISE EXCEPTION 'Expected six restrictive policies';
    END IF;
END;
$verify$;

COMMIT;

-- Read-only confirmation (expect exactly 6 rows, all RESTRICTIVE / ALL).
SELECT schemaname, tablename, policyname, permissive, roles, cmd
FROM pg_catalog.pg_policies
WHERE (schemaname = 'public' AND policyname = 'pm_active_account_required'
       AND tablename IN ('inventions','invention_documents','invention_profile_drafts',
                         'invention_profiles','user_profiles'))
   OR (schemaname = 'storage' AND tablename = 'objects'
       AND policyname = 'pm_active_account_invention_storage')
ORDER BY schemaname, tablename;
