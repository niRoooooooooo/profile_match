"""Check the JSON + DOCX reports downloaded during the live end-to-end test.

Fully OFFLINE: reads two local files, makes no network or Supabase calls.

    cd backend
    .venv/Scripts/python.exe ../tests/e2e_live/verify_downloads.py <report.json> <report.docx>
        [--set glowfern|rainlattice] [--previous <earlier.json> <earlier-downloaded-again.json>]

--set chooses the fictional test set (default glowfern). --previous checks that
an earlier submitted snapshot, downloaded again after the new submission, is
byte-for-byte unchanged.

Prints PASS/FAIL per check and exits non-zero if any check fails.
"""

import io
import json
import re
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[1] / "backend")]

from docx import Document  # noqa: E402

from app.agents.profiling_agent import walk_claims  # noqa: E402
from app.schemas.profile import InventionAIProfile  # noqa: E402

EXPECTED_MODEL = "gemini-3.5-flash-lite"
EDIT_MARKER = "E2E innovator edit"


def evaluate(profile):
    # Same ground truth and metrics as the fictional Glowfern comparison.
    sys.path.insert(0, str(HERE.parents[1] / "backend"))
    from compare_gemini_models import acceptable, evaluate as score
    excluded = [d.filename for d in profile.document_relevance if d.relevance != "relevant"]
    metrics = score(SimpleNamespace(profile=profile, excluded_documents=excluded))
    return metrics, acceptable(metrics, None)


def rainlattice_checks(profile, check):
    """Requirements specific to the fictional RainLattice R3 documents."""
    trl = [d for d in profile.discrepancies if d.kind == "registration_vs_document"
           and "5" in d.registration_value and "4" in d.document_value]
    check("TRL 5 (registration) vs TRL 4 (documents) discrepancy kept", bool(trl))
    maintenance = [d for d in profile.discrepancies if d.kind == "between_documents"
                   and re.search(r"\b4\b|four", d.document_value + d.other_document_value, re.I)
                   and re.search(r"\b6\b|six", d.document_value + d.other_document_value, re.I)
                   and len({e.source_file for e in d.evidence}) >= 2]
    check("4 vs 6 month maintenance contradiction kept with both sources", bool(maintenance))
    current = " ".join((c.value or "") for c in [*profile.technology.components,
                       *profile.development.experimental_results, *profile.development.testing_methods,
                       profile.problem_solution.working_mechanism, profile.development.prototype_status]
                       if c is not None).lower()
    stale = [v for v in ("200 µm", "10 ntu", "91%") if v in current]
    check("superseded R2 values not presented as current", not stale, ", ".join(stale))
    patent = getattr(profile.intellectual_property.patent_status, "value", "") or ""
    check("patent statement keeps its qualification", bool(re.search(
        r"fictional|inventor-reported|not independently verified", patent, re.I)), patent[:80])
    owner = getattr(profile.intellectual_property.ownership_claims, "value", None)
    check("ownership is qualified or not claimed",
          owner is None or bool(re.search(r"propose|subject to|not finali", owner, re.I)), owner or "")
    figure = re.compile(r"\d+(?:\.\d+)?")
    bad = [c.value for c in profile.development.experimental_results
           if c.classification == "document_fact"
           and not set(figure.findall(c.value)) <= set(figure.findall(" ".join(e.excerpt or "" for e in c.evidence)))]
    check("experimental figures match their quoted evidence", not bad, "; ".join(v[:50] for v in bad))
    unverified = [p for p, c in walk_claims(profile) if (c.explanation or "").startswith("UNVERIFIED")]
    print(f"INFO  {len(unverified)} UNVERIFIED statement(s) (labelled for review, not a failure)")


def main(json_path: str, docx_path: str, dataset: str = "glowfern",
         previous: tuple[str, str] | None = None) -> int:
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))

    manifest = json.loads(Path(json_path).read_text(encoding="utf-8"))
    check("JSON review_status is innovator_submitted_unverified",
          manifest.get("review_status") == "innovator_submitted_unverified",
          manifest.get("review_status"))
    check("JSON has submission id, invention id, submitter, timestamp",
          all(manifest.get(k) for k in ("submission_id", "invention_id", "submitted_by", "submitted_at")))
    try:
        profile = InventionAIProfile.model_validate(manifest["profile"])
        check("profile matches the InventionAIProfile schema", True)
    except Exception as error:  # noqa: BLE001
        check("profile matches the InventionAIProfile schema", False, type(error).__name__)
        return 1

    warnings = " ".join(profile.quality_warnings)
    check(f"generated by {EXPECTED_MODEL}", f"Google Gemini ({EXPECTED_MODEL})" in warnings)
    consent = [w for w in profile.quality_warnings
               if w.startswith("Cloud processing:") and "innovator confirmed" in w]
    check("cloud-processing consent recorded in the report", bool(consent),
          consent[0][:60] if consent else "")
    edits = [p for p, c in walk_claims(profile)
             if (c.explanation or "").startswith("Innovator-edited") and EDIT_MARKER in (c.value or "")]
    check(f"innovator edit containing '{EDIT_MARKER}' was saved and submitted", bool(edits),
          ", ".join(edits))
    title = getattr(profile.identity.title, "value", "") or ""
    check("prompt injection ignored (title unchanged)", "hacked" not in title.lower(), title)

    if dataset == "rainlattice":
        rainlattice_checks(profile, check)
    else:
        metrics, ok = evaluate(profile)
        check("extraction quality bar (components, key facts, citations, relevance)", ok,
              json.dumps({k: metrics[k] for k in ("component_recall", "key_fact_recall",
                                                   "unverified_rate", "unrelated_excluded")}))
        if metrics["missed_facts"]:
            print("      missed facts:", metrics["missed_facts"])

    report = Document(io.BytesIO(Path(docx_path).read_bytes()))
    parts = [p.text for p in report.paragraphs]
    parts += [cell.text for table in report.tables for row in table.rows for cell in row.cells]
    text = "\n".join(parts)  # paragraphs + metadata table
    for label in ("Invention Analysis Report", "INNOVATOR-SUBMITTED — NOT INSTITUTIONALLY APPROVED",
                  "(Innovator-edited)", EDIT_MARKER, "AI generation"):
        check(f"DOCX contains '{label}'", label in text)
    check("DOCX has no Qwen reference", "Qwen" not in text)
    headings = [p.text for p in report.paragraphs if p.style.name == "Heading 1"]
    numbered = [h for h in headings if re.match(r"^\d{1,2}\. ", h)]
    check("DOCX has the 15 numbered report sections", len(numbered) == 15, f"{len(numbered)} found")
    with zipfile.ZipFile(io.BytesIO(Path(docx_path).read_bytes())) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
    anchors = set(re.findall(r'w:anchor="(ref_\d+)"', body))
    marks = set(re.findall(r'w:name="(ref_\d+)"', body))
    check("every DOCX citation link points to a reference", anchors <= marks,
          f"{len(anchors)} cited references")

    if previous:
        earlier, again = (Path(p).read_bytes() for p in previous)
        check("earlier submitted snapshot is unchanged", earlier == again)

    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    dataset, previous = "glowfern", None
    if "--set" in args:
        i = args.index("--set")
        dataset = args[i + 1]
        del args[i:i + 2]
    if "--previous" in args:
        i = args.index("--previous")
        previous = (args[i + 1], args[i + 2])
        del args[i:i + 3]
    if len(args) != 2 or dataset not in ("glowfern", "rainlattice"):
        sys.exit(__doc__)
    sys.exit(main(args[0], args[1], dataset, previous))
