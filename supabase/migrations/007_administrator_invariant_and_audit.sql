-- =============================================================================
-- 007_administrator_invariant_and_audit.sql   (Phase 5.5.1 — DRAFT, NOT APPLIED)
-- =============================================================================
-- Independent of 006 (the read-only user directory). Purpose:
--   A. Transaction-safe invariant: at least one GLOBALLY active Administrator
--      (role administrator, status active, no non-active user_account_status
--      row) must remain after every change to admin_accounts or
--      user_account_status, including concurrent changes and auth.users
--      cascades.
--   B. Revised admin_accounts_guard() and user_account_status_guard(), based on
--      the RECOVERED applied definitions in 003/004. Every existing behaviour
--      is preserved (actor checks, updated_at / status_changed_at / changed_at
--      maintenance, immutable user_id, error messages and SQLSTATEs).
--      Strengthened: (1) the serialization lock is taken BEFORE any
--      authorization or invariant decision; (2) the recorded admin_accounts
--      actor must be GLOBALLY active (is_active_administrator), as the 004
--      guards already require; (3) the last-Administrator count uses global
--      status in both guards.
--   C. Audit triggers on admin_accounts and admin_permission_grants using the
--      existing audit_access_change() (attribution = auth.uid(), else system).
-- No table, column, RLS policy, storage policy or record is changed.
--
-- Applying (owner, Supabase SQL Editor, after review):
--   SET profile_match.migration_007_reviewed = 'yes';
-- =============================================================================
--
-- CONCURRENCY DESIGN
--   * One transaction-scoped advisory lock, key 5501001, guards every write to
--     admin_accounts and user_account_status. It is acquired as the FIRST
--     action of the BEFORE ROW guard, before the actor (authorization) check
--     and before the invariant check, and held until COMMIT/ROLLBACK.
--   * Under READ COMMITTED, each SQL statement inside a (volatile) PL/pgSQL
--     function takes a new snapshot, so every check performed after the lock
--     sees all changes committed by the previous lock holder. Authorization is
--     therefore re-evaluated after waiting: e.g. if transaction A bans
--     Administrator Y while transaction B, acting as Y, demotes X, B waits for
--     A and then fails the actor check.
--   * Rows changed earlier in the SAME statement are visible to the checks
--     (trigger visibility rules), so multi-row updates are covered.
--   * REPEATABLE READ / SERIALIZABLE keep a transaction-wide snapshot that can
--     predate the lock; writes to these tables are refused there (SQLSTATE
--     40001, retryable). PostgREST and the SQL Editor default to READ COMMITTED.
--   * Lock order: the triggering row lock (UPDATE/DELETE) or unique-index
--     insertion happens before the trigger, then the advisory lock; the checks
--     take no further row locks, so no lock cycle can form between these
--     guards. Cascades from auth.users deletion run the admin_accounts guard
--     and therefore the same lock.
--   * Owner maintenance escape for the invariant ONLY (never for actor checks):
--     SET LOCAL profile_match.allow_no_active_administrator = 'on';
--     honoured only when session_user is postgres or supabase_admin.
--   * Residual (documented, not changed here): admin_permission_grants_guard,
--     institutional_memberships_guard and institutional_permission_grants_guard
--     check the recorded actor without this lock; a grant made concurrently
--     with the actor's restriction can commit. Mutation RPCs (Phase 5.5.4+)
--     should take the same lock first.
-- =============================================================================

BEGIN;
SET LOCAL lock_timeout = '5s';

-- -----------------------------------------------------------------------------
-- 1. Preflight: deployed definitions must still be the recovered 003/004 ones
-- -----------------------------------------------------------------------------
DO $preflight$
DECLARE
    src text;
BEGIN
    IF coalesce(current_setting('profile_match.migration_007_reviewed', true), '') <> 'yes' THEN
        RAISE EXCEPTION 'Migration 007 not reviewed: SET profile_match.migration_007_reviewed = ''yes'' first';
    END IF;

    -- admin_accounts_guard (003): SECURITY INVOKER with the recovered body.
    SELECT p.prosrc INTO src FROM pg_catalog.pg_proc p
    WHERE p.oid = 'public.admin_accounts_guard()'::regprocedure AND NOT p.prosecdef;
    IF src IS NULL
       OR position('Administrative account identity cannot be changed' IN src) = 0
       OR position('Recorded actor must be an active Administrator' IN src) = 0
       OR position('The last active Administrator cannot be removed or restricted' IN src) = 0
       OR position('NEW.status_changed_at := now()' IN src) = 0 THEN
        RAISE EXCEPTION 'admin_accounts_guard() differs from the recovered 003 definition; inspect first';
    END IF;

    -- user_account_status_guard (004): SECURITY DEFINER with the recovered body.
    SELECT p.prosrc INTO src FROM pg_catalog.pg_proc p
    WHERE p.oid = 'public.user_account_status_guard()'::regprocedure AND p.prosecdef;
    IF src IS NULL
       OR position('Only an active Administrator can change account status' IN src) = 0
       OR position('The last active Administrator cannot be suspended or banned' IN src) = 0 THEN
        RAISE EXCEPTION 'user_account_status_guard() differs from the recovered 004 definition; inspect first';
    END IF;

    -- Triggers attached exactly as in 003/004.
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t
                   WHERE t.tgrelid = 'public.admin_accounts'::regclass
                     AND t.tgname = 'admin_accounts_guard' AND t.tgenabled = 'O') THEN
        RAISE EXCEPTION 'Trigger admin_accounts_guard missing or not enabled';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t
                   WHERE t.tgrelid = 'public.user_account_status'::regclass
                     AND t.tgname = 'user_account_status_guard' AND t.tgenabled = 'O') THEN
        RAISE EXCEPTION 'Trigger user_account_status_guard missing or not enabled';
    END IF;

    -- Audit triggers must not exist yet on the administrative tables.
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
               WHERE t.tgrelid IN ('public.admin_accounts'::regclass, 'public.admin_permission_grants'::regclass)
                 AND p.proname = 'audit_access_change') THEN
        RAISE EXCEPTION 'Administrative audit triggers already exist; inspect first';
    END IF;

    IF pg_catalog.to_regprocedure('public.admin_invariant_lock()') IS NOT NULL
       OR pg_catalog.to_regprocedure('public.assert_active_administrator_remains(uuid)') IS NOT NULL THEN
        RAISE EXCEPTION 'A function introduced by migration 007 already exists; inspect first';
    END IF;

    -- The invariant must hold before we start.
    IF NOT EXISTS (SELECT 1 FROM public.admin_accounts a WHERE public.is_active_administrator(a.user_id)) THEN
        RAISE EXCEPTION 'No globally active Administrator exists; resolve before applying 007';
    END IF;
END
$preflight$;

-- -----------------------------------------------------------------------------
-- 2. Serialization lock (first action of every guarded write)
-- -----------------------------------------------------------------------------
CREATE FUNCTION public.admin_invariant_lock()
RETURNS void
LANGUAGE plpgsql
VOLATILE
SET search_path = ''
AS $function$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(5501001);
    IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Administrator and account-status changes require READ COMMITTED isolation'
            USING ERRCODE = '40001';
    END IF;
END;
$function$;

-- -----------------------------------------------------------------------------
-- 3. Invariant check (call only while holding the lock)
--    Counts globally active Administrators other than p_affected.
-- -----------------------------------------------------------------------------
CREATE FUNCTION public.assert_active_administrator_remains(p_affected uuid)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
SET row_security = off
AS $function$
BEGIN
    IF coalesce(pg_catalog.current_setting('profile_match.allow_no_active_administrator', true), '') = 'on'
       AND session_user IN ('postgres', 'supabase_admin') THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.admin_accounts AS a
        WHERE a.role = 'administrator'
          AND a.status = 'active'
          AND a.user_id IS DISTINCT FROM p_affected
          AND NOT EXISTS (SELECT 1 FROM public.user_account_status AS s
                          WHERE s.user_id = a.user_id AND s.status IS DISTINCT FROM 'active'))
    THEN
        -- Caller supplies the guard-specific message; this is the shared code.
        RAISE EXCEPTION 'last_active_administrator' USING ERRCODE = '23514';
    END IF;
END;
$function$;

-- -----------------------------------------------------------------------------
-- 4. admin_accounts_guard — recovered 003 behaviour + lock + global status
--    Remains SECURITY INVOKER with empty search_path (as deployed).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_accounts_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    actor uuid;
    removes_active_admin boolean := false;
BEGIN
    -- Serialize BEFORE any authorization or invariant decision.
    PERFORM public.admin_invariant_lock();

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

    -- NULL actor = database-owner maintenance / bootstrap (as in 003).
    IF actor IS NOT NULL AND NOT public.is_active_administrator(actor) THEN
        RAISE EXCEPTION 'Recorded actor must be an active Administrator' USING ERRCODE = '42501';
    END IF;

    IF removes_active_admin THEN
        BEGIN
            PERFORM public.assert_active_administrator_remains(OLD.user_id);
        EXCEPTION WHEN check_violation THEN
            RAISE EXCEPTION 'The last active Administrator cannot be removed or restricted' USING ERRCODE = '23514';
        END;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 5. user_account_status_guard — recovered 004 behaviour + lock first
--    Remains SECURITY DEFINER with empty search_path (as deployed).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.user_account_status_guard()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    -- Serialize BEFORE any authorization or invariant decision.
    PERFORM public.admin_invariant_lock();

    IF NOT public.is_active_administrator(NEW.changed_by) THEN
        RAISE EXCEPTION 'Only an active Administrator can change account status' USING ERRCODE = '42501';
    END IF;
    -- Restricting an account that currently counts as a globally active
    -- Administrator (the table still shows the OLD status here).
    IF NEW.status <> 'active' AND public.is_active_administrator(NEW.user_id) THEN
        BEGIN
            PERFORM public.assert_active_administrator_remains(NEW.user_id);
        EXCEPTION WHEN check_violation THEN
            RAISE EXCEPTION 'The last active Administrator cannot be suspended or banned'
                USING ERRCODE = '23514';
        END;
    END IF;
    NEW.changed_at := NOW();
    RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 6. Audit coverage for administrative tables (existing generic function)
-- -----------------------------------------------------------------------------
CREATE TRIGGER audit_admin_accounts
AFTER INSERT OR UPDATE OR DELETE ON public.admin_accounts
FOR EACH ROW EXECUTE FUNCTION public.audit_access_change();

CREATE TRIGGER audit_admin_permission_grants
AFTER INSERT OR UPDATE OR DELETE ON public.admin_permission_grants
FOR EACH ROW EXECUTE FUNCTION public.audit_access_change();

-- -----------------------------------------------------------------------------
-- 7. Privileges: internal only (as 003/004 revoke their guards)
-- -----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.admin_invariant_lock()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.assert_active_administrator_remains(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.admin_accounts_guard(), public.user_account_status_guard()
    FROM PUBLIC, anon, authenticated, service_role;

-- -----------------------------------------------------------------------------
-- 8. Postconditions
-- -----------------------------------------------------------------------------
DO $verify$
BEGIN
    IF (SELECT p.prosecdef FROM pg_catalog.pg_proc p WHERE p.oid = 'public.admin_accounts_guard()'::regprocedure)
       OR NOT (SELECT p.prosecdef FROM pg_catalog.pg_proc p WHERE p.oid = 'public.user_account_status_guard()'::regprocedure) THEN
        RAISE EXCEPTION 'Guard security context changed unexpectedly';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
        WHERE p.proname = 'audit_access_change' AND NOT t.tgisinternal) <> 5 THEN
        RAISE EXCEPTION 'Expected five audit_access_change triggers';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.admin_accounts a WHERE public.is_active_administrator(a.user_id)) THEN
        RAISE EXCEPTION 'Invariant violated after migration';
    END IF;
END
$verify$;

COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION (read-only)
-- =============================================================================
-- V1 functions: expect 20 public functions before 006 (18 + 2) or 23 with 006.
-- V2 triggers: SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t
--      JOIN pg_class c ON c.oid = t.tgrelid
--      WHERE NOT t.tgisinternal AND c.relname IN ('admin_accounts','admin_permission_grants',
--        'user_account_status') ORDER BY 1, 2;      -- expect 20 inspected triggers overall (18 + 2)
-- V3 invariant: SELECT count(*) FROM public.admin_accounts a
--      WHERE public.is_active_administrator(a.user_id);   -- expect >= 1
-- V4 PostgreSQL concurrency tests (staging, read.md §28.11) — mandatory before relying on 007.

-- =============================================================================
-- ROLLBACK (owner approval)
-- =============================================================================
-- 1. Restore the exact original guard bodies from the recovered files:
--      003_admin_access.sql         -> CREATE OR REPLACE FUNCTION public.admin_accounts_guard() ...
--      004_institutional_access.sql -> CREATE OR REPLACE FUNCTION public.user_account_status_guard() ...
-- 2. DROP TRIGGER audit_admin_accounts ON public.admin_accounts;
--    DROP TRIGGER audit_admin_permission_grants ON public.admin_permission_grants;
--    (audit rows already written remain; append-only by design)
-- 3. DROP FUNCTION public.assert_active_administrator_remains(uuid);
--    DROP FUNCTION public.admin_invariant_lock();
--    (only after step 1, because the revised guards call them)
