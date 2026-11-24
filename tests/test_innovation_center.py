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
        for path in [*IC_JS, FRONTEND / "js" / "role-switcher.js"]:
            if path.name == "sample-reports.js":
                continue
            self.assertEqual(forbidden.findall(read(path)), [], path.name)

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
        self.assertEqual(stripped.replace("\r\n", "\n"), head.stdout.replace("\r\n", "\n"))

    def test_protected_auth_files_untouched_by_roles(self):
        for name in ("js/auth.js", "js/api.js", "js/dashboard.js", "login.html",
                     "invention_report.html"):
            text = read(FRONTEND / name)
            self.assertNotIn("role-switcher", text, name)
            self.assertNotIn("roles/", text, name)
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            self.assertNotIn("roles/innovation-center", read(path), path.name)

    def test_switcher_roles_and_links(self):
        text = read(FRONTEND / "js" / "role-switcher.js")
        ids = re.findall(r"\{id: '([a-z-]+)', label:", text)
        self.assertEqual(ids, ["innovator", "innovation-center", "industry-liaison",
                               "management", "administrator", "industry-partner"])
        self.assertEqual(text.count("comingSoon: true"), 4)
        self.assertIn("href: '/dashboard'", text)
        self.assertIn("href: '/assets/roles/innovation-center/index.html'", text)


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

    def test_role_switcher_menu_and_keyboard(self):
        out = self.run_in_browser(1440, r"""async () => {
  const win = await open('overview.html'); const d = win.document;
  const button = d.querySelector('.role-switcher-button');
  out.label = button.textContent;
  out.expandedBefore = button.getAttribute('aria-expanded');
  button.click(); await wait(20);
  out.expanded = button.getAttribute('aria-expanded');
  const links = [...d.querySelectorAll('.role-switcher-panel a')];
  out.links = links.map(a => [a.textContent, a.getAttribute('href')]);
  out.current = d.querySelector('.role-switcher-panel a[aria-current="page"]').dataset.roleId;
  out.focus = d.activeElement.dataset.roleId;
  d.activeElement.dispatchEvent(new win.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));
  out.focusNext = d.activeElement.dataset.roleId;
  d.activeElement.dispatchEvent(new win.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  out.closed = d.querySelector('.role-switcher-panel').hidden;
  out.focusBack = d.activeElement === button;
  out.account = d.getElementById('accountName').textContent;
  out.back = d.querySelector('.ic-nav .nav-back').getAttribute('href');
  const soon = await open('../management/index.html');
  out.soonCurrent = soon.document.querySelector('.role-switcher-current').textContent;
}""")
        self.assertEqual(out["label"], "Switch roleInnovation Center ▾")
        self.assertEqual((out["expandedBefore"], out["expanded"]), ("false", "true"))
        self.assertEqual(out["links"], [
            ["Innovator / Researcher", "/dashboard"],
            ["Innovation Center Current", "/assets/roles/innovation-center/index.html"],
            ["Industry Liaison Office Coming soon", "/assets/roles/industry-liaison/index.html"],
            ["Management / Executive Coming soon", "/assets/roles/management/index.html"],
            ["Administrator Coming soon", "/assets/roles/administrator/index.html"],
            ["Industry Partner Coming soon", "/assets/roles/industry-partner/index.html"]])
        self.assertEqual(out["current"], "innovation-center")
        self.assertEqual(out["focus"], "innovation-center")
        self.assertEqual(out["focusNext"], "industry-liaison")
        self.assertTrue(out["closed"])
        self.assertTrue(out["focusBack"])
        self.assertEqual(out["account"], "Not signed in (offline file)")
        self.assertEqual(out["back"], "/dashboard")
        self.assertEqual(out["soonCurrent"], "Management / Executive")

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
