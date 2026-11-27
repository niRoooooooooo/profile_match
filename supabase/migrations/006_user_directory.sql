-- =============================================================================
-- 006_user_directory.sql                      (Phase 5.5.1 — DRAFT, NOT APPLIED)
-- =============================================================================
-- Read-only user directory for User and Employee Management.
--
-- Creates ONLY:
--   public.admin_caller_has_permission(text)   internal helper (no client access)
--   public.admin_list_users(...)               paginated directory  -> jsonb
--   public.admin_get_user_details(uuid)        single user details  -> jsonb
-- Changes NO existing table, trigger, function, RLS policy, storage policy,
-- grant on existing objects, or record. No mutation of any kind.
--
-- Authorization (inside every function; nothing from the caller is trusted):
--   caller = auth.uid(); the caller must hold users.view:
--     active Administrator (role administrator, status active), or
--     active Admin Employee with an explicit users.view grant,
--   AND the caller's application account must not be restricted.
--   Restriction reasons are returned only to full active Administrators
--   (public.is_active_administrator(auth.uid())).
--
-- Applying (owner, Supabase SQL Editor, after review):
--   SET profile_match.migration_006_reviewed = 'yes';   -- same session
--   then run this file. The preflight refuses to run without it.
-- Verified live state this draft is written against (Phase 5.5.1 inspection):
--   14 public tables, 18 public functions, 18 triggers (all enabled),
--   24 administrative / 28 institutional permission keys, migrations 003-005.
-- =============================================================================

BEGIN;
SET LOCAL lock_timeout = '5s';

-- -----------------------------------------------------------------------------
-- 1. Preflight
-- -----------------------------------------------------------------------------
DO $preflight$
DECLARE
    missing text;
BEGIN
    IF coalesce(current_setting('profile_match.migration_006_reviewed', true), '') <> 'yes' THEN
        RAISE EXCEPTION 'Migration 006 not reviewed: SET profile_match.migration_006_reviewed = ''yes'' first';
    END IF;

    -- Columns read by this migration (verified live in Phase 5.5.1).
    SELECT string_agg(c.sch || '.' || c.tbl || '.' || c.col, ', ') INTO missing
    FROM (VALUES
        ('auth', 'users', 'id'), ('auth', 'users', 'email'),
        ('auth', 'users', 'created_at'), ('auth', 'users', 'last_sign_in_at'),
        ('public', 'user_profiles', 'id'), ('public', 'user_profiles', 'full_name'),
        ('public', 'user_profiles', 'department'),
        ('public', 'inventions', 'owner_id'),
        ('public', 'admin_accounts', 'user_id'), ('public', 'admin_accounts', 'role'),
        ('public', 'admin_accounts', 'status'), ('public', 'admin_accounts', 'status_reason'),
        ('public', 'admin_accounts', 'status_changed_at'),
        ('public', 'admin_accounts', 'created_at'), ('public', 'admin_accounts', 'updated_at'),
        ('public', 'admin_permissions', 'key'), ('public', 'admin_permissions', 'administrator_only'),
        ('public', 'admin_permission_grants', 'user_id'),
        ('public', 'admin_permission_grants', 'permission_key'),
        ('public', 'institutional_actors', 'key'), ('public', 'institutional_actors', 'label'),
        ('public', 'institutional_memberships', 'user_id'),
        ('public', 'institutional_memberships', 'actor_key'),
        ('public', 'institutional_memberships', 'position'),
        ('public', 'institutional_memberships', 'status'),
        ('public', 'institutional_memberships', 'status_reason'),
        ('public', 'institutional_memberships', 'created_at'),
        ('public', 'institutional_memberships', 'updated_at'),
        ('public', 'institutional_permission_grants', 'user_id'),
        ('public', 'institutional_permission_grants', 'actor_key'),
        ('public', 'institutional_permission_grants', 'permission_key'),
        ('public', 'user_account_status', 'user_id'), ('public', 'user_account_status', 'status'),
        ('public', 'user_account_status', 'reason'), ('public', 'user_account_status', 'changed_at'),
        ('public', 'user_account_status', 'changed_by')
    ) AS c(sch, tbl, col)
    WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns i
                      WHERE i.table_schema = c.sch AND i.table_name = c.tbl AND i.column_name = c.col);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'Missing columns: %', missing;
    END IF;

    IF (SELECT count(*) FROM public.admin_permissions) <> 24
       OR NOT EXISTS (SELECT 1 FROM public.admin_permissions
                      WHERE key = 'users.view' AND administrator_only IS FALSE) THEN
        RAISE EXCEPTION 'Unexpected administrative permission catalogue';
    END IF;

    IF pg_catalog.to_regprocedure('public.is_active_administrator(uuid)') IS NULL THEN
        RAISE EXCEPTION 'public.is_active_administrator(uuid) not found';
    END IF;

    -- Names introduced here must be free (never silently replace an object).
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = 'public'
                 AND p.proname IN ('admin_caller_has_permission', 'admin_list_users',
                                   'admin_get_user_details')) THEN
        RAISE EXCEPTION 'A function introduced by migration 006 already exists; inspect first';
    END IF;

    -- The protected tables must stay without client privileges (003/004).
    IF pg_catalog.has_table_privilege('authenticated', 'public.admin_accounts', 'SELECT')
       OR pg_catalog.has_table_privilege('authenticated', 'public.user_account_status', 'SELECT')
       OR pg_catalog.has_table_privilege('anon', 'public.admin_accounts', 'SELECT') THEN
        RAISE EXCEPTION 'Unexpected client privileges on protected administrative tables';
    END IF;
END
$preflight$;

-- -----------------------------------------------------------------------------
-- 2. Internal helper: does the CALLER hold an administrative permission?
--    Mirrors backend/app/core/admin_permissions.py and admin_get_my_access():
--    Administrators hold every registered key; Admin Employees hold granted
--    keys that are not administrator_only. Restricted accounts hold nothing.
-- -----------------------------------------------------------------------------
CREATE FUNCTION public.admin_caller_has_permission(p_permission text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
SET row_security = off
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.admin_accounts AS a
        JOIN public.admin_permissions AS p ON p.key = p_permission
        WHERE a.user_id = (SELECT auth.uid())
          AND a.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM public.user_account_status AS s
                          WHERE s.user_id = a.user_id AND s.status IS DISTINCT FROM 'active')
          AND (a.role = 'administrator'
               OR (a.role = 'admin_employee'
                   AND p.administrator_only IS FALSE
                   AND EXISTS (SELECT 1 FROM public.admin_permission_grants AS g
                               WHERE g.user_id = a.user_id AND g.permission_key = p.key))));
$function$;

-- -----------------------------------------------------------------------------
-- 3. Directory listing -> jsonb
--    {"total": n, "limit": l, "offset": o, "users": [ ... ]}
--    total is computed independently of the page, so an empty page past the
--    end still reports the correct total.
--    Order: registered_at DESC NULLS LAST, then user_id (deterministic).
--    Search: literal, case-insensitive substring of email or full name
--    (LIKE wildcards in the input are escaped).
-- -----------------------------------------------------------------------------
CREATE FUNCTION public.admin_list_users(
    p_search         text    DEFAULT NULL,   -- <= 100 characters
    p_account_status text    DEFAULT NULL,   -- active | suspended | banned
    p_admin_role     text    DEFAULT NULL,   -- administrator | admin_employee | none
    p_actor          text    DEFAULT NULL,   -- institutional actor key
    p_position       text    DEFAULT NULL,   -- head | employee
    p_limit          integer DEFAULT 25,     -- 1..100
    p_offset         integer DEFAULT 0       -- 0..10000
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
SET row_security = off
AS $function$
DECLARE
    v_search  text := nullif(btrim(p_search), '');
    v_pattern text;
    v_total   bigint;
    v_users   jsonb;
BEGIN
    IF NOT public.admin_caller_has_permission('users.view') THEN
        RAISE EXCEPTION 'Not authorized to view registered users' USING ERRCODE = '42501';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'p_limit must be between 1 and 100' USING ERRCODE = '22023';
    END IF;
    IF p_offset IS NULL OR p_offset < 0 OR p_offset > 10000 THEN
        RAISE EXCEPTION 'p_offset must be between 0 and 10000' USING ERRCODE = '22023';
    END IF;
    IF v_search IS NOT NULL AND char_length(v_search) > 100 THEN
        RAISE EXCEPTION 'p_search must be at most 100 characters' USING ERRCODE = '22023';
    END IF;
    IF p_account_status IS NOT NULL AND p_account_status NOT IN ('active', 'suspended', 'banned') THEN
        RAISE EXCEPTION 'Unknown account status filter' USING ERRCODE = '22023';
    END IF;
    IF p_admin_role IS NOT NULL AND p_admin_role NOT IN ('administrator', 'admin_employee', 'none') THEN
        RAISE EXCEPTION 'Unknown administrative role filter' USING ERRCODE = '22023';
    END IF;
    IF p_actor IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.institutional_actors AS x WHERE x.key = p_actor) THEN
        RAISE EXCEPTION 'Unknown institutional actor filter' USING ERRCODE = '22023';
    END IF;
    IF p_position IS NOT NULL AND p_position NOT IN ('head', 'employee') THEN
        RAISE EXCEPTION 'Unknown position filter' USING ERRCODE = '22023';
    END IF;

    IF v_search IS NOT NULL THEN
        v_pattern := '%' || replace(replace(replace(v_search, '\', '\\'), '%', '\%'), '_', '\_') || '%';
    END IF;

    WITH matched AS (
        SELECT u.id, u.email, u.created_at, u.last_sign_in_at,
               pr.full_name, pr.department,
               coalesce(st.status, 'active') AS account_status,
               ad.role AS admin_role, ad.status AS admin_status
        FROM auth.users AS u
        LEFT JOIN public.user_profiles       AS pr ON pr.id = u.id
        LEFT JOIN public.user_account_status AS st ON st.user_id = u.id
        LEFT JOIN public.admin_accounts      AS ad ON ad.user_id = u.id
        WHERE (v_pattern IS NULL
               OR u.email ILIKE v_pattern ESCAPE '\'
               OR pr.full_name ILIKE v_pattern ESCAPE '\')
          AND (p_account_status IS NULL OR coalesce(st.status, 'active') = p_account_status)
          AND (p_admin_role IS NULL
               OR (p_admin_role = 'none' AND ad.user_id IS NULL)
               OR ad.role = p_admin_role)
          AND ((p_actor IS NULL AND p_position IS NULL)
               OR EXISTS (SELECT 1 FROM public.institutional_memberships AS m
                          WHERE m.user_id = u.id
                            AND (p_actor IS NULL OR m.actor_key = p_actor)
                            AND (p_position IS NULL OR m.position = p_position)))
    ),
    page AS (
        SELECT * FROM matched
        ORDER BY created_at DESC NULLS LAST, id
        LIMIT p_limit OFFSET p_offset
    )
    SELECT (SELECT count(*) FROM matched),
           coalesce(jsonb_agg(jsonb_build_object(
               'user_id',         pg.id,
               'email',           pg.email,
               'full_name',       pg.full_name,
               'department',      pg.department,
               'registered_at',   pg.created_at,
               'last_sign_in_at', pg.last_sign_in_at,
               'account_status',  pg.account_status,
               'admin_role',      pg.admin_role,
               'admin_status',    pg.admin_status,
               'memberships', coalesce((
                   SELECT jsonb_agg(jsonb_build_object('actor', m.actor_key, 'position', m.position,
                                                       'status', m.status) ORDER BY m.actor_key)
                   FROM public.institutional_memberships AS m WHERE m.user_id = pg.id), '[]'::jsonb))
               ORDER BY pg.created_at DESC NULLS LAST, pg.id), '[]'::jsonb)
    INTO v_total, v_users
    FROM page AS pg;

    RETURN jsonb_build_object('total', v_total, 'limit', p_limit, 'offset', p_offset, 'users', v_users);
END;
$function$;

-- -----------------------------------------------------------------------------
-- 4. User details -> jsonb. Unknown user -> P0002.
--    Never returned: password hash, tokens, provider identities, raw
--    user/app metadata, invention content. Reason fields only for full
--    active Administrators (NULL otherwise).
-- -----------------------------------------------------------------------------
CREATE FUNCTION public.admin_get_user_details(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
SET row_security = off
AS $function$
DECLARE
    v_full_admin boolean;
    v_result     jsonb;
BEGIN
    IF NOT public.admin_caller_has_permission('users.view') THEN
        RAISE EXCEPTION 'Not authorized to view registered users' USING ERRCODE = '42501';
    END IF;
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'p_user_id is required' USING ERRCODE = '22023';
    END IF;
    v_full_admin := public.is_active_administrator((SELECT auth.uid()));

    SELECT jsonb_build_object(
        'user_id',         u.id,
        'email',           u.email,
        'full_name',       pr.full_name,
        'department',      pr.department,
        'has_profile',     pr.id IS NOT NULL,
        'registered_at',   u.created_at,
        'last_sign_in_at', u.last_sign_in_at,
        'account', jsonb_build_object(
            'status',     coalesce(st.status, 'active'),
            'reason',     CASE WHEN v_full_admin THEN st.reason END,
            'changed_at', st.changed_at),
        'administrator', CASE WHEN ad.user_id IS NULL THEN NULL ELSE jsonb_build_object(
            'role',              ad.role,
            'status',            ad.status,
            'status_reason',     CASE WHEN v_full_admin THEN ad.status_reason END,
            'status_changed_at', ad.status_changed_at,
            'created_at',        ad.created_at,
            'updated_at',        ad.updated_at,
            'granted_permissions', coalesce((
                SELECT jsonb_agg(g.permission_key ORDER BY g.permission_key)
                FROM public.admin_permission_grants AS g WHERE g.user_id = u.id), '[]'::jsonb)) END,
        'memberships', coalesce((
            SELECT jsonb_agg(jsonb_build_object(
                       'actor',         m.actor_key,
                       'actor_label',   x.label,
                       'position',      m.position,
                       'status',        m.status,
                       'status_reason', CASE WHEN v_full_admin THEN m.status_reason END,
                       'created_at',    m.created_at,
                       'updated_at',    m.updated_at,
                       'granted_permissions', coalesce((
                           SELECT jsonb_agg(ig.permission_key ORDER BY ig.permission_key)
                           FROM public.institutional_permission_grants AS ig
                           WHERE ig.user_id = m.user_id AND ig.actor_key = m.actor_key), '[]'::jsonb))
                   ORDER BY m.actor_key)
            FROM public.institutional_memberships AS m
            JOIN public.institutional_actors AS x ON x.key = m.actor_key
            WHERE m.user_id = u.id), '[]'::jsonb),
        'owned_invention_count', (SELECT count(*) FROM public.inventions AS i WHERE i.owner_id = u.id))
    INTO v_result
    FROM auth.users AS u
    LEFT JOIN public.user_profiles       AS pr ON pr.id = u.id
    LEFT JOIN public.user_account_status AS st ON st.user_id = u.id
    LEFT JOIN public.admin_accounts      AS ad ON ad.user_id = u.id
    WHERE u.id = p_user_id;

    IF v_result IS NULL THEN
        RAISE EXCEPTION 'User not found' USING ERRCODE = 'P0002';
    END IF;
    RETURN v_result;
END;
$function$;

-- -----------------------------------------------------------------------------
-- 5. Privileges (Supabase default privileges grant EXECUTE broadly)
-- -----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.admin_caller_has_permission(text)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.admin_list_users(text, text, text, text, text, integer, integer)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.admin_get_user_details(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
-- Callable with the caller's own JWT only; authorization is enforced inside.
GRANT EXECUTE ON FUNCTION public.admin_list_users(text, text, text, text, text, integer, integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.admin_get_user_details(uuid) TO authenticated;

-- -----------------------------------------------------------------------------
-- 6. Transactional postconditions (fail instead of leaving an unsafe state)
-- -----------------------------------------------------------------------------
DO $verify$
DECLARE
    fn  text;
    tbl text;
    own oid;
BEGIN
    FOREACH fn IN ARRAY ARRAY['public.admin_caller_has_permission(text)',
                              'public.admin_list_users(text,text,text,text,text,integer,integer)',
                              'public.admin_get_user_details(uuid)']
    LOOP
        SELECT p.proowner INTO own FROM pg_catalog.pg_proc p WHERE p.oid = fn::regprocedure;
        IF NOT (SELECT p.prosecdef FROM pg_catalog.pg_proc p WHERE p.oid = fn::regprocedure) THEN
            RAISE EXCEPTION '% must be SECURITY DEFINER', fn;
        END IF;
        -- The owner must be able to read every protected table without RLS
        -- hiding rows (superuser, BYPASSRLS, or table owner without FORCE RLS).
        FOREACH tbl IN ARRAY ARRAY['public.admin_accounts', 'public.admin_permissions',
                                   'public.admin_permission_grants', 'public.user_account_status',
                                   'public.institutional_memberships', 'public.institutional_actors',
                                   'public.institutional_permission_grants', 'public.user_profiles',
                                   'public.inventions']
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles r, pg_catalog.pg_class c
                WHERE r.oid = own AND c.oid = tbl::regclass
                  AND (r.rolsuper OR r.rolbypassrls OR (c.relowner = own AND NOT c.relforcerowsecurity))
            ) THEN
                RAISE EXCEPTION 'Owner of % cannot safely read %', fn, tbl;
            END IF;
        END LOOP;
        IF NOT pg_catalog.has_table_privilege(own, 'auth.users', 'SELECT') THEN
            RAISE EXCEPTION 'Owner of % cannot read auth.users', fn;
        END IF;
    END LOOP;

    IF pg_catalog.has_function_privilege('anon', 'public.admin_list_users(text,text,text,text,text,integer,integer)', 'EXECUTE')
       OR pg_catalog.has_function_privilege('anon', 'public.admin_get_user_details(uuid)', 'EXECUTE')
       OR pg_catalog.has_function_privilege('authenticated', 'public.admin_caller_has_permission(text)', 'EXECUTE')
       OR pg_catalog.has_function_privilege('anon', 'public.admin_caller_has_permission(text)', 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('authenticated', 'public.admin_list_users(text,text,text,text,text,integer,integer)', 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('authenticated', 'public.admin_get_user_details(uuid)', 'EXECUTE') THEN
        RAISE EXCEPTION 'Unexpected EXECUTE privileges on directory functions';
    END IF;
END
$verify$;

COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION (read-only; run separately)
-- =============================================================================
-- V1  SELECT p.proname, p.prosecdef, p.provolatile, p.proconfig, pg_get_userbyid(p.proowner)
--     FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--     WHERE n.nspname = 'public'
--       AND p.proname IN ('admin_caller_has_permission','admin_list_users','admin_get_user_details');
-- V2  SELECT routine_name, grantee, privilege_type FROM information_schema.routine_privileges
--     WHERE routine_schema = 'public'
--       AND routine_name IN ('admin_caller_has_permission','admin_list_users','admin_get_user_details')
--     ORDER BY 1, 2;          -- expect: list/details -> authenticated (+ owner) only
-- V3  public function count: expect 21 (18 existing + 3).
-- V4  From the API with real accounts (no SQL Editor: auth.uid() is NULL there):
--     ordinary user -> 42501/HTTP 403; Admin Employee without users.view -> 403;
--     the Administrator -> {"total": n, ...}; offset past the end -> users [] with correct total.
-- In the SQL Editor (no JWT) both functions correctly raise 42501.

-- =============================================================================
-- ROLLBACK (owner approval; no data was created)
-- =============================================================================
-- DROP FUNCTION public.admin_get_user_details(uuid);
-- DROP FUNCTION public.admin_list_users(text, text, text, text, text, integer, integer);
-- DROP FUNCTION public.admin_caller_has_permission(text);
