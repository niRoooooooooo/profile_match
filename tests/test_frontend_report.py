"""Frontend checks for invention_report.html (display-only UNVERIFIED label).

Runs the page's REAL makeClaimEditor code in Node.js with a minimal fake DOM.
Skipped automatically if Node.js is not installed. No browser, no network.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "invention_report.html"
NODE = shutil.which("node")


def inline_script() -> str:
    html = PAGE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    assert len(scripts) == 1, "expected exactly one inline script"
    return scripts[0]


def extract_function(source: str, name: str) -> str:
    """Return the full source of `function name(...) {...}` by brace matching."""
    start = source.index(f"function {name}(")
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1


FAKE_DOM = r"""
class Node {
  constructor(tag){ this.tag=tag; this.children=[]; this.className=''; this._text='';
    this.attrs={}; this.listeners={}; this.value=''; this.title=''; }
  set textContent(v){ this._text=String(v); this.children=[]; }
  get textContent(){ return this._text + this.children.map(c=>c.textContent).join(' '); }
  get firstChild(){ return this.children[0] || null; }
  append(...nodes){ this.children.push(...nodes); }
  removeChild(n){ this.children.splice(this.children.indexOf(n),1); return n; }
  setAttribute(k,v){ this.attrs[k]=v; }
  addEventListener(t,f){ (this.listeners[t] ||= []).push(f); }
  dispatch(t){ (this.listeners[t]||[]).forEach(f=>f({target:this})); }
  findAll(pred,out=[]){ if(pred(this))out.push(this); this.children.forEach(c=>c.findAll(pred,out)); return out; }
}
const document={ createElement: tag=>new Node(tag) };
let dirty=0; function markDirty(){ dirty++; }
"""


@unittest.skipUnless(NODE, "Node.js not installed")
class UnverifiedLabelTests(unittest.TestCase):
    def run_node(self, body: str) -> dict:
        source = inline_script()
        functions = "\n".join(extract_function(source, n)
                              for n in ("pretty", "elem", "makeClaimEditor"))
        program = FAKE_DOM + functions + "\n" + body
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "check.js"
            script.write_text(program, encoding="utf-8")
            completed = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                                       encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_inline_script_is_valid_javascript(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "page.js"
            script.write_text(inline_script(), encoding="utf-8")
            completed = subprocess.run([NODE, "--check", str(script)], capture_output=True,
                                       text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_label_shown_only_for_unverified_and_cleared_on_edit(self):
        out = self.run_node(r"""
const labels = el => el.findAll(n => n.className === 'unverified');
const unverified = {value:'300 lumens', classification:'inference', evidence:[],
  explanation:'UNVERIFIED: the AI attributed this to the uploaded documents, but ...'};
const verified = {value:'gel pad', classification:'document_fact',
  evidence:[{source_file:'a.pdf', page:1, excerpt:'gel pad'}], explanation:null};
const plain = {value:'Self-powered marker', classification:'inference', evidence:[],
  explanation:'Synthesized from a.pdf.'};
const e1 = makeClaimEditor(unverified, 'experimental_results');
const e2 = makeClaimEditor(verified, 'components');
const e3 = makeClaimEditor(plain, 'problem');
const before = labels(e1).length;
const labelText = labels(e1)[0].textContent;
const role = labels(e1)[0].attrs.role;
// Simulate an innovator edit exactly as the browser would.
const input = e1.findAll(n => n.tag === 'textarea')[0];
input.value = 'Innovator corrected value';
input.dispatch('input');
console.log(JSON.stringify({
  before, labelText, role,
  verifiedLabels: labels(e2).length, plainLabels: labels(e3).length,
  afterEdit: labels(e1).length, dirty,
  edited: unverified,
  evidenceCards: e2.findAll(n => n.className === 'evidence').length,
}));
""")
        self.assertEqual(out["before"], 1)
        self.assertIn("UNVERIFIED", out["labelText"])
        self.assertEqual(out["role"], "note")
        self.assertEqual(out["verifiedLabels"], 0)
        self.assertEqual(out["plainLabels"], 0)
        self.assertEqual(out["evidenceCards"], 1)
        # Editing behaviour is unchanged: value saved, marked innovator-edited,
        # evidence cleared, autosave triggered, AI label removed.
        self.assertEqual(out["afterEdit"], 0)
        self.assertEqual(out["dirty"], 1)
        self.assertEqual(out["edited"]["value"], "Innovator corrected value")
        self.assertEqual(out["edited"]["classification"], "inference")
        self.assertEqual(out["edited"]["evidence"], [])
        self.assertTrue(out["edited"]["explanation"].startswith("Innovator-edited statement"))

    def test_label_text_is_not_html_injected(self):
        out = self.run_node(r"""
const claim = {value:'x', classification:'inference', evidence:[],
  explanation:'UNVERIFIED: <img src=x onerror=alert(1)>'};
const e = makeClaimEditor(claim, 'f');
const flag = e.findAll(n => n.className === 'unverified')[0];
console.log(JSON.stringify({text: flag.textContent, title: flag.title, kids: flag.children.length}));
""")
        self.assertNotIn("<img", out["text"])          # fixed text, set via textContent
        self.assertEqual(out["kids"], 0)               # no parsed child elements
        self.assertIn("<img", out["title"])            # tooltip is a plain attribute string


class BehaviourUnchangedTests(unittest.TestCase):
    """Key editing, autosave and submission behaviour is still present (see git diff)."""

    EXPECTED = {
        "autosave": "draft=result.draft;savedCounter=before;",
        "ensureSaved": "if(editCounter>savedCounter)await autosave();",
        "submit": "if(!(await ensureSaved()))return;",
    }

    def test_behaviour_functions_unchanged(self):
        source = inline_script()
        for name, marker in self.EXPECTED.items():
            self.assertIn(marker, extract_function(source, name), name)
        editor = extract_function(source, "makeClaimEditor")
        for marker in ("claim.classification=changed?'inference':'missing';",
                       "claim.evidence=[];", "markDirty();",
                       "while(notes.firstChild)notes.removeChild(notes.firstChild);"):
            self.assertIn(marker, editor)


if __name__ == "__main__":
    unittest.main()
