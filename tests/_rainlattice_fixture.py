"""FICTIONAL "RainLattice R3" test set, condensed from the three fictional
RainLattice R3 test documents (sentences copied verbatim, page/section kept).

It exercises Option B extraction quality:
- current R3 values (250 µm, 12 NTU) vs SUPERSEDED R2 values (200 µm,
  10 NTU, 91%) that must never be reported as current;
- an UNRESOLVED cross-document contradiction: screen maintenance every
  4 months (technical specification) vs 6 months (commercial dossier);
- registered TRL 5 vs evidence-based TRL 4 (discrepancy, not resolved);
- testing METHODS (setup, flows, trials) distinct from RESULTS;
- a hedged novelty claim and a qualified, unfinished ownership statement;
- real application settings vs the product name; sectors vs the domain;
- the commercial dossier lacks the demo-mode marker at its start (as the
  real file does), so demo mode would refuse it.
"""

import re

import _fixtures as fx  # noqa: F401  (adds backend to sys.path)
from app.services.document_parser import DocumentChunk, ParsedDocument
from app.services.document_processor import ProcessedFile, ProcessingResult

RAIN_INVENTION_ID = "44444444-4444-4444-8444-444444444444"
SPEC = "RainLattice_R3_Technical_Specification.pdf"
VAL = "RainLattice_R3_Prototype_Testing_and_Validation.pdf"
DOSSIER = "RainLattice_R3_IP_and_Commercialization_Dossier.docx"
TITLE = "RainLattice R3 - Smart First-Flush Rainwater Diversion and Quality Monitoring Unit"
MARK = "FICTIONAL TEST DOCUMENT | PROFILE MATCH DEMO CORPUS"


def rain_invention(confidentiality="public"):
    return {
        "id": RAIN_INVENTION_ID,
        "owner_id": fx.OWNER_ID,
        "title": TITLE,
        "abstract": "A smart first-flush diverter that monitors rainwater quality.",
        "domain": "Environmental engineering",
        "trl": 5,                     # documents assess TRL 4
        "ip_status": "Provisional application filed",
        "inventors": ["Test Inventor A", "Test Inventor B"],
        "keywords": ["rainwater harvesting", "first flush", "turbidity"],
        "confidentiality": confidentiality,
        "status": "registered",
    }


RAIN_DOCS = {
    SPEC: [
        (1, None,
         f"{MARK} | 01/03\nSystem Design and Technical Specification\n"
         "1. Executive design abstract\n"
         "RainLattice R3 is a modular, locally controlled first-flush diversion unit for roof "
         "rainwater harvesting. Instead of directing every litre of runoff into a storage tank, "
         "the unit initially diverts runoff that may contain accumulated dust and debris. After "
         "a configurable initial volume has been diverted, a photometric turbidity measurement "
         "and basic operating checks determine whether the valve can switch to collection. The "
         "unit is intended for NON-POTABLE applications only. No pathogen-removal or "
         "disinfection capability is claimed.\n"
         "2. Design intent and boundary conditions\n"
         "User need. A small building collecting roof runoff may wish to reduce visibly dirty "
         "initial runoff and monitor the quality of water that enters storage."),
        (2, None,
         f"{MARK} | 01/03\n3. Architecture and major subsystems\n"
         "Rainwater flows through a 250 µm mesh pre-screen (R3 baseline), a short measurement "
         "cell, and an electrically actuated spring-return diverter. The control PCB samples "
         "turbidity, conductivity, temperature and flow pulses. A 12 V battery supplies the "
         "actuator and control electronics; a small solar panel supports charging. The firmware "
         "saves decision traces and fault flags to local microSD.\n"
         "RL-02 Optical turbidity sensor 0-100 NTU nominal digital output; 5 s samples\n"
         "RL-07 Controller ESP32-S3 with watchdog, no wireless enabled"),
        (3, None,
         f"{MARK} | 01/03\n4. Control logic and decision sequence\n"
         "State 2 - INITIAL_DIVERT: The controller integrates measured flow until at least the "
         "configured diversion volume is reached (0.50 L/m² × registered roof area). State 3 - "
         "QUALITY_CHECK: Turbidity must remain at or below 12 NTU for two consecutive samples, "
         "while flow, battery and sensor-validity checks pass. State 4 - COLLECT: The valve "
         "switches to the storage outlet; sampling and alarm monitoring continue.\n"
         "Screen maintenance Nominal every 4 months Engineering estimate; no long-duration wear test"),
        (5, None,
         f"{MARK} | 01/03\n9. Revision history\n"
         "R2 02 August 2026 Earlier commercial concept: 200 µm screen; 10 NTU switching "
         "threshold. Superseded.\n"
         "10. Known gaps\nNo outdoor roof pilot has been completed; therefore, the claimed TRL 5 "
         "in the registration is not yet supported by environment-relevant field validation."),
    ],
    VAL: [
        (1, None,
         f"{MARK} | 02/03\nPrototype Testing and Validation Report\n"
         "Total primary trials 18 paired first-flush trials across 6 controlled scenarios\n"
         "2. Materials and representative test setup\n"
         "A recirculating laboratory rainfall apparatus supplied preconditioned tap water to a "
         "mock gutter section, synthetic roofing strip, adjustable dust loading tray and the R3 "
         "prototype intake. Flow conditions were 3, 6 and 9 L/min. Each flow/loading combination "
         "was repeated three times, for 18 tests."),
        (2, None,
         f"{MARK} | 02/03\n4. Primary paired-trial results\n"
         "Across these six scenario medians, the reductions range from 67.6% to 79.5% (depending "
         "on dust loading and flow). Four of the 18 trial records included later sample values "
         "over 12 NTU; the current firmware flagged these but did not automatically revert once "
         "the valve had switched."),
        (3, None,
         f"{MARK} | 02/03\n5. Diversion-volume and switch-timing accuracy\n"
         "The median observed valve switch latency across eligible decisions was 11.8 seconds "
         "(range 9.2-14.9 seconds)."),
        (4, None,
         f"{MARK} | 02/03\n8. Prototype revision history, superseded data\n"
         "Likewise, an R2 study note recorded a single-event turbidity reduction of 91% under "
         "especially light dust loading. The R2 figure is excluded from the R3 aggregate results.\n"
         "9. Readiness and interpretation\n"
         "The invention registration declares TRL 5. The validation team assesses the "
         "demonstrated readiness as TRL 4 on the basis of laboratory component and system "
         "validation only. No outdoor relevant-environment rain event pilot, independent "
         "installation validation, or real customer field trial was completed."),
    ],
    DOSSIER: [
        # Like the real file: the marker is NOT within the first 300 characters.
        (None, None, "DOCUMENT 03/03  /  REV 21 November 2026  /  STATUS: FICTIONAL TEST DATA"),
        (None, "IP, Commercialization and Partnership Dossier",
         "TEST NOTICE All content is fabricated for testing AI extraction, citation handling, "
         "cross-document synthesis and missing-information detection. This is not an actual "
         "product, clinical device, patent filing or safety certification. Permitted handling: "
         "FICTIONAL TEST DOCUMENT; public test data only"),
        (None, "2. Invention ownership and IP disclosure",
         "The dossier records a FICTIONAL provisional application filed on 02 September 2026, "
         "referenced as RL-PRV-FICTION-2026-0902.\n"
         "Ownership | Inventors propose equal ownership, subject to institution agreement | "
         "Not finalized; assignment contract missing\n"
         "Novelty claim | To the inventors' knowledge, combining integrated first-flush sensing "
         "and fail-to-divert control in one removable unit is distinctive | Unverified claim"),
        (None, "3. Version history and technical-data reconciliation",
         "One matter remains unresolved. The latest technical specification says nominal screen "
         "maintenance every FOUR months, while the current commercialization planning worksheet "
         "below assumes replacement every SIX months."),
        (None, "4. Customer problems and application settings",
         "Proposed applications include: (i) educational campus buildings collecting water for "
         "garden irrigation; (ii) non-potable utility tanks in community halls; (iii) roof-water "
         "capture demonstrations at sustainability learning centers; and (iv) pilot deployments "
         "in temporary facilities with defined maintenance staff."),
        (None, "5. Proposed product and pricing options",
         "The 1,000-unit projected direct cost is USD 146/unit and includes packaging and a "
         "warranty reserve; installation, shipping, taxes, reseller margin and certification are "
         "excluded."),
        (None, "6. Business-case assumptions and limitations",
         "The six-month screen service interval used for a draft consumables-revenue model is a "
         "business-model assumption. The technical specification uses four months."),
        (None, "7. Target partner categories and capabilities",
         "Sensor manufacturer | Optical turbidity calibration and anti-fouling design | Reduce "
         "sensor drift in dirty runoff"),
    ],
}


def rain_processed_result(confidentiality="public"):
    documents = []
    for index, (filename, chunks) in enumerate(RAIN_DOCS.items(), 1):
        parsed = ParsedDocument(
            filename=filename, file_type=filename.rsplit(".", 1)[-1],
            chunks=[DocumentChunk(source_file=filename, page=page, section=section, text=text)
                    for page, section, text in chunks])
        documents.append(ProcessedFile(document_id=f"r{index}", filename=filename, parsed=parsed))
    return ProcessingResult(invention_id=RAIN_INVENTION_ID, owner_id=fx.OWNER_ID,
                            invention=rain_invention(confidentiality), documents=documents)


def rain_source_text() -> str:
    parts = [text for chunks in RAIN_DOCS.values() for _, _, text in chunks]
    invention = rain_invention()
    parts += [str(invention[k]) for k in ("title", "abstract", "domain", "trl", "ip_status")]
    return " ".join(parts)


_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
SUPERSEDED = ("200 µm", "10 ntu", "91%")


def evaluate_rain(result) -> dict:
    """PASS/FAIL per Option B quality criterion (deterministic)."""
    from app.agents.profiling_agent import near_duplicate, walk_claims

    p = result.profile
    claims = [(path, c) for path, c in walk_claims(p) if c.classification != "missing" and c.value]
    available = set(_NUMBER.findall(rain_source_text().replace(",", "")))
    invented = [f"{path}: {n}" for path, c in claims
                for n in _NUMBER.findall(c.value.replace(",", "")) if n not in available]
    current = " ".join((c.value or "").lower() for c in
                       p.technology.components + p.development.experimental_results
                       + p.development.testing_methods + [p.problem_solution.working_mechanism,
                                                          p.development.prototype_status]
                       if c is not None)
    maintenance = [d for d in p.discrepancies if d.kind == "between_documents"
                   and {e.source_file for e in d.evidence} >= {SPEC, DOSSIER}
                   and re.search(r"maint|interval|replace|screen", f"{d.field} {d.document_value}", re.I)]
    trl = [d for d in p.discrepancies if "trl" in f"{d.field} {d.document_value}".lower()]
    ps = p.problem_solution
    statements = [c.value for c in (ps.problem, ps.objective, ps.solution, ps.working_mechanism)
                  if c is not None and c.value]
    ownership = p.intellectual_property.ownership_claims
    title_words = set(re.findall(r"[a-z0-9-]+", TITLE.lower())) | {"unit", "device", "system"}
    from app.services.report_renderer import _match_field
    stale = [n for n in p.missing_information
             if (m := _match_field(n))[0] and m[1]
             and getattr(eval_path(p, m[0]), "value", None) is not None]
    return {
        "maintenance_contradiction_preserved": bool(maintenance),
        "trl_discrepancy_preserved": bool(trl),
        "no_superseded_values_as_current": not any(s in current for s in SUPERSEDED),
        "working_mechanism_present": ps.working_mechanism is not None
        and "12 ntu" in ps.working_mechanism.value.lower(),
        "statements_distinct": not any(near_duplicate(a, b) for i, a in enumerate(statements)
                                       for b in statements[i + 1:]),
        "methods_separate_from_results": bool(p.development.testing_methods)
        and not any("%" in c.value for c in p.development.testing_methods),
        "results_reported": any("67.6%" in c.value for c in p.development.experimental_results),
        "trl_justified": p.readiness.justification is not None
        and "trl 4" in p.readiness.justification.value.lower(),
        "ownership_explicit_or_absent": ownership is None or (
            ownership.classification == "document_fact" and "propose" in ownership.value.lower()),
        "novelty_hedged": all("knowledge" in c.value.lower() for c in p.technology.novelty)
        and bool(p.technology.novelty),
        "use_cases_real": len(p.applications.use_cases) >= 3 and not any(
            set(re.findall(r"[a-z0-9-]+", c.value.lower())) <= title_words
            for c in p.applications.use_cases),
        "industries_not_domain": bool(p.applications.industries) and not any(
            "environmental engineering" == c.value.lower() for c in p.applications.industries),
        "no_invented_numbers": not invented,
        "no_stale_missing_notes": not stale,
        "invented": invented,
    }


def eval_path(profile, path):
    value = profile
    for part in path.split("."):
        value = getattr(value, part)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def rain_verdict(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if isinstance(v, bool)}
