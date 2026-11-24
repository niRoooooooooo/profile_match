"""View mode / Edit mode tests: the page's REAL functions run in Node.js.

A report rendered by the real Python renderer (fictional Glowfern data) is
fed to the browser code with a minimal fake DOM. No browser, no network.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_frontend_report import extract_function, inline_script
from test_report_renderer import glowfern_profile

from app.services.report_renderer import render_report_json

NODE = shutil.which("node")
FUNCTIONS = ("elem", "getAt", "setAt", "applySingleEdit", "applyListEdit", "statusHint",
             "openSource", "annotate", "sectionHeading", "renderView", "addLink",
             "makeFieldEditor", "renderEdit", "updateVersionLine")

FAKE_DOM = r"""
class Node {
  constructor(tag){ this.tag=tag; this.children=[]; this.className=''; this._text='';
    this.attrs={}; this.listeners={}; this.value=''; this.hidden=false; this.parent=null;
    this.id=''; this.href=''; this.open=false; this.title='';
    this.classList={ toggle:(c,on)=>{ const s=new Set(this.className.split(' ').filter(Boolean));
      on?s.add(c):s.delete(c); this.className=[...s].join(' '); } }; }
  set textContent(v){ this._text=String(v); this.children=[]; }
  get textContent(){ return this._text + this.children.map(c=>c.textContent).join(''); }
  append(...nodes){ for(const n of nodes){ n.parent=this; this.children.push(n); } }
  replaceChildren(...nodes){ this.children=[]; this.append(...nodes); }
  remove(){ if(this.parent){ this.parent.children.splice(this.parent.children.indexOf(this),1); this.parent=null; } }
  setAttribute(k,v){ this.attrs[k]=v; }
  addEventListener(t,f){ (this.listeners[t] ||= []).push(f); }
  dispatch(t){ (this.listeners[t]||[]).forEach(f=>f({target:this, preventDefault(){} })); }
  focus(){} scrollIntoView(){}
  findAll(pred,out=[]){ if(pred(this))out.push(this); this.children.forEach(c=>c.findAll(pred,out)); return out; }
}
const document={ createElement: tag=>new Node(tag),
  createTextNode: text=>{ const n=new Node('#text'); n._text=String(text); return n; } };
const sections=new Node('div');
const $=id=>sections.findAll(n=>n.id===id)[0]||null;
let dirty=0; function markDirty(){ dirty++; }
let submissionCount=null; let currentReport=null;
const all=pred=>sections.findAll(pred);
"""


@unittest.skipUnless(NODE, "Node.js not installed")
class ReportModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = glowfern_profile().model_dump(mode="json")
        cls.profile["problem_solution"]["solution"] = None    # an empty field to "+ Add"
        cls.report = render_report_json(cls.profile, {"generation_number": 1})
        source = inline_script()
        constant = re.search(r"const INNOVATOR_EDIT='[^']*';", source).group(0)
        cls.functions = constant + "\n" + "\n".join(extract_function(source, n) for n in FUNCTIONS)

    def run_node(self, body: str) -> dict:
        program = (FAKE_DOM + self.functions
                   + f"\nlet workingProfile={json.dumps(self.profile)};\n"
                   + f"const report={json.dumps(self.report)};\n" + body)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "modes.js"
            path.write_text(program, encoding="utf-8")
            done = subprocess.run([NODE, str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    # ---------------- edit rules (pure functions) ----------------

    def test_list_edit_keeps_unchanged_claims_and_marks_new_lines(self):
        out = self.run_node(r"""
const claims = workingProfile.technology.components;
const original = claims.map(c => c.value);
const edited = applyListEdit(claims, [original[1], '  ', 'Brand new part', original[0]].join('\n'));
console.log(JSON.stringify({
  values: edited.map(c => c.value),
  keptSameObjects: edited[0] === claims[1] && edited[2] === claims[0],
  keptEvidence: edited[0].evidence.length > 0 && edited[0].classification === 'document_fact',
  added: edited[1], removed: original[2]
}));
""")
        self.assertEqual(out["values"][1], "Brand new part")
        self.assertEqual(len(out["values"]), 3)               # deleted lines removed
        self.assertNotIn(out["removed"], out["values"])
        self.assertTrue(out["keptSameObjects"])
        self.assertTrue(out["keptEvidence"])                  # citations survive reordering
        self.assertEqual(out["added"]["classification"], "inference")
        self.assertEqual(out["added"]["evidence"], [])
        self.assertTrue(out["added"]["explanation"].startswith("Innovator-edited statement"))

    def test_single_edit_never_creates_a_verified_fact(self):
        out = self.run_node(r"""
const claim = JSON.parse(JSON.stringify(workingProfile.development.prototype_status));
const before = claim.classification;
applySingleEdit(claim, ' Lab prototype v2 ');
const edited = JSON.parse(JSON.stringify(claim));
applySingleEdit(claim, '   ');
console.log(JSON.stringify({before, edited, cleared: claim}));
""")
        self.assertEqual(out["before"], "document_fact")
        self.assertEqual(out["edited"]["value"], "Lab prototype v2")
        self.assertEqual(out["edited"]["classification"], "inference")
        self.assertEqual(out["edited"]["evidence"], [])
        self.assertEqual(out["cleared"]["classification"], "missing")
        self.assertIsNone(out["cleared"]["value"])

    # ---------------- view mode ----------------

    def test_view_mode_is_a_document_not_a_form(self):
        out = self.run_node(r"""
renderView(report);
const ids = new Set(all(n => n.className === 'source-entry').map(n => n.id));
const cites = all(n => n.className === 'cite');
console.log(JSON.stringify({
  h1: all(n => n.tag === 'h1').map(n => n.textContent),
  h2: all(n => n.tag === 'h2').map(n => n.textContent),
  textareas: all(n => n.tag === 'textarea').length,
  inputs: all(n => n.tag === 'input').length,
  itemLabels: all(n => /^Item \d/.test(n._text)).length,
  classificationLines: all(n => /AI classification/.test(n._text)).length,
  unverifiedBadges: all(n => (n.className||'').includes('badge unverified')).map(n => n.textContent),
  citesResolve: cites.length > 0 && cites.every(a => ids.has(a.href.slice(1))),
  notes: all(n => n.className === 'doc-note').map(n => n.textContent),
  tables: all(n => n.tag === 'table').length,
  notice: all(n => n.className === 'doc-notice').map(n => n.textContent)
}));
""")
        self.assertEqual(out["h1"], ["Glowfern Bioluminescent Path Marker"])
        self.assertEqual(len(out["h2"]), 15)
        self.assertEqual(out["h2"][0], "1. Executive Summary")
        self.assertEqual((out["textareas"], out["inputs"]), (0, 0))
        self.assertEqual((out["itemLabels"], out["classificationLines"]), (0, 0))
        self.assertEqual(out["unverifiedBadges"], ["⚠ Unverified"])
        self.assertTrue(out["citesResolve"])
        self.assertIn("Not documented in the uploaded materials.", out["notes"])
        self.assertEqual(out["tables"], 1)
        self.assertEqual(out["notice"], ["INNOVATOR-SUBMITTED — NOT INSTITUTIONALLY APPROVED"])

    def test_citation_opens_its_source_details(self):
        out = self.run_node(r"""
renderView(report);
const cite = all(n => n.className === 'cite')[0];
const target = $(cite.href.slice(1));
const before = target.children.filter(c => c.tag === 'blockquote').length;
cite.dispatch('click');
console.log(JSON.stringify({tag: target.tag, highlighted: target.className.includes('target'),
  before, details: all(n => n.tag === 'details').length,
  quotes: all(n => n.tag === 'blockquote').length,
  excerpts: report.sources.reduce((n, s) => n + s.excerpts.length, 0)}));
""")
        self.assertEqual(out["tag"], "div")                   # always visible, not collapsed
        self.assertEqual(out["details"], 0)
        self.assertGreaterEqual(out["before"], 1)             # quotes shown before any click
        self.assertEqual(out["quotes"], out["excerpts"])      # every quotation, once
        self.assertTrue(out["highlighted"])

    def test_version_line_distinguishes_draft_from_snapshots(self):
        out = self.run_node(r"""
currentReport = report; const lines = [];
for (const n of [null, 0, 2]) { submissionCount = n; renderView(report); lines.push($('docVersion').textContent); }
console.log(JSON.stringify({lines}));
""")
        unknown, none, two = out["lines"]
        self.assertTrue(unknown.startswith("Current editable draft"))
        self.assertNotIn("submitted", unknown)          # never guessed while unknown
        self.assertTrue(none.endswith("not yet submitted"))
        self.assertIn("2 submitted snapshots listed below", two)
        self.assertNotIn("not yet submitted", two)

    def test_shared_labels_shown_once_and_headings_numbered(self):
        out = self.run_node(r"""
renderView(report);
console.log(JSON.stringify({
  blockLabels: all(n => n.className === 'block-label').map(n => n.textContent),
  interpretationBadges: all(n => (n.className||'').startsWith('badge') && n.textContent === 'AI interpretation').length,
  h2: all(n => n.tag === 'h2').map(n => n.textContent),
  legend: all(n => n.className === 'doc-legend').length
}));
""")
        self.assertIn("Declared at registration", out["blockLabels"])
        self.assertIn("AI recommendations", out["blockLabels"])
        self.assertLessEqual(out["interpretationBadges"], 8)
        self.assertTrue(all(re.match(r"^\d+\. \S", h) for h in out["h2"]))
        self.assertEqual(out["legend"], 1)

    def test_reference_without_excerpt_shows_note_not_empty_quote(self):
        out = self.run_node(r"""
const r = JSON.parse(JSON.stringify(report));
r.sources[0].excerpts = []; r.sources[0].note = 'No excerpt was recorded for this citation.';
renderView(r);
const d = $('src-' + r.sources[0].number);
console.log(JSON.stringify({quotes: d.children.filter(c => c.tag === 'blockquote').length,
                            text: d.textContent}));
""")
        self.assertEqual(out["quotes"], 0)
        self.assertIn("No excerpt was recorded", out["text"])

    # ---------------- edit mode ----------------

    def test_edit_mode_fields_and_hidden_empty_fields(self):
        out = self.run_node(r"""
renderEdit(report);
const visible = all(n => n.tag === 'textarea' && !n.hidden);
const hidden = all(n => n.tag === 'textarea' && n.hidden);
console.log(JSON.stringify({
  sections: all(n => n.tag === 'h2').length,
  visible: visible.length, hidden: hidden.length,
  addLinks: all(n => n.className === 'add-link').map(n => n.textContent).slice(0, 3),
  components: visible.find(t => t.id === 'f-technology-components').value.split('\n'),
  itemLabels: all(n => /^Item \d/.test(n._text)).length
}));
""")
        self.assertEqual(out["sections"], 14)                 # Sources has nothing to edit
        self.assertGreater(out["visible"], 5)
        self.assertGreater(out["hidden"], 5)                  # empty fields collapsed
        self.assertTrue(all(link.startswith("+ Add ") for link in out["addLinks"]))
        self.assertEqual(out["components"],
                         ["acrylic housing", "gel pad", "photodiode sensor", "ESP32 microcontroller"])
        self.assertEqual(out["itemLabels"], 0)

    def test_edits_update_working_profile_and_trigger_autosave(self):
        out = self.run_node(r"""
renderEdit(report);
const comps = $('f-technology-components');
comps.value = comps.value + '\nLED driver';
comps.dispatch('input');
const add = all(n => n.className === 'add-link' && n.textContent === '+ Add proposed solution')[0];
add.dispatch('click');
const sol = $('f-problem_solution-solution') || $('f-problem-solution-solution');
const wasHidden = sol.hidden;
sol.value = 'A sealed moss enclosure with a solar charger.';
sol.dispatch('input');
const trl = $('f-readiness-suggested-trl');
trl.value = '12'; trl.dispatch('input');
const afterBad = workingProfile.readiness.suggested_trl;
trl.value = '4'; trl.dispatch('input');
console.log(JSON.stringify({
  dirty, components: workingProfile.technology.components.map(c => [c.value, c.classification]),
  solution: workingProfile.problem_solution.solution, wasHidden,
  afterBad, trl: workingProfile.readiness.suggested_trl,
  addRemoved: !all(n => n.textContent === '+ Add proposed solution').length
}));
""")
        self.assertEqual(out["components"][-1], ["LED driver", "inference"])
        self.assertEqual(out["components"][0], ["acrylic housing", "document_fact"])
        self.assertEqual(out["solution"]["classification"], "inference")
        self.assertTrue(out["solution"]["explanation"].startswith("Innovator-edited"))
        self.assertFalse(out["wasHidden"])
        self.assertTrue(out["addRemoved"])
        self.assertIsNone(out["afterBad"])                    # invalid TRL ignored
        self.assertEqual(out["trl"], 4)
        self.assertEqual(out["dirty"], 3)                     # autosave scheduled per valid edit

    def test_unverified_items_flagged_in_edit_mode(self):
        out = self.run_node(r"""
renderEdit(report);
const hint = $('f-development-experimental-results').parent.children.find(n => n.className === 'edit-hint');
console.log(JSON.stringify({hint: hint.textContent}));
""")
        self.assertIn("⚠ 1 unverified item", out["hint"])


if __name__ == "__main__":
    unittest.main()
