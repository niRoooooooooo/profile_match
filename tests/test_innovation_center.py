"""Innovation Center role pages and the development role switcher.

Static checks always run. Interaction checks run the real pages in headless
Chrome/Edge from local files (skipped if no browser). No network, no Supabase.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from innovation_center_samples import build_samples, render_js

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ROLES = FRONTEND / "roles"
IC = ROLES / "innovation-center"
IC_JS = sorted((IC / "js").rglob("*.js"))
NODE = shutil.which("node")
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    shutil.which("chrome") or "", shutil.which("msedge") or "") if p and Path(p).exists()), None)
IC_PAGES = ["overview.html", "profile-approvals.html", "portfolio.html", "match-review.html"]
COMING_SOON = "Coming Soon — Available After Data Integration"
TRENDS = [["Pipeline Trends & Reports", "View Pipeline Trends & Reports", True, COMING_SOON],
          ["Technology Domain Trends & Reports", "View Technology Domain Trends & Reports", True,
           COMING_SOON]]


def read(path):
    return Path(path).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Static checks: structure, isolation and protected files
# --------------------------------------------------------------------------

class StructureAndIsolationTests(unittest.TestCase):
    def test_role_directory_layout(self):
        for name in ["index.html", *IC_PAGES, "css/innovation-center.css", "js/shell.js",
                     "js/overview.js", "js/profile-approvals.js", "js/portfolio.js",
                     "js/match-review.js", "js/data/mock-data.js", "js/data/repository.js",
                     "js/data/sample-reports.js"]:
            self.assertTrue((IC / name).is_file(), name)
        for role in ("industry-liaison", "management", "administrator", "industry-partner"):
            self.assertTrue((ROLES / role / "index.html").is_file(), role)
        self.assertFalse((FRONTEND / "ic-preview").exists(), "obsolete ic-preview removed")

    def test_every_referenced_asset_exists(self):
        pages = [*ROLES.rglob("*.html"), FRONTEND / "index.html"]
        for page in pages:
            for ref in re.findall(r'(?:src|href)="([^"#?]+)', read(page)):
                if ref.startswith(("http", "mailto:")) or ref in ("/dashboard", "/login"):
                    continue
                target = (FRONTEND / ref.removeprefix("/assets/")) if ref.startswith("/assets/") \
                    else (page.parent / ref)
                self.assertTrue(target.resolve().exists(), f"{page.name}: {ref}")

    def test_innovation_center_code_has_no_data_access(self):
        forbidden = re.compile(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|supabase|getSupabase|"
                               r"localStorage|sessionStorage|indexedDB|document\.cookie|/api/|"
                               r"invention-document|invention-profiles|https?://(?!www.w3.org/2000/svg)",
                               re.IGNORECASE)
        for path in IC_JS:
            if path.name == "sample-reports.js":
                continue
            self.assertEqual(forbidden.findall(read(path)), [], path.name)

    def test_role_switcher_only_uses_server_authorization(self):
        # Phase 5.4.2: the interface list comes only from GET /api/access/me; the
        # switcher may otherwise only start/end/check the server UI sessions.
        text = read(FRONTEND / "js" / "role-switcher.js")
        self.assertEqual(re.findall(r"\bfetch\s*\(", text), ["fetch("], "single request helper")
        self.assertEqual(sorted(set(re.findall(r"'(/(?:api|admin|institutional)/[^']*)'", text))),
                         ["/admin/session", "/api/access/me", "/institutional/session"])
        never = re.compile(r"XMLHttpRequest|WebSocket|sendBeacon|localStorage|indexedDB|"
                           r"document\.cookie|\.from\s*\(|\.rpc\s*\(|\.storage\b|signOut\s*\(|"
                           r"signIn|invention|https?://", re.IGNORECASE)
        self.assertEqual(never.findall(text), [])
        self.assertNotIn("sessionStorage", text)
        # No built-in role list, public role pages or "coming soon" entries.
        for stale in ("/assets/roles/", "comingSoon", "Coming soon", "requiresAdminAccess",
                      "PROFILE_MATCH_ROLES"):
            self.assertNotIn(stale, text)

    def test_no_charts_graphs_or_analytics_in_this_phase(self):
        self.assertFalse((FRONTEND / "js" / "charts.js").exists())
        # Chart CODE only; the placeholder text may mention "charts" in prose.
        graphic = re.compile(r"createElementNS|<svg|\bsvg\b|<canvas|PMCharts|chart-|\.chart\b|"
                             r"'chart|heatmap|gauge|funnel", re.IGNORECASE)
        for path in [*IC_JS, *(IC / p for p in IC_PAGES), IC / "css" / "innovation-center.css"]:
            if path.name in ("sample-reports.js", "mock-data.js"):
                continue
            self.assertEqual(graphic.findall(read(path)), [], path.name)
        repository = read(IC / "js" / "data" / "repository.js")
        for name in ("stats", "lifecycleFunnel", "stageDistribution", "domainCounts",
                     "trlDistribution", "statusBreakdown", "domainStageHeatmap", "engagementPipeline"):
            self.assertNotRegex(repository, rf"\b{name}\b")

    def test_session_header_only_reads_own_account_and_signs_out(self):
        text = read(FRONTEND / "js" / "session-header.js")
        calls = set(re.findall(r"client\.(?:auth\.)?(\w+)\(", text))
        self.assertEqual(calls, {"getUser", "from", "signOut"})
        self.assertIn(".from('user_profiles')", text)
        self.assertIn(".select('full_name')", text)
        self.assertIn("signOut({scope: 'local'})", text)
        for forbidden in ("inventions", "storage", "insert", "update(", "upsert", "delete(",
                          "invention-document", "invention-profiles", "/api/inventions",
                          "signInWithOAuth", "onAuthStateChange"):
            self.assertNotIn(forbidden, text)

    def test_sample_reports_are_current_and_contain_no_ids_or_urls(self):
        text = read(IC / "js" / "data" / "sample-reports.js")
        self.assertEqual(text, render_js(build_samples()),
                         "Regenerate with: python tests/innovation_center_samples.py")
        self.assertNotRegex(text, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        self.assertNotRegex(text, r"https?://|<script|supabase")

    def test_pages_are_labelled_and_not_indexed(self):
        for page in [*(IC / p for p in IC_PAGES), *(ROLES / r / "index.html" for r in
                     ("industry-liaison", "management", "administrator", "industry-partner"))]:
            html = read(page)
            self.assertIn('name="robots" content="noindex, nofollow"', html, page.name)
            self.assertIn("Development interface.", html, page.name)
            self.assertIn('id="roleSwitcher"', html, page.name)
            self.assertIn('id="logoutButton"', html, page.name)
            self.assertNotIn("dashboard.js", html)
            self.assertNotIn("auth.js", html)

    def test_innovator_dashboard_change_is_presentation_only(self):
        html = read(FRONTEND / "index.html")
        self.assertIn('<body data-role="innovator">', html)
        self.assertIn('<div id="roleSwitcher"></div>', html)
        self.assertIn('/assets/js/role-switcher.js', html)
        # Compare with the last committed version from BEFORE the switcher.
        log = subprocess.run(["git", "log", "--format=%H", "--", "frontend/index.html"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
        if log.returncode != 0:
            self.skipTest("git history not available")
        head = None
        for commit in log.stdout.split():
            shown = subprocess.run(["git", "show", f"{commit}:frontend/index.html"], cwd=ROOT,
                                   capture_output=True, text=True, encoding="utf-8")
            if shown.returncode == 0 and "roleSwitcher" not in shown.stdout:
                head = shown
                break
        if head is None:
            self.skipTest("no committed version from before the role switcher")
        stripped = html.replace('    <link rel="stylesheet" href="/assets/css/roles.css">\n', "")
        stripped = stripped.replace(
            "    <!-- Development interface switcher (presentation only; no role change). -->\n"
            '    <script src="/assets/js/role-switcher.js" defer></script>\n', "")
        stripped = stripped.replace('<body data-role="innovator">', "<body>")
        stripped = stripped.replace('    <div id="roleSwitcher"></div>\n', "")
        # Phase 5.4.4: workspace hidden until account authorization succeeds.
        stripped = stripped.replace('<p id="accountCheckStatus" class="content muted" role="status">\n'
                                    '    Checking account access...\n</p>\n\n', "")
        stripped = stripped.replace('<div class="app" hidden>', '<div class="app">')
        self.assertEqual(stripped.replace("\r\n", "\n"), head.stdout.replace("\r\n", "\n"))

    def test_protected_auth_files_untouched_by_roles(self):
        for name in ("js/auth.js", "js/api.js", "js/dashboard.js", "login.html",
                     "invention_report.html"):
            text = read(FRONTEND / name)
            self.assertNotIn("role-switcher", text, name)
            self.assertNotIn("roles/", text, name)
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            self.assertNotIn("roles/innovation-center", read(path), path.name)

    def test_institutional_files_are_never_public(self):
        # Phase 5.4.1: no institutional file is served by the public /assets
        # mount; the Innovation Center opens only through its protected route.
        import _fixtures  # noqa: F401  (adds backend to sys.path)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        for role in ("innovation-center", "industry-liaison", "management", "administrator",
                     "industry-partner"):
            for path in (f"/assets/roles/{role}/index.html", f"/assets/roles/{role}/",
                         f"/assets/roles/%2e%2e/roles/{role}/index.html",
                         f"/assets/ROLES/{role.upper()}/index.html",
                         f"/assets/roles%5c{role}%5cindex.html",
                         f"/assets/css/../roles/{role}/index.html"):
                self.assertEqual(client.get(path).status_code, 404, path)
        for name in ("overview.html", "css/innovation-center.css", "js/shell.js",
                     "js/data/mock-data.js", "js/data/sample-reports.js"):
            self.assertEqual(client.get(f"/assets/roles/innovation-center/{name}").status_code,
                             404, name)
            protected = client.get(f"/institutional/innovation-center/{name}")
            self.assertEqual(protected.status_code, 401, name)       # no session
            self.assertNotIn("Innovation Center", protected.text, name)
            self.assertEqual(protected.headers["cache-control"], "no-store, max-age=0")
        for role in ("industry-liaison", "management", "industry-partner"):
            self.assertEqual(client.get(f"/institutional/{role}/index.html").status_code, 404)
        # Shared frontend files needed by the Innovator dashboard stay public.
        for path in ("/assets/css/style.css", "/assets/css/roles.css", "/assets/js/api.js",
                     "/assets/js/role-switcher.js", "/assets/js/dashboard.js",
                     "/assets/invention_report.html"):
            self.assertEqual(client.get(path).status_code, 200, path)

    def test_development_test_page_is_never_public(self):
        # Phase 5.4.4: the file stays on disk but is never served.
        import _fixtures  # noqa: F401  (adds backend to sys.path)
        from fastapi.testclient import TestClient
        from app.main import app

        self.assertTrue((FRONTEND / "phase4_test.html").is_file())
        client = TestClient(app)
        for path in ("/assets/phase4_test.html", "/assets/PHASE4_TEST.HTML", "/assets/Phase4_Test.html",
                     "/assets/%70hase4_test.html", "/assets/phase4_test.html.", "/assets/phase4_test.html%20",
                     "/assets/phase4_test.html::$DATA", "/assets/PHASE4~1.HTM", "/assets/css/../phase4_test.html",
                     "/assets/css/..%2fphase4_test.html", "/assets//phase4_test.html", "/assets/./phase4_test.html",
                     "/phase4_test.html"):
            self.assertEqual(client.get(path).status_code, 404, path)


class AuthorizationServiceTests(unittest.TestCase):
    """Phase 5.4.4: permanent checks of the REAL Administrator and institutional
    authorization services and routes against a simulated Supabase (no network).

    A regression that made the Administrator service unusable once passed the
    whole suite unnoticed; these tests exercise it end to end.
    """

    IC = "innovation_center."

    def setUp(self):
        import base64
        import time
        import uuid

        import _fixtures  # noqa: F401  (adds backend to sys.path)
        import httpx
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.admin_access import get_admin_access_service
        from app.core.institutional_access import get_institutional_access_service
        from app.services.admin_access_service import AdminAccessService
        from app.services.institutional_access_service import InstitutionalAccessService

        admin = {"role": "administrator", "status": "active", "permissions": []}
        staff = {"role": "admin_employee", "status": "active", "permissions": ["users.view"]}
        member = lambda position, perms=(): [{"actor": "innovation_center", "position": position,
                                              "status": "active", "permissions": list(perms)}]
        staff_noview = {"role": "admin_employee", "status": "active", "permissions": ["audit.view"]}
        self.users = {
            "admin": {"admin": admin, "memberships": []},
            "staff": {"admin": staff, "memberships": []},
            "staff_noview": {"admin": staff_noview, "memberships": []},
            "ordinary": {"admin": None, "memberships": []},
            "head": {"admin": None, "memberships": member("head")},
            "employee": {"admin": None, "memberships": member("employee", [
                self.IC + "inventions.view", self.IC + "profiles.review",
                self.IC + "profiles.approve", "industry_liaison.matches.view"])},
        }
        for row in self.users.values():
            row["uid"] = str(uuid.uuid4())
            row["record"] = None           # None = normal record with account_status null

        def handler(request):
            name = request.headers.get("authorization", "")[7:].rsplit(".", 1)[-1]
            row, path = self.users.get(name), request.url.path
            if path.endswith("/auth/v1/user"):
                return httpx.Response(200, json={"id": row["uid"]}) if row else httpx.Response(401, json={})
            if path.endswith("/rpc/admin_get_my_access"):
                if row["admin"] is None:
                    return httpx.Response(200, content=b"null", headers={"Content-Type": "application/json"})
                return httpx.Response(200, json={"user_id": row["uid"], **row["admin"]})
            if path.endswith("/rpc/institutional_get_my_access"):
                record = row["record"]
                if callable(record):
                    return record(row)
                return httpx.Response(200, json={"user_id": row["uid"], "account_status": None,
                                                 "memberships": row["memberships"]})
            if path.endswith("/rpc/admin_list_users"):
                return self.directory_rpc(request, row)
            if path.endswith("/rpc/admin_get_user_details"):
                return self.details_rpc(request, row)
            return httpx.Response(404, json={})

        # Phase 5.5.2: simulated public.admin_list_users() (migration 006).
        # Fictional directory rows only; the emulator enforces the same rule as
        # the database (users.view, unrestricted) and records every call.
        self.directory_rows = [
            {"user_id": str(uuid.uuid4()), "email": "alpha.innovator@example.test",
             "full_name": "Alpha Innovator", "department": "Engineering",
             "registered_at": "2026-11-20T10:00:00+00:00", "last_sign_in_at": "2026-11-27T09:00:00+00:00",
             "account_status": "active", "admin_role": None, "admin_status": None,
             "memberships": [{"actor": "innovation_center", "position": "head", "status": "active"}]},
            {"user_id": str(uuid.uuid4()), "email": None, "full_name": None, "department": None,
             "registered_at": None, "last_sign_in_at": None, "account_status": "suspended",
             "admin_role": "admin_employee", "admin_status": "active", "memberships": []},
        ]
        self.directory_calls = []
        self.directory_response = None      # callable(request) -> httpx.Response to override

        def directory_rpc(request, row):
            body = json.loads(request.content)
            self.directory_calls.append({"args": body, "apikey": request.headers.get("apikey"),
                                         "authorization": request.headers.get("authorization")})
            if self.directory_response is not None:
                return self.directory_response(request)
            if not row:
                return httpx.Response(401, json={})
            grants = (row["admin"] or {}).get("permissions", [])
            allowed = (row["admin"] is not None and row["admin"]["status"] == "active"
                       and not row.get("restricted")
                       and (row["admin"]["role"] == "administrator" or "users.view" in grants))
            if not allowed:
                return httpx.Response(403, json={"code": "42501", "message": "Not authorized"})
            matches = [u for u in self.directory_rows
                       if not body["p_search"]
                       or body["p_search"].lower() in (u["email"] or "").lower()
                       or body["p_search"].lower() in (u["full_name"] or "").lower()]
            if body["p_account_status"]:
                matches = [u for u in matches if u["account_status"] == body["p_account_status"]]
            page = matches[body["p_offset"]:body["p_offset"] + body["p_limit"]]
            return httpx.Response(200, json={"total": len(matches), "limit": body["p_limit"],
                                             "offset": body["p_offset"], "users": page})
        self.directory_rpc = directory_rpc

        # Phase 5.5.3: simulated public.admin_get_user_details(). Fictional
        # targets: one with a profile, an Admin Employee account and two
        # memberships with explicit grants; one without a profile row.
        self.target_full = str(uuid.uuid4())
        self.target_bare = str(uuid.uuid4())
        self.detail_rows = {
            self.target_full: {
                "user_id": self.target_full, "email": "beta.staff@example.test", "full_name": "Beta Staff",
                "department": "Research Office", "has_profile": True,
                "registered_at": "2026-11-21T08:00:00+00:00", "last_sign_in_at": None,
                "account": {"status": "suspended", "reason": "Fictional restriction reason",
                            "changed_at": "2026-11-26T12:00:00+00:00"},
                "administrator": {"role": "admin_employee", "status": "active",
                                  "status_reason": "Fictional admin note",
                                  "status_changed_at": None, "created_at": "2026-11-22T08:00:00+00:00",
                                  "updated_at": "2026-11-22T08:00:00+00:00",
                                  "granted_permissions": ["audit.view", "users.view"]},
                "memberships": [
                    {"actor": "innovation_center", "actor_label": "Innovation Center", "position": "employee",
                     "status": "active", "status_reason": None, "created_at": "2026-11-23T08:00:00+00:00",
                     "updated_at": "2026-11-23T08:00:00+00:00",
                     "granted_permissions": ["innovation_center.inventions.view"]},
                    {"actor": "management", "actor_label": "Management", "position": "head",
                     "status": "suspended", "status_reason": "Fictional membership note",
                     "created_at": "2026-11-24T08:00:00+00:00", "updated_at": "2026-11-25T08:00:00+00:00",
                     "granted_permissions": []}],
                "owned_invention_count": 2},
            self.target_bare: {
                "user_id": self.target_bare, "email": None, "full_name": None, "department": None,
                "has_profile": False, "registered_at": None, "last_sign_in_at": None,
                "account": {"status": "active", "reason": None, "changed_at": None},
                "administrator": None, "memberships": [], "owned_invention_count": 0},
        }
        self.details_response = None        # callable(request) -> httpx.Response to override

        def details_rpc(request, row):
            body = json.loads(request.content)
            self.directory_calls.append({"args": body, "apikey": request.headers.get("apikey"),
                                         "authorization": request.headers.get("authorization")})
            if self.details_response is not None:
                return self.details_response(request)
            grants = (row["admin"] or {}).get("permissions", []) if row else []
            allowed = (row and row["admin"] is not None and row["admin"]["status"] == "active"
                       and (row["admin"]["role"] == "administrator" or "users.view" in grants))
            if not allowed:
                return httpx.Response(403, json={"code": "42501"})
            target = self.detail_rows.get(body["p_user_id"])
            if target is None:
                return httpx.Response(400, json={"code": "P0002", "message": "User not found"})
            result = json.loads(json.dumps(target))
            if row["admin"]["role"] != "administrator":          # reasons: full Administrators only
                result["account"]["reason"] = None
                if result["administrator"]:
                    result["administrator"]["status_reason"] = None
                for membership in result["memberships"]:
                    membership["status_reason"] = None
            return httpx.Response(200, json=result)
        self.details_rpc = details_rpc

        transport = httpx.MockTransport(handler)
        self.admin_service = AdminAccessService("https://example.supabase.co", "sb_publishable_test",
                                                transport=transport)
        institutional = InstitutionalAccessService(self.admin_service, "https://example.supabase.co",
                                                   "sb_publishable_test", transport=transport)
        overrides = app.dependency_overrides
        overrides[get_admin_access_service] = lambda: self.admin_service
        overrides[get_institutional_access_service] = lambda: institutional
        self.addCleanup(overrides.pop, get_admin_access_service, None)
        self.addCleanup(overrides.pop, get_institutional_access_service, None)
        from app.api.admin_users import get_admin_user_service
        from app.services.admin_user_service import AdminUserService
        user_service = AdminUserService("https://example.supabase.co", "sb_publishable_test",
                                        transport=transport)
        overrides[get_admin_user_service] = lambda: user_service
        self.addCleanup(overrides.pop, get_admin_user_service, None)
        self.app, self.TestClient, self.httpx = app, TestClient, httpx

        def token(name):
            claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode())
            return "h." + claims.decode().rstrip("=") + "." + name
        self.token = token

    def client(self):
        return self.TestClient(self.app, base_url="http://localhost")

    def bearer(self, name):
        return {"Authorization": "Bearer " + self.token(name)}

    def start(self, client, kind, name):
        return client.post(f"/{kind}/session", headers={"Origin": "http://localhost", **self.bearer(name)})

    def set_record(self, name, body=None, status=200, raw=None):
        httpx = self.httpx
        def record(row):
            if raw is not None:
                return httpx.Response(status, content=raw, headers={"Content-Type": "application/json"})
            payload = body(row) if callable(body) else body
            return httpx.Response(status, json=payload)
        self.users[name]["record"] = record

    def test_administrator_service_methods_remain_callable(self):
        import asyncio
        for method in ("get_access", "get_access_and_record", "_fetch_own_record", "_interpret",
                       "_account_status"):
            self.assertTrue(callable(getattr(self.admin_service, method, None)), method)
        access, record = asyncio.run(self.admin_service.get_access_and_record(self.token("admin")))
        self.assertTrue(access.is_administrator and access.is_active)
        self.assertEqual(len(access.effective_permissions), 24)
        self.assertEqual(record["user_id"], self.users["admin"]["uid"])

    def test_active_administrator_has_24_permissions_and_ui(self):
        response = self.client().get("/api/admin/access/me", headers=self.bearer("admin"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["permissions"]), 24)
        client = self.client()
        self.assertEqual(self.start(client, "admin", "admin").status_code, 200)
        self.assertEqual(client.get("/admin/overview.html").status_code, 200)
        self.assertEqual(len(client.get("/admin/session").json()["permissions"]), 24)
        # No institutional access without an explicit membership.
        self.assertEqual(self.start(self.client(), "institutional", "admin").status_code, 403)

    def test_admin_employee_permission_isolation(self):
        response = self.client().get("/api/admin/access/me", headers=self.bearer("staff"))
        self.assertEqual(response.json()["permissions"], ["users.view"])
        interfaces = self.client().get("/api/access/me", headers=self.bearer("staff")).json()["interfaces"]
        self.assertEqual([(i["id"], i["label"]) for i in interfaces],
                         [("innovator", "Innovator / Researcher"), ("administrator", "Admin Employee")])

    def test_ordinary_innovator_access(self):
        client = self.client()
        self.assertEqual(client.get("/api/admin/access/me", headers=self.bearer("ordinary")).status_code, 403)
        me = client.get("/api/access/me", headers=self.bearer("ordinary")).json()
        self.assertEqual([i["id"] for i in me["interfaces"]], ["innovator"])
        self.assertIsNone(me["administrator"])
        self.assertEqual(self.start(client, "admin", "ordinary").status_code, 403)
        self.assertEqual(self.start(client, "institutional", "ordinary").status_code, 403)
        self.assertEqual(client.get("/institutional/innovation-center/overview.html").status_code, 401)

    def test_institutional_head_and_employee(self):
        head = self.client()
        self.assertEqual(self.start(head, "institutional", "head").status_code, 200)
        session = head.get("/institutional/session").json()["actors"]["innovation_center"]
        self.assertEqual((session["position"], len(session["permissions"])), ("head", 11))
        self.assertEqual(head.get("/institutional/innovation-center/portfolio.html").status_code, 200)
        employee = self.client()
        self.assertEqual(self.start(employee, "institutional", "employee").status_code, 200)
        session = employee.get("/institutional/session").json()["actors"]["innovation_center"]
        self.assertEqual(session["permissions"], [self.IC + "inventions.view", self.IC + "profiles.review"])
        self.assertEqual(employee.get("/institutional/innovation-center/profile-approvals.html").status_code, 200)
        self.assertEqual(employee.get("/institutional/innovation-center/portfolio.html").status_code, 403)

    def test_suspended_banned_and_unknown_accounts_are_refused(self):
        for status in ("suspended", "banned", "archived"):
            for name in ("admin", "head"):
                self.set_record(name, lambda row, s=status: {"user_id": row["uid"], "account_status": s,
                                                             "memberships": row["memberships"]})
            client = self.client()
            self.assertEqual(client.get("/api/admin/access/me", headers=self.bearer("admin")).status_code, 403)
            self.assertEqual(client.get("/api/access/me", headers=self.bearer("admin")).status_code, 403)
            self.assertEqual(self.start(client, "admin", "admin").status_code, 403, status)
            self.assertEqual(self.start(client, "institutional", "head").status_code, 403, status)

    def test_restriction_during_an_admin_session_ends_it(self):
        client = self.client()
        self.assertEqual(self.start(client, "admin", "admin").status_code, 200)
        self.set_record("admin", lambda row: {"user_id": row["uid"], "account_status": "banned",
                                              "memberships": []})
        self.assertEqual(client.get("/admin/overview.html").status_code, 403)
        self.users["admin"]["record"] = None
        self.assertEqual(client.get("/admin/overview.html").status_code, 401)     # not restored

    def test_explicit_null_status_is_active(self):
        self.set_record("admin", lambda row: {"user_id": row["uid"], "account_status": None, "memberships": []})
        self.assertEqual(self.client().get("/api/admin/access/me", headers=self.bearer("admin")).status_code, 200)

    def test_malformed_mismatched_or_unavailable_records_fail_closed(self):
        import uuid
        cases = (dict(body=lambda row: {"user_id": row["uid"], "memberships": []}),         # field missing
                 dict(body=lambda row: {"user_id": row["uid"], "account_status": 7, "memberships": []}),
                 dict(body=lambda row: {"account_status": None, "memberships": []}),        # no identity
                 dict(body=lambda row: {"user_id": str(uuid.uuid4()), "account_status": None,
                                        "memberships": []}),                                # mismatched
                 dict(body=[{"account_status": None}]),                                     # not an object
                 dict(raw=b"null"), dict(raw=b"<html>"),
                 dict(body={"code": "PGRST202"}, status=404),                               # function missing
                 dict(body={}, status=503))                                                 # outage
        for case in cases:
            for name in ("admin", "head"):
                self.set_record(name, **case)
            client = self.client()
            for path in ("/api/admin/access/me", "/api/access/me"):
                self.assertEqual(client.get(path, headers=self.bearer("admin")).status_code, 503, (case, path))
            self.assertEqual(self.start(client, "admin", "admin").status_code, 503, case)
            self.assertEqual(self.start(client, "institutional", "head").status_code, 503, case)

    def test_invalid_token_is_401(self):
        client = self.client()
        self.assertEqual(client.get("/api/admin/access/me", headers=self.bearer("nobody")).status_code, 401)
        self.assertEqual(client.get("/api/access/me").status_code, 401)

    # ------------------------------------------- Phase 5.5.2: GET /api/admin/users

    def directory(self, name="admin", params=None, headers=None):
        hdrs = self.bearer(name) if headers is None else headers
        return self.client().get("/api/admin/users", params=params or {}, headers=hdrs)

    def test_directory_administrator_and_authorized_admin_employee(self):
        for name in ("admin", "staff"):
            response = self.directory(name)
            self.assertEqual(response.status_code, 200, (name, response.text))
            self.assertEqual(response.headers["cache-control"], "no-store")
            body = response.json()
            self.assertEqual((body["total"], body["limit"], body["offset"]), (2, 20, 0))
            self.assertEqual(set(body["users"][0]), {
                "user_id", "email", "full_name", "department", "registered_at", "last_sign_in_at",
                "account_status", "admin_role", "admin_status", "memberships"})
            self.assertEqual(body["users"][0]["memberships"],
                             [{"actor": "innovation_center", "position": "head", "status": "active"}])

    def test_directory_denies_everyone_without_users_view(self):
        for name in ("staff_noview", "ordinary", "head", "employee"):
            self.assertEqual(self.directory(name).status_code, 403, name)
        self.assertEqual(self.directory(headers={}).status_code, 401)
        self.assertEqual(self.directory("nobody").status_code, 401)
        self.assertEqual(self.directory_calls, [], "denied before any directory request")

    def test_directory_denies_restricted_accounts(self):
        for status_value in ("suspended", "banned", "archived"):
            self.set_record("admin", lambda row, s=status_value: {
                "user_id": row["uid"], "account_status": s, "memberships": []})
            self.assertEqual(self.directory("admin").status_code, 403, status_value)
        self.assertEqual(self.directory_calls, [])

    def test_directory_forwards_exact_rpc_contract_with_caller_token(self):
        params = {"search": "  Alpha ", "account_status": "active", "admin_role": "none",
                  "actor": "innovation_center", "position": "head", "limit": 5, "offset": 0}
        response = self.directory("admin", params)
        self.assertEqual(response.status_code, 200, response.text)
        call = self.directory_calls[-1]
        self.assertEqual(call["args"], {"p_search": "Alpha", "p_account_status": "active",
                                        "p_admin_role": "none", "p_actor": "innovation_center",
                                        "p_position": "head", "p_limit": 5, "p_offset": 0})
        self.assertEqual(call["apikey"], "sb_publishable_test")
        self.assertEqual(call["authorization"], "Bearer " + self.token("admin"))
        self.assertFalse(any((c["apikey"] or "").startswith("sb_secret_") for c in self.directory_calls))
        self.assertEqual([u["full_name"] for u in response.json()["users"]], ["Alpha Innovator"])
        # Defaults and blank search.
        self.directory("admin", {"search": "   "})
        self.assertEqual(self.directory_calls[-1]["args"], {
            "p_search": None, "p_account_status": None, "p_admin_role": None, "p_actor": None,
            "p_position": None, "p_limit": 20, "p_offset": 0})

    def test_directory_parameter_validation_matches_migration_006(self):
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 10001},
                       {"search": "x" * 101}, {"account_status": "deleted"}, {"admin_role": "owner"},
                       {"position": "manager"}, {"actor": "Innovation-Center"}, {"limit": "many"}):
            self.assertEqual(self.directory("admin", params).status_code, 422, params)
        self.assertEqual(self.directory_calls, [])
        self.assertEqual(self.directory("admin", {"limit": 100, "offset": 10000}).status_code, 200)

    def test_directory_empty_page_and_nullable_fields(self):
        body = self.directory("admin", {"offset": 50}).json()
        self.assertEqual((body["total"], body["users"]), (2, []))
        body = self.directory("admin", {"search": "no-such-person"}).json()
        self.assertEqual((body["total"], body["users"]), (0, []))
        nullable = self.directory("admin", {"account_status": "suspended"}).json()["users"][0]
        for field in ("email", "full_name", "department", "registered_at", "last_sign_in_at"):
            self.assertIsNone(nullable[field], field)

    def test_directory_database_errors_and_malformed_responses_fail_closed(self):
        httpx = self.httpx
        good = {"user_id": self.directory_rows[0]["user_id"], "email": None, "full_name": None,
                "department": None, "registered_at": None, "last_sign_in_at": None,
                "account_status": "active", "admin_role": None, "admin_status": None, "memberships": []}
        page = lambda users, **kw: {"total": len(users), "limit": 20, "offset": 0, "users": users, **kw}

        def unreachable(request):
            raise httpx.ConnectError("down", request=request)
        cases = (
            (lambda r: httpx.Response(403, json={"code": "42501"}), 403),       # database refuses caller
            (lambda r: httpx.Response(400, json={"code": "22023"}), 400),       # invalid argument
            (lambda r: httpx.Response(401, json={}), 401),
            (lambda r: httpx.Response(404, json={"code": "PGRST202"}), 503),    # function missing
            (lambda r: httpx.Response(500, json={}), 503),
            (unreachable, 503),
            (lambda r: httpx.Response(200, content=b"null", headers={"Content-Type": "application/json"}), 503),
            (lambda r: httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"}), 503),
            (lambda r: httpx.Response(200, json=[good]), 503),                                   # not an object
            (lambda r: httpx.Response(200, json={"users": [good]}), 503),                        # fields missing
            (lambda r: httpx.Response(200, json=page([{**good, "reason": "x"}])), 503),          # unexpected field
            (lambda r: httpx.Response(200, json=page([{**good, "account_status": "deleted"}])), 503),
            (lambda r: httpx.Response(200, json=page([{**good, "user_id": "not-a-uuid"}])), 503),
            (lambda r: httpx.Response(200, json=page([good], limit=99)), 503),                   # window mismatch
            (lambda r: httpx.Response(200, json=page([good], total=-1)), 503),
        )
        for respond, expected in cases:
            self.directory_response = respond
            response = self.directory("admin")
            self.assertEqual(response.status_code, expected, response.text)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertNotIn("example.test", response.text)

    # --------------------------------- Phase 5.5.3: GET /api/admin/users/{user_id}

    def details(self, target, name="admin", headers=None):
        hdrs = self.bearer(name) if headers is None else headers
        return self.client().get(f"/api/admin/users/{target}", headers=hdrs)

    def test_details_administrator_sees_full_record_with_reasons(self):
        response = self.details(self.target_full)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["user_id"], self.target_full)
        self.assertEqual(body["account"], {"status": "suspended", "reason": "Fictional restriction reason",
                                           "changed_at": "2026-11-26T12:00:00Z"})
        self.assertEqual(body["administrator"]["status_reason"], "Fictional admin note")
        self.assertEqual(body["administrator"]["granted_permissions"], ["audit.view", "users.view"])
        self.assertEqual([(m["actor"], m["position"], m["granted_permissions"]) for m in body["memberships"]],
                         [("innovation_center", "employee", ["innovation_center.inventions.view"]),
                          ("management", "head", [])])          # Head: no explicit grants
        self.assertEqual(body["memberships"][1]["status_reason"], "Fictional membership note")
        self.assertEqual(body["owned_invention_count"], 2)
        self.assertIsNone(body["last_sign_in_at"])

    def test_details_without_profile_and_nullable_fields(self):
        body = self.details(self.target_bare).json()
        self.assertEqual((body["has_profile"], body["full_name"], body["email"], body["registered_at"],
                          body["administrator"], body["memberships"]), (False, None, None, None, None, []))
        self.assertEqual(body["account"], {"status": "active", "reason": None, "changed_at": None})

    def test_details_admin_employee_never_sees_restriction_reasons(self):
        body = self.details(self.target_full, "staff").json()
        self.assertIsNone(body["account"]["reason"])
        self.assertIsNone(body["administrator"]["status_reason"])
        self.assertTrue(all(m["status_reason"] is None for m in body["memberships"]))
        # If the database unexpectedly returned reasons to an Admin Employee: fail closed.
        httpx = self.httpx
        self.details_response = lambda r: httpx.Response(200, json=self.detail_rows[self.target_full])
        response = self.details(self.target_full, "staff")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Fictional", response.text)

    def test_details_denied_callers_and_authentication(self):
        for name in ("staff_noview", "ordinary", "head", "employee"):
            self.assertEqual(self.details(self.target_full, name).status_code, 403, name)
        for status_value in ("suspended", "banned"):
            self.set_record("staff", lambda row, s=status_value: {
                "user_id": row["uid"], "account_status": s, "memberships": []})
            self.assertEqual(self.details(self.target_full, "staff").status_code, 403, status_value)
        self.assertEqual(self.details(self.target_full, headers={}).status_code, 401)
        self.assertEqual(self.details(self.target_full, "nobody").status_code, 401)
        self.assertEqual(self.directory_calls, [], "denied before any database request")

    def test_details_not_found_invalid_uuid_and_rpc_contract(self):
        import uuid
        response = self.details(str(uuid.uuid4()))
        self.assertEqual((response.status_code, response.headers["cache-control"]), (404, "no-store"))
        calls_before = len(self.directory_calls)
        for bad in ("not-a-uuid", "123", self.target_full + "x"):
            self.assertEqual(self.details(bad).status_code, 422, bad)
        self.assertEqual(len(self.directory_calls), calls_before, "no database call for malformed UUIDs")
        self.details(self.target_full.upper())                     # canonicalized before forwarding
        call = self.directory_calls[-1]
        self.assertEqual(call["args"], {"p_user_id": self.target_full})
        self.assertEqual(call["apikey"], "sb_publishable_test")
        self.assertEqual(call["authorization"], "Bearer " + self.token("admin"))
        self.assertFalse(any((c["apikey"] or "").startswith("sb_secret_") for c in self.directory_calls))

    def test_details_malformed_responses_and_errors_fail_closed(self):
        import copy
        httpx = self.httpx
        base = self.detail_rows[self.target_full]

        def variant(change):
            data = copy.deepcopy(base)
            change(data)
            return lambda r: httpx.Response(200, json=data)

        def unreachable(request):
            raise httpx.ConnectError("down", request=request)
        cases = (
            (variant(lambda d: d.update(user_id=self.target_bare)), 503),                 # another user
            (variant(lambda d: d.update(encrypted_password="x")), 503),                   # sensitive extra field
            (variant(lambda d: d.update(raw_user_meta_data={})), 503),
            (variant(lambda d: d["account"].update(token="x")), 503),                     # nested extra field
            (variant(lambda d: d["administrator"].update(granted_permissions=["root.all"])), 503),
            (variant(lambda d: d["memberships"][0].update(
                granted_permissions=["industry_liaison.matches.view"])), 503),            # cross-actor grant
            (variant(lambda d: d.update(memberships=[d["memberships"][0]] * 2)), 503),    # duplicate actor
            (variant(lambda d: d.update(has_profile=False)), 503),                        # inconsistent profile
            (variant(lambda d: d.update(owned_invention_count=-1)), 503),
            (variant(lambda d: d["account"].update(status="deleted")), 503),
            (variant(lambda d: d.pop("account")), 503),
            (lambda r: httpx.Response(200, content=b"null", headers={"Content-Type": "application/json"}), 503),
            (lambda r: httpx.Response(200, json=[base]), 503),
            (lambda r: httpx.Response(500, json={}), 503),
            (lambda r: httpx.Response(404, json={"code": "PGRST202"}), 503),
            (unreachable, 503),
            (lambda r: httpx.Response(403, json={"code": "42501"}), 403),                 # database refuses caller
            (lambda r: httpx.Response(400, json={"code": "22023"}), 400),
            (lambda r: httpx.Response(401, json={}), 401),
        )
        for respond, expected in cases:
            self.details_response = respond
            response = self.details(self.target_full)
            self.assertEqual(response.status_code, expected, response.text)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertNotIn("Fictional", response.text)
            self.assertNotIn("example.test", response.text)


# --------------------------------------------------------------------------
# Mock data consistency (Node)
# --------------------------------------------------------------------------

@unittest.skipUnless(NODE, "Node.js not installed")
class MockDataConsistencyTests(unittest.TestCase):
    def test_records_are_internally_consistent(self):
        program = ("const window = {};\n" + read(IC / "js" / "data" / "mock-data.js") + "\n" +
                   read(IC / "js" / "data" / "repository.js") + r"""
const D = window.IC_MOCK_DATA, R = window.ICData, problems = [];
const idx = Object.fromEntries(D.stages.map((s, i) => [s.id, i]));
const expected = {registered: ['not_submitted'], ai_profile: ['not_submitted'], submitted: ['awaiting'],
  review: ['in_review', 'clarification', 'on_hold']};
for (const inv of D.inventions) {
  const allowed = expected[inv.stage] || ['verified'];
  if (!allowed.includes(inv.reviewStatus)) problems.push(`${inv.id}: ${inv.stage}/${inv.reviewStatus}`);
  if ((inv.submitted === null) !== (inv.reviewStatus === 'not_submitted')) problems.push(`${inv.id}: submitted`);
  if (inv.assessedTrl && inv.reviewStatus !== 'verified') problems.push(`${inv.id}: assessed TRL before verification`);
  if (D.matches[inv.id] && idx[inv.stage] < idx.match_review) problems.push(`${inv.id}: matches before match review`);
  if (!D.matches[inv.id] && idx[inv.stage] >= idx.match_review) problems.push(`${inv.id}: missing matches`);
  if (inv.latest.date > D.asOf) problems.push(`${inv.id}: future activity`);
}
for (const [id, list] of Object.entries(D.matches)) for (const m of list) {
  const values = D.criteria.map(c => m.scores[c.id]);
  if (Math.round(values.reduce((a, b) => a + b, 0) / 6) !== m.overall) problems.push(`${id}/${m.id}: overall`);
}
console.log(JSON.stringify({problems, queue: R.reviewQueue().length,
  pending: R.pendingReviews().map(i => i.id), attention: R.attention().map(i => i.id),
  strongestA: R.matchesFor('s05')[0].strongest, exports: Object.keys(R).sort()}));
""")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.js"
            path.write_text(program, encoding="utf-8")
            done = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["queue"], 12)
        self.assertEqual(out["strongestA"], {"id": "technology_fit", "label": "Technology fit", "value": 88})
        self.assertEqual(out["pending"], ["s07", "s04", "tdw", "rl3"])           # oldest first
        self.assertEqual(out["attention"], ["rl3", "s03", "s06", "s07"])
        self.assertNotIn("stats", out["exports"])


# --------------------------------------------------------------------------
# Real-browser checks
# --------------------------------------------------------------------------

HARNESS = r"""<!DOCTYPE html><html><body><pre id="out">pending</pre>
<iframe id="f" style="width:__W__px;height:1400px;border:0"></iframe>
<script>
const out = {}; const frame = document.getElementById('f');
const base = '__BASE__';
const wait = ms => new Promise(r => setTimeout(r, ms));
async function open(path) { frame.src = base + path; await new Promise(r => frame.onload = r);
  await wait(200); return frame.contentWindow; }
function setValue(win, input, value, type) { input.value = value;
  input.dispatchEvent(new win.Event(type || 'input', {bubbles: true})); }
function nonLocal(win) { return win.performance.getEntriesByType('resource').map(r => r.name)
  .filter(u => !u.startsWith('file:')); }
(async () => {
  try { await (__SCRIPT__)(); } catch (e) { out.error = String(e && e.stack || e); }
  document.getElementById('out').textContent = JSON.stringify(out);
})();
</script></body></html>"""


@unittest.skipUnless(BROWSER, "Chrome or Edge not installed")
class BrowserTests(unittest.TestCase):
    def run_in_browser(self, width, script):
        html = (HARNESS.replace("__W__", str(width)).replace("__BASE__", IC.as_uri() + "/")
                .replace("__SCRIPT__", script))
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / "harness.html"
            page.write_text(html, encoding="utf-8")
            done = subprocess.run(
                [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={Path(folder) / 'profile'}", "--allow-file-access-from-files",
                 "--virtual-time-budget=20000", "--dump-dom", page.as_uri()],
                capture_output=True, text=True, encoding="utf-8", timeout=180)
        match = re.search(r'<pre id="out">(.*?)</pre>', done.stdout, re.S)
        self.assertIsNotNone(match, done.stderr[-2000:])
        raw = (match.group(1).replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
               .replace("&amp;", "&"))
        result = json.loads(raw)
        self.assertNotIn("error", result, result.get("error"))
        return result

    def test_overview_placeholders_and_work_lists(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('overview.html'); const d = win.document;
  out.h1 = d.querySelector('h1').textContent;
  out.summary = [...d.querySelectorAll('.placeholder-kpi')].map(k => [
    k.querySelector('.kpi-label').textContent, k.querySelector('.kpi-empty').textContent]);
  out.digitsInSummary = /\d/.test(d.querySelector('.kpi-grid').textContent);
  out.trends = [...d.querySelectorAll('.placeholder')].map(t => [t.querySelector('h3').textContent,
    t.querySelector('button').textContent, t.querySelector('button').disabled,
    t.querySelector('.coming-soon-note').textContent]);
  out.graphics = d.querySelectorAll('svg, canvas, figure.chart').length;
  out.pending = d.querySelectorAll('#pending-h ~ ul li').length;
  out.lists = [...d.querySelectorAll('section.panel h2')].map(h => h.textContent);
  out.quick = [...d.querySelectorAll('.quick-links a')].map(a => a.getAttribute('href'));
  out.current = d.querySelector('.ic-nav a[aria-current="page"]').textContent;
  out.network = nonLocal(win);
}""")
        self.assertEqual(out["h1"], "Innovation Center overview")
        self.assertEqual(out["summary"], [[label, "Not available yet"] for label in (
            "Total inventions", "Profiles awaiting institutional review",
            "Institutionally verified inventions", "Inventions requiring clarification",
            "Rejected or on-hold inventions", "Inventions in the matching stage",
            "Active industry engagements")])
        self.assertFalse(out["digitsInSummary"], "no fictional numbers in the summary")
        self.assertEqual(out["trends"], TRENDS)
        self.assertEqual(out["graphics"], 0)
        self.assertEqual(out["pending"], 4)
        self.assertEqual(out["lists"], ["Pending verification tasks", "Inventions requiring attention",
                                        "Recent review activity"])
        self.assertEqual(out["quick"], ["profile-approvals.html", "portfolio.html"])
        self.assertEqual(out["current"], "Overview")
        self.assertEqual(out["network"], [])

    def test_profile_approvals_queue(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('profile-approvals.html'); const d = win.document;
  const rows = () => [...d.querySelectorAll('.queue-table tbody tr')].filter(r => r.querySelector('a'));
  out.total = rows().length;
  setValue(win, d.getElementById('queue-search'), 'tidewell'); await wait(50);
  out.search = rows().map(r => r.querySelector('th').textContent);
  setValue(win, d.getElementById('queue-search'), ''); await wait(50);
  setValue(win, d.getElementById('queue-status'), 'awaiting', 'change'); await wait(50);
  out.awaiting = rows().length;
  setValue(win, d.getElementById('queue-status'), '', 'change');
  setValue(win, d.getElementById('queue-search'), 'zzz'); await wait(50);
  out.empty = d.querySelector('.queue-table .empty').textContent;
  d.querySelector('.filters button').click(); await wait(50);
  out.cleared = rows().length;
  const sort = [...d.querySelectorAll('th button.sort')].find(b => b.textContent.startsWith('Invention'));
  sort.click(); await wait(50);
  out.first = rows()[0].querySelector('th').textContent;
  out.href = rows()[0].querySelector('a').getAttribute('href');
  out.columns = [...d.querySelectorAll('.queue-table thead th')].map(t => t.textContent.replace(/[▲▼]/g, '').trim());
}""")
        self.assertEqual(out["total"], 12)
        self.assertEqual(out["search"], ["Tidewell Solar Desalination Cartridge"])
        self.assertEqual(out["awaiting"], 3)
        self.assertEqual(out["empty"], "No submissions match these filters.")
        self.assertEqual(out["cleared"], 12)
        self.assertTrue(out["first"].startswith("RainLattice"))
        self.assertEqual(out["href"], "profile-approvals.html?review=rl3")
        self.assertEqual(out["columns"], [
            "Invention", "Inventor", "Technical domain", "Declared TRL", "AI-estimated TRL",
            "Confidentiality", "Submitted", "Verification status", "Review action"])

    def test_review_workspace_keeps_every_feature(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('profile-approvals.html?review=rl3'); const d = win.document;
  out.h1 = d.querySelector('h1').textContent;
  out.sections = d.querySelectorAll('.report-section').length;
  out.notVerified = d.body.textContent.includes('Innovator-submitted — not institutionally verified');
  const cite = d.querySelector('.report-view .cite'); const n = Number(cite.textContent.replace(/\D/g, ''));
  cite.click(); await wait(50);
  const viewer = d.getElementById('evidence-viewer');
  out.viewer = [viewer.querySelector('h4').textContent.split(':')[0], n, viewer.querySelectorAll('mark').length];
  out.headings = [...d.querySelectorAll('.evidence-panel h3, .assessment-panel h3')].map(h => h.textContent);
  out.registration = [...d.querySelectorAll('.evidence-panel table')][0].querySelectorAll('tbody tr').length;
  out.consistent = [...d.querySelectorAll('.evidence-panel table')][0].textContent.includes('Consistent');
  out.contradiction = [...d.querySelectorAll('.alert-list li')].some(li => li.textContent.includes('every 4 months'));
  out.trlKinds = [...d.querySelectorAll('.trl-kind')].map(t => t.textContent);
  out.kinds = [...d.querySelectorAll('.evidence-kinds dt')].map(t => t.textContent);
  out.outcomes = [...d.querySelectorAll('.outcomes button')].map(b => [b.textContent, b.disabled]);
  out.checklist = d.querySelectorAll('.check-item').length;
  d.getElementById('check-identity-supported').click(); await wait(20);
  out.progress = d.querySelector('.progress').textContent;
  out.back = d.querySelector('.back-link').getAttribute('href');
  out.network = nonLocal(win);
}""")
        self.assertTrue(out["h1"].startswith("RainLattice R3"))
        self.assertEqual(out["sections"], 15)
        self.assertTrue(out["notVerified"])
        self.assertEqual(out["viewer"][0], f"Source [{out['viewer'][1]}]")
        self.assertGreater(out["viewer"][2], 0)
        for heading in ("Source documents", "Evidence viewer", "Registration details vs AI report",
                        "Document coverage by report section", "Contradictions and discrepancies",
                        "Missing or partly documented information",
                        "Experimental results and technical limitations",
                        "Technology readiness (TRL)", "IP and ownership evidence",
                        "Human verification checklist", "Reviewer notes", "Verification status"):
            self.assertIn(heading, out["headings"])
        self.assertEqual(out["registration"], 4)
        self.assertTrue(out["consistent"])
        self.assertTrue(out["contradiction"])
        self.assertEqual(out["trlKinds"], ["Declared by innovator", "AI-estimated", "Staff-assessed"])
        self.assertEqual(out["kinds"], ["Supported by uploaded documents",
                                        "Independently validated by the institution",
                                        "Unverified or insufficient evidence"])
        self.assertEqual(out["outcomes"], [["Verified", True], ["Request clarification", True],
                                           ["Rejected / On hold", True]])
        self.assertEqual(out["checklist"], 10)
        self.assertEqual(out["progress"], "1 of 10 checklist items assessed")
        self.assertEqual(out["back"], "profile-approvals.html")
        self.assertEqual(out["network"], [])

    def test_portfolio_table_progress_and_not_matched(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('portfolio.html?id=s09'); const d = win.document;
  const rows = [...d.querySelectorAll('.portfolio-table tbody tr')];
  out.rows = rows.length;
  out.headers = d.querySelectorAll('.portfolio-table thead th').length;
  out.notMatched = rows.filter(r => r.textContent.includes('Not matched yet')).length;
  const s05 = rows.find(r => r.textContent.includes('Bamboo'));
  out.s05 = [...s05.cells].slice(9, 13).map(c => c.textContent);
  out.detail = d.querySelector('#portfolio-detail h2').textContent;
  out.current = d.querySelector('.stepper li[aria-current="step"]').textContent;
  out.done = d.querySelectorAll('#portfolio-detail .stepper li.done').length;
  rows.find(r => r.textContent.includes('Soil Moisture')).querySelector('button').click(); await wait(50);
  out.blocked = d.querySelector('.stepper li.blocked').textContent;
  out.notMatchedText = d.querySelector('#portfolio-detail .not-matched').textContent;
  out.url = win.location.search;
  out.trends = [...d.querySelectorAll('.placeholder')].map(t => [t.querySelector('h3').textContent,
    t.querySelector('button').textContent, t.querySelector('button').disabled,
    t.querySelector('.coming-soon-note').textContent]);
  out.graphics = d.querySelectorAll('svg, canvas, figure.chart').length;
  rows.find(r => r.textContent.includes('ECG')).querySelector('button').click(); await wait(50);
  out.criteria = [...d.querySelectorAll('#portfolio-detail .criteria-table tbody tr')].map(r => r.textContent);
  setValue(win, d.getElementById('portfolio-stage'), 'licensed', 'change'); await wait(30);
  out.filtered = d.querySelectorAll('.portfolio-table tbody tr').length;
}""")
        self.assertEqual(out["rows"], 14)
        self.assertEqual(out["headers"], 15)
        self.assertEqual(out["notMatched"], 10)
        self.assertEqual(out["s05"], ["4", "Sample Company A (fictional)", "82/100", "Technology fit (88)"])
        self.assertEqual(out["detail"], "Sample: Low-cost ECG Patch")
        self.assertTrue(out["current"].startswith("Negotiation"))
        self.assertEqual(out["done"], 8)
        self.assertIn("needs clarification", out["blocked"])
        self.assertIn("Not matched yet", out["notMatchedText"])
        self.assertEqual(out["url"], "?id=s03")                    # refresh reopens the same detail
        self.assertEqual(out["trends"], TRENDS)
        self.assertEqual(out["graphics"], 0)
        self.assertEqual(len(out["criteria"]), 6)
        self.assertTrue(out["criteria"][0].startswith("Technology fit Strongest"))
        self.assertEqual(out["filtered"], 1)

    def test_match_review_ranking_detail_comparison_and_empty_state(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('match-review.html'); const d = win.document;
  out.callout = d.querySelector('.preview-callout').textContent;
  const names = () => [...d.querySelectorAll('.partner-open')].map(b => b.textContent);
  out.ranked = names();
  out.detail = d.querySelector('#partner-h').textContent;
  out.criteria = d.querySelectorAll('#partner-detail .criteria-table tbody tr').length;
  out.strongest = d.querySelector('#partner-detail .criteria-table tr.strongest').textContent;
  out.score = d.querySelector('#partner-detail .score-pill').textContent;
  out.sections = [...d.querySelectorAll('#partner-detail h3')].map(h => h.textContent);
  out.actions = [...d.querySelectorAll('#partner-detail .outcomes button')].map(b => [b.textContent, b.disabled]);
  [...d.querySelectorAll('.partner-open')][1].click(); await wait(30);
  out.detail2 = d.querySelector('#partner-h').textContent;
  out.compareDisabled = [...d.querySelectorAll('button')].find(b => b.textContent.startsWith('Compare selected')).disabled;
  d.getElementById('compare-A').click(); await wait(30);
  d.getElementById('compare-C').click(); await wait(30);
  out.compareHeaders = [...d.querySelectorAll('.compare-table thead th')].map(t => t.textContent);
  out.graphics = d.querySelectorAll('svg, canvas, figure.chart').length;
  setValue(win, d.getElementById('rank-by'), 'geographic_proximity', 'change'); await wait(30);
  out.byProximity = names()[0];
  setValue(win, d.getElementById('invention-select'), 's11', 'change'); await wait(30);
  out.empty = d.querySelector('main section.panel h2').textContent;
  out.url = win.location.search;
  out.noNull = !d.getElementById('main').textContent.includes('null');
  out.network = nonLocal(win);
}""")
        self.assertIn("No matching has been run", out["callout"])
        self.assertEqual(out["ranked"], ["1. Sample Company A", "2. Sample Company B",
                                         "3. Sample Fund C", "4. Sample Company D"])
        self.assertEqual(out["detail"], "Sample Company A")
        self.assertEqual(out["criteria"], 6)
        self.assertTrue(out["strongest"].startswith("Technology fit"))
        for heading in ("Six-criterion score breakdown", "Why this partner?", "Relevant source evidence",
                        "Market-signal timeline", "Risk and conflict flags", "Decision (future)"):
            self.assertIn(heading, out["sections"])
        self.assertEqual(out["actions"], [["Shortlist", True], ["Approve for outreach", True],
                                          ["Reject with reason", True]])
        self.assertEqual(out["detail2"], "Sample Company B")
        self.assertTrue(out["compareDisabled"])
        self.assertEqual(out["compareHeaders"], ["Criterion", "Sample Company A", "Sample Fund C"])
        self.assertEqual(out["graphics"], 0)
        self.assertEqual(out["score"], "82/100")
        self.assertTrue(out["byProximity"].endswith("Sample Company B"))
        self.assertEqual(out["empty"], "Not matched yet")
        self.assertEqual(out["url"], "?invention=s11")
        self.assertTrue(out["noNull"])
        self.assertEqual(out["network"], [])

    def test_offline_pages_show_no_role_switcher(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('overview.html'); const d = win.document;
  const host = d.getElementById('roleSwitcher');
  out.hidden = host.hidden; out.children = host.children.length;
  out.account = d.getElementById('accountName').textContent;
  out.back = d.querySelector('.ic-nav .nav-back').getAttribute('href');
}""")
        self.assertEqual((out["hidden"], out["children"]), (True, 0))
        self.assertEqual(out["account"], "Not signed in (offline file)")
        self.assertEqual(out["back"], "/dashboard")

    def test_role_switcher_shows_only_server_authorized_interfaces(self):
        # The page's Supabase client and fetch are stubbed: the switcher must
        # use only what GET /api/access/me returns for the signed-in account.
        script = r"""async () => {
  const SWITCHER = '__SWITCHER__';
  const I = {
    innovator: {id: 'innovator', label: 'Innovator / Researcher', href: '/dashboard', available: true},
    admin: {id: 'administrator', label: 'Administrator', href: '/admin/overview.html', available: true},
    staff: {id: 'administrator', label: 'Admin Employee', href: '/admin/overview.html', available: true},
    ic: {id: 'innovation_center', label: 'Innovation Center',
         href: '/institutional/innovation-center/overview.html', available: true},
    il: {id: 'industry_liaison', label: 'Industry Liaison', href: null, available: false}};
  const me = (user, list, wait) => ({status: 200, wait, body: {user_id: user, account_status: 'active',
                                                              interfaces: list}});
  const icSession = {status: 200, body: {user_id: 'U1', actors: {innovation_center: {}},
                                         expires_at: Date.now() / 1000 + 900}};
  async function mount(role, plan, settle) {
    window.currentPlan = plan;
    frame.srcdoc = `<!DOCTYPE html><html><body data-role="${role}"><header>
      <div id="roleSwitcher"></div><button id="logoutButton" type="button">Sign out</button></header>
      <div class="dev-banner">banner</div><div class="app"><p id="content">content</p></div>
      <script>
        window.plan = parent.currentPlan; window.calls = []; window.authCallbacks = [];
        window.getSupabase = async () => ({auth: {
          getSession: async () => ({data: {session: window.plan.user
            ? {access_token: 'test-token', user: {id: window.plan.user}} : null}}),
          onAuthStateChange: cb => { window.authCallbacks.push(cb);
                                     return {data: {subscription: {unsubscribe() {}}}}; }}});
        window.fetch = async (url, options) => {
          const method = (options && options.method) || 'GET';
          window.calls.push([String(url), method,
                             Boolean(options && options.headers && options.headers.Authorization)]);
          const answer = window.plan.respond(String(url), method, window.plan.user) || {status: 404, body: {}};
          if (answer.wait) await new Promise(r => setTimeout(r, answer.wait));
          return new Response(answer.status === 204 ? null : JSON.stringify(answer.body || {}),
                              {status: answer.status,
                              headers: {'Content-Type': 'application/json'}});
        };
      <\/script><script src="${SWITCHER}"><\/script></body></html>`;
    await new Promise(r => frame.onload = r);
    await wait(settle || 400);
    return frame.contentWindow;
  }
  const state = win => { const d = win.document, host = d.getElementById('roleSwitcher');
    return {hidden: host.hidden, links: [...host.querySelectorAll('a')].map(a => [a.textContent, a.getAttribute('href')]),
            locked: Boolean(d.getElementById('interfaceLocked')), content: Boolean(d.getElementById('content'))}; };

  // Ordinary Innovator: no switcher at all.
  let win = await mount('innovator', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator]) : null});
  out.ordinary = state(win);

  // Administrator: hidden while pending, then Innovator + Administrator only.
  win = await mount('innovator', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator, I.admin, I.il], 1500) : null}, 300);
  out.pending = state(win).hidden;
  await wait(1700);
  out.admin = state(win);
  const d = win.document, button = d.querySelector('.role-switcher-button');
  out.label = button.textContent;
  button.click(); await wait(20);
  out.expanded = button.getAttribute('aria-expanded');
  out.focus = d.activeElement.dataset.interfaceId;
  d.activeElement.dispatchEvent(new win.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));
  out.focusNext = d.activeElement.dataset.interfaceId;
  d.activeElement.dispatchEvent(new win.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  out.closed = d.querySelector('.role-switcher-panel').hidden && d.activeElement === button;
  // Sign-out: the existing sign-out handlers call this shared helper, which
  // ends both server UI sessions and waits for confirmation.
  win.plan.respond = (url, method) => method === 'DELETE' ? {status: 204} : null;
  const ended = await win.ProfileMatchUISessions.end();
  out.logoutConfirmed = ended.confirmed;
  out.logout = win.calls.filter(c => c[1] === 'DELETE').map(c => c[0]).sort();
  out.tokenInUrl = win.calls.some(c => c[0].includes('test-token'));
  out.bearerTo = [...new Set(win.calls.filter(c => c[2]).map(c => c[0]))];

  // Admin Employee label comes from the server.
  win = await mount('administrator', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator, I.staff]) : null});
  out.staff = state(win).links;

  // Innovation Center member on the Innovation Center page.
  win = await mount('innovation-center', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator, I.ic]) : (url === '/institutional/session' ? icSession : null)});
  out.ic = state(win);
  out.icCurrent = win.document.querySelector('.role-switcher-current').textContent;

  // Authorization unavailable: hidden.
  win = await mount('innovator', {user: 'U1', respond: url => url === '/api/access/me'
    ? {status: 503, body: {}} : null});
  out.unavailable = state(win);

  // Membership revoked while on the page: content removed, UI sessions ended.
  win = await mount('innovation-center', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator]) : (url === '/institutional/session' ? icSession : null)});
  out.revoked = state(win);
  out.revokedCalls = win.calls.filter(c => c[1] === 'DELETE').map(c => c[0]).sort();

  // Institutional UI session expired: content removed.
  win = await mount('innovation-center', {user: 'U1', respond: url => url === '/api/access/me'
    ? me('U1', [I.innovator, I.ic]) : (url === '/institutional/session' ? {status: 401, body: {}} : null)});
  out.expired = [state(win), win.document.querySelector('#interfaceLocked h1').textContent];

  // A slow response for the previous account never renders for the new one.
  win = await mount('innovator', {user: 'U1', respond: (url, m, user) => url === '/api/access/me'
    ? me('U1', [I.innovator, I.admin], 800) : null}, 100);
  win.plan.user = 'U2';
  await wait(1200);
  out.stale = state(win);

  // Account switch after the list is shown: hidden, sessions ended, re-checked.
  win = await mount('innovator', {user: 'U1', respond: (url, m, user) => url === '/api/access/me'
    ? me(user, user === 'U1' ? [I.innovator, I.admin] : [I.innovator]) : null});
  out.beforeSwitch = state(win).links.length;
  win.plan.user = 'U2';
  win.authCallbacks.forEach(cb => cb('SIGNED_IN', {user: {id: 'U2'}}));
  await wait(400);
  out.afterSwitch = state(win);
  out.switchCalls = win.calls.filter(c => c[1] === 'DELETE').map(c => c[0]).sort();
}""".replace("__SWITCHER__", (FRONTEND / "js" / "role-switcher.js").as_uri())
        out = self.run_in_browser(1440, script)
        hidden = {"hidden": True, "links": [], "locked": False, "content": True}
        sessions = ["/admin/session", "/institutional/session"]
        self.assertEqual(out["ordinary"], hidden)
        self.assertTrue(out["pending"])
        self.assertEqual(out["admin"]["links"], [["Innovator / Researcher Current", "/dashboard"],
                                                 ["Administrator", "/admin/overview.html"]])
        self.assertFalse(out["admin"]["hidden"])
        self.assertEqual(out["label"], "Switch interfaceInnovator / Researcher ▾")
        self.assertEqual(out["expanded"], "true")
        self.assertEqual((out["focus"], out["focusNext"]), ("innovator", "administrator"))
        self.assertTrue(out["closed"])
        self.assertEqual(out["logout"], sessions)
        self.assertTrue(out["logoutConfirmed"])
        self.assertFalse(out["tokenInUrl"])
        self.assertEqual(out["bearerTo"], ["/api/access/me"])
        self.assertEqual(out["staff"], [["Innovator / Researcher", "/dashboard"],
                                        ["Admin Employee Current", "/admin/overview.html"]])
        self.assertEqual(out["ic"]["links"], [
            ["Innovator / Researcher", "/dashboard"],
            ["Innovation Center Current", "/institutional/innovation-center/overview.html"]])
        self.assertEqual((out["ic"]["locked"], out["ic"]["content"]), (False, True))
        self.assertEqual(out["icCurrent"], "Innovation Center")
        self.assertEqual(out["unavailable"], hidden)
        self.assertEqual(out["revoked"], {"hidden": True, "links": [], "locked": True, "content": False})
        self.assertEqual(out["revokedCalls"], sessions)
        self.assertEqual(out["expired"][0]["content"], False)
        self.assertEqual(out["expired"][1], "Session ended")
        self.assertEqual(out["stale"], hidden)
        self.assertEqual(out["beforeSwitch"], 2)
        self.assertEqual(out["afterSwitch"], hidden)
        self.assertEqual(out["switchCalls"], sessions)

    def test_mobile_layouts_do_not_scroll_sideways(self):
        out = self.run_in_browser(390, r"""async () => {
  out.overflow = {};
  for (const path of ['overview.html', 'profile-approvals.html', 'profile-approvals.html?review=tdw',
                      'portfolio.html', 'match-review.html']) {
    const win = await open(path); const d = win.document;
    out.overflow[path] = d.documentElement.scrollWidth - d.documentElement.clientWidth;
  }
  const win = await open('profile-approvals.html?review=rl3'); const d = win.document;
  const tab = d.getElementById('tab-report'); tab.focus();
  tab.dispatchEvent(new win.KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true})); await wait(20);
  out.tab = d.activeElement.id;
  d.getElementById('tab-report').click(); d.querySelector('.report-view .cite').click(); await wait(30);
  out.afterCite = d.querySelector('[role="tab"][aria-selected="true"]').id;
}""")
        for path, overflow in out["overflow"].items():
            self.assertLessEqual(overflow, 0, path)
        self.assertEqual(out["tab"], "tab-evidence")
        self.assertEqual(out["afterCite"], "tab-evidence")


if __name__ == "__main__":
    unittest.main()
