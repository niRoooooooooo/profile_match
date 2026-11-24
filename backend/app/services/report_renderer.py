"""Deterministic report renderer: one InventionAIProfile -> one report.

The SINGLE rendering system for the web report (View/Edit modes) and the
submitted DOCX. It only arranges the saved, evidence-checked profile data in
reading order. It never calls an AI model and never writes new facts:
- every item keeps its status (verified / AI interpretation / recommendation
  / declared at registration / innovator-edited / unverified);
- verified items carry numbered citations; excerpts are listed once in the
  "Source Documents and References" section;
- empty fields collapse into one "Not documented in the uploaded materials."
  note instead of blank boxes. Absence is never stated as non-existence.

Input is the saved edited_data (the only source of truth); nothing is stored.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.profile import Claim, Evidence, InventionAIProfile

NOT_DOCUMENTED = "Not documented in the uploaded materials."
REPORT_NOTICE = "INNOVATOR-SUBMITTED — NOT INSTITUTIONALLY APPROVED"
DISCLAIMER = (
    "This AI-assisted report was generated from the innovator's uploaded "
    "documents and edited by the innovator. Statements are not independently "
    "verified. AI interpretations and recommendations are labelled; check the "
    "original documents before relying on technical, legal or commercial claims."
)
LEGEND = (
    "How to read this report: numbered citations such as [1] link to the supporting "
    "passages listed in Section 15. Statements are labelled when they are AI "
    "interpretations, AI recommendations, declared at registration, edited by the "
    "innovator or unverified."
)
NO_EXCERPT = "No excerpt was recorded for this citation."
REVIEW_STATUS = "Innovator-submitted; pending future institutional review"

Status = Literal["verified", "interpretation", "recommendation", "declared",
                 "edited", "unverified", "discrepancy", "contradiction", "info"]

STATUS_LABELS: dict[str, str | None] = {
    "verified": None,                      # shown via its citations only
    "interpretation": "AI interpretation",
    "recommendation": "Recommendation",
    "declared": "Declared at registration",
    "edited": "Innovator-edited",
    "unverified": "Unverified",
    "discrepancy": "Discrepancy",
    "contradiction": "Unresolved contradiction",
    "info": None,
}
# Weakest status wins when several claims are joined into one line.
_WEAKNESS = ["verified", "declared", "edited", "recommendation", "interpretation", "unverified"]
# When every item of a block shares one of these statuses, the label is shown
# ONCE for the block instead of after every item. Innovator edits, unverified
# statements and contradictions always keep their per-item label.
BLOCK_LABELS = {
    "interpretation": "AI interpretation",
    "recommendation": "AI recommendations",
    "declared": "Declared at registration",
}


# ---------------------------------------------------------------------------
# Report document model (JSON for the web page; input for the DOCX writer)
# ---------------------------------------------------------------------------

class ReportItem(BaseModel):
    text: str
    name: str | None = None          # field name for "facts" blocks
    status: Status = "info"
    label: str | None = None         # human label derived from status
    citations: list[int] = Field(default_factory=list)
    path: str | None = None          # profile path, e.g. technology.components[1]


class ReportBlock(BaseModel):
    kind: Literal["paragraph", "facts", "bullets", "table", "note"]
    heading: str | None = None
    items: list[ReportItem] = Field(default_factory=list)
    text: str | None = None          # notes only
    label: str | None = None         # shared status label for all items
    status: Status | None = None


class ReportField(BaseModel):
    """An editable field shown in Edit mode for this section."""

    path: str                        # e.g. problem_solution.problem
    label: str
    kind: Literal["text", "list", "lines", "number"]


class ReportSection(BaseModel):
    number: int
    key: str
    title: str
    blocks: list[ReportBlock] = Field(default_factory=list)
    fields: list[ReportField] = Field(default_factory=list)
    documented: bool = True


class SourceEntry(BaseModel):
    number: int
    source_file: str
    page: int | None = None
    section: str | None = None
    excerpts: list[str] = Field(default_factory=list)
    note: str | None = None          # shown when no excerpt was recorded


class MetaEntry(BaseModel):
    name: str
    value: str


class ReportDocument(BaseModel):
    title: str
    subtitle: str = "Invention Analysis Report"
    notice: str = REPORT_NOTICE
    disclaimer: str = DISCLAIMER
    legend: str = LEGEND
    version: str | None = None       # editable draft or submitted snapshot
    metadata: list[MetaEntry] = Field(default_factory=list)      # short header
    processing: list[MetaEntry] = Field(default_factory=list)    # appendix only
    sections: list[ReportSection] = Field(default_factory=list)
    sources: list[SourceEntry] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section specification (profile path -> report position)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class El:
    kind: str            # prose | fact | facts_list | bullets | table
    path: str            # dotted profile path
    label: str
    important: bool = False   # reported as missing when empty


P = lambda path, label, important=False: El("prose", path, label, important)  # noqa: E731
F = lambda path, label, important=False: El("fact", path, label, important)  # noqa: E731
FL = lambda path, label, important=False: El("facts_list", path, label, important)  # noqa: E731
L = lambda path, label, important=False: El("bullets", path, label, important)  # noqa: E731
T = lambda path, label, important=False: El("table", path, label, important)  # noqa: E731

SECTIONS: list[tuple[int, str, str, list[El]]] = [
    (1, "executive_summary", "Executive Summary", [
        P("identity.concise_summary", "Summary", True)]),
    (2, "invention_overview", "Invention Overview", [
        P("identity.detailed_summary", "Overview"),
        F("identity.title", "Title"),
        FL("identity.inventors", "Inventors"),
        F("identity.institution", "Institution"),
        F("technology.primary_domain", "Technical domain"),
        FL("technology.secondary_domains", "Secondary domains"),
        FL("identity.keywords", "Keywords")]),
    (3, "problem_objectives", "Problem Statement and Objectives", [
        P("problem_solution.problem", "Problem", True),
        P("problem_solution.objective", "Objectives", True)]),
    (4, "solution_principle", "Proposed Solution and Working Principle", [
        P("problem_solution.solution", "Proposed solution", True),
        P("problem_solution.working_mechanism", "Working principle", True),
        L("technology.techniques", "Key techniques")]),
    (5, "technology_components", "Technology Description and Core Components", [
        L("technology.components", "Core components", True)]),
    (6, "novelty", "Novelty and Technical Advantages", [
        L("technology.novelty", "Novelty claims", True)]),
    (7, "prototype_readiness", "Prototype Development and Technology Readiness", [
        P("development.prototype_status", "Prototype status", True),
        P("readiness.justification", "Readiness assessment"),
        L("readiness.verification_needed", "Verification still needed")]),
    (8, "testing_results", "Testing Methods and Experimental Results", [
        L("development.testing_methods", "Testing methods", True),
        T("development.experimental_results", "Experimental results", True)]),
    (9, "applications", "Applications and Relevant Industries", [
        L("applications.use_cases", "Use cases", True),
        L("applications.industries", "Industries", True),
        L("applications.target_customers", "Target customers"),
        L("applications.product_forms", "Product forms")]),
    (10, "intellectual_property", "Intellectual Property and Ownership", [
        F("intellectual_property.patent_status", "Patent status", True),
        F("intellectual_property.ownership_claims", "Ownership", True),
        L("intellectual_property.licensing_restrictions", "Licensing restrictions"),
        L("intellectual_property.disclosed_prior_art", "Disclosed prior art")]),
    (11, "commercialization", "Commercialization Potential and Requirements", [
        P("commercialization.product_concept", "Product concept"),
        F("commercialization.documented_costs", "Documented costs", True),
        P("commercialization.manufacturing_requirements", "Manufacturing requirements", True),
        P("commercialization.scalability", "Scalability", True),
        P("commercialization.supply_chain", "Supply chain", True),
        P("commercialization.maintenance_requirements", "Maintenance requirements")]),
    (12, "partner_capabilities", "Required Industry Partner Capabilities", [
        L("partner_requirements.required_capabilities", "Required capabilities", True),
        L("partner_requirements.potential_partner_types", "Potential partner types")]),
    (13, "limitations_risks", "Technical Limitations and Risks", [
        L("development.technical_limitations", "Technical limitations", True),
        L("gaps.regulatory_questions", "Regulatory questions")]),
    (14, "gaps_next_steps", "Research Gaps, Missing Information and Recommended Next Steps", [
        L("gaps.missing_tests", "Missing tests"),
        L("gaps.missing_evidence", "Missing evidence"),
        L("gaps.engineering_requirements", "Engineering requirements"),
        L("gaps.funding_requirements", "Funding requirements")]),
    (15, "sources", "Source Documents and References", []),
]
SECTION_OF = {el.path: number for number, _, _, els in SECTIONS for el in els}

# "Partly documented": an empty field whose subject is covered by related
# documented fields. The report points to them; it never writes the field.
RELATED: dict[str, list[tuple[str, str]]] = {
    "problem_solution.working_mechanism": [
        ("technology.components", "core components"),
        ("technology.techniques", "key techniques"),
        ("problem_solution.solution", "proposed solution")],
    "development.testing_methods": [
        ("development.experimental_results", "experimental results"),
        ("development.prototype_status", "prototype status")],
}

# Keyword matching of the AI's free-text missing-information notes to report
# fields: (anchor tokens, extra tokens a generic note may contain). Used only
# to avoid repeating or contradicting the report; the saved notes are untouched.
FIELD_TERMS: dict[str, tuple[str, set[str]]] = {
    "identity.concise_summary": (r"summary", {"invention", "concise"}),
    "technology.primary_domain": (r"domain", {"technical", "primary"}),
    "problem_solution.problem": (r"problems?", {"statement"}),
    "problem_solution.objective": (r"objectives?|goals?|aims?", set()),
    "problem_solution.solution": (r"solutions?", {"proposed"}),
    "problem_solution.working_mechanism": (r"mechanisms?|principles?|operation",
                                           {"working", "operating", "how", "works"}),
    "technology.components": (r"components?", {"core", "parts"}),
    "technology.novelty": (r"novelty|novel", {"claims", "claim"}),
    "development.prototype_status": (r"prototypes?", {"status"}),
    "development.experimental_results": (r"results?|measurements?|performance",
                                         {"experimental", "test", "testing", "tests"}),
    "development.testing_methods": (r"methods?|methodology|procedures?|protocols?|testing|tests?",
                                    {"testing", "test", "tests"}),
    "applications.use_cases": (r"uses?|cases?|applications?", set()),
    "applications.industries": (r"industr\w*|sectors?", {"target", "relevant"}),
    "applications.target_customers": (r"customers?|buyers?", {"target"}),
    "intellectual_property.patent_status": (r"patents?|patenting", {"status", "filing"}),
    "intellectual_property.ownership_claims": (r"ownership|owners?", set()),
    "commercialization.documented_costs": (r"costs?|prices?|pricing|bom", {"unit", "estimate", "estimates"}),
    "commercialization.manufacturing_requirements": (r"manufactur\w*|fabrication|production",
                                                     {"requirements", "process", "processes"}),
    "commercialization.scalability": (r"scal\w*", {"up"}),
    "commercialization.supply_chain": (r"supply|suppliers?|sourcing", {"chain"}),
    "commercialization.maintenance_requirements": (r"maintenance|maintain\w*", {"requirements"}),
    "partner_requirements.required_capabilities": (r"capabilit\w*", {"partner", "partners", "industry"}),
    "development.technical_limitations": (r"limitations?|risks?", {"technical"}),
}
_STOP = {
    "no", "not", "none", "missing", "lack", "lacking", "absent", "undocumented",
    "unavailable", "available", "documented", "provided", "described", "stated",
    "specified", "identified", "given", "found", "mentioned", "information", "info",
    "details", "detail", "detailed", "data", "specific", "explicit", "clear", "any",
    "the", "a", "an", "of", "on", "about", "for", "in", "is", "are", "was", "were",
    "has", "have", "been", "regarding", "uploaded", "materials", "documents",
    "document", "sources", "and", "or", "its", "invention", "innovator", "review",
    "needed", "yet", "list", "description", "descriptions",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(profile: InventionAIProfile, path: str):
    obj = profile
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _present(claim) -> bool:
    return (isinstance(claim, Claim) and claim.classification != "missing"
            and bool((claim.value or "").strip()))


def claim_status(claim: Claim) -> str:
    explanation = (claim.explanation or "").strip()
    if explanation.startswith("UNVERIFIED"):
        return "unverified"
    if explanation.startswith("Innovator-edited"):
        return "edited"
    return {
        "document_fact": "verified",
        "registration_fact": "declared",
        "inference": "interpretation",
        "recommendation": "recommendation",
    }.get(claim.classification, "interpretation")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _humanize(path: str) -> str:
    last = path.split(".")[-1]
    text = last.replace("_", " ").strip().capitalize() or path
    return re.sub(r"\btrl\b", "TRL", text, flags=re.IGNORECASE)


class _Citations:
    """Numbers each (file, page, section) once; collects distinct excerpts."""

    def __init__(self):
        self._numbers: dict[tuple, int] = {}
        self.entries: list[SourceEntry] = []

    def register(self, evidence: list[Evidence]) -> list[int]:
        numbers = []
        for ev in evidence:
            key = (ev.source_file, ev.page, (ev.section or "").strip() or None)
            if key not in self._numbers:
                self._numbers[key] = len(self.entries) + 1
                self.entries.append(SourceEntry(
                    number=self._numbers[key], source_file=key[0], page=key[1], section=key[2]))
            entry = self.entries[self._numbers[key] - 1]
            excerpt = " ".join((ev.excerpt or "").split())
            # Only real text: an excerpt of quotes/punctuation shows as empty.
            if re.search(r"\w", excerpt) and _norm(excerpt) not in {_norm(e) for e in entry.excerpts}:
                entry.excerpts.append(excerpt)
            if self._numbers[key] not in numbers:
                numbers.append(self._numbers[key])
        return sorted(numbers)


def _item(claim: Claim, path: str, citations: _Citations, name: str | None = None) -> ReportItem:
    status = claim_status(claim)
    return ReportItem(text=" ".join(claim.value.split()), name=name, status=status,
                      label=STATUS_LABELS[status], citations=citations.register(claim.evidence),
                      path=path)


def _joined(claims: list[Claim], path: str, citations: _Citations, name: str) -> ReportItem:
    statuses = [claim_status(c) for c in claims]
    weakest = max(statuses, key=_WEAKNESS.index)
    numbers = sorted({n for c in claims for n in citations.register(c.evidence)})
    return ReportItem(text="; ".join(" ".join(c.value.split()) for c in claims), name=name,
                      status=weakest, label=STATUS_LABELS[weakest], citations=numbers, path=path)


def _discrepancy_items(profile: InventionAIProfile, citations: _Citations) -> list[ReportItem]:
    items = []
    for index, d in enumerate(profile.discrepancies):
        field = _humanize(d.field)
        if d.kind == "between_documents":
            text = (f"{field}: the documents disagree — “{d.document_value}” versus "
                    f"“{d.other_document_value}”. Not resolved; innovator review required.")
            status = "contradiction"
        else:
            text = (f"{field}: the registration states “{d.registration_value}”, but the "
                    f"documents state “{d.document_value}”.")
            status = "discrepancy"
        if d.explanation:
            text += f" {d.explanation.strip()}"
        items.append(ReportItem(text=text, status=status, label=STATUS_LABELS[status],
                                citations=citations.register(d.evidence),
                                path=f"discrepancies[{index}]"))
    return items


def _has(profile: InventionAIProfile, path: str) -> bool:
    value = _get(profile, path)
    if isinstance(value, list):
        return any(_present(c) for c in value)
    return _present(value)


def _documented(profile: InventionAIProfile, path: str) -> bool:
    """True only for verified document facts with a cited source passage.

    AI interpretations, recommendations, registration data, innovator edits
    and UNVERIFIED statements never count as "documented information".
    """
    value = _get(profile, path)
    claims = value if isinstance(value, list) else [value]
    return any(_present(c) and claim_status(c) == "verified" and c.evidence for c in claims)


def _match_field(note: str) -> tuple[str | None, bool]:
    """(best-matching field path or None, whether the note is generic).

    Generic = the note names only the field itself ("Supply chain information
    not documented"); specific notes name a narrower gap and are always kept.
    """
    tokens = [t for t in re.findall(r"[a-z0-9]+", note.casefold()) if t not in _STOP]
    best, best_hits = None, 0
    for path, (anchor, _) in FIELD_TERMS.items():
        hits = sum(1 for t in tokens if re.fullmatch(anchor, t))
        if hits > best_hits:
            best, best_hits = path, hits
    if best is None:
        return None, False
    anchor, extra = FIELD_TERMS[best]
    generic = all(re.fullmatch(anchor, t) or t in extra for t in tokens)
    return best, generic


def _human_time(value) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC").lstrip("0")


def _collapse_labels(block: ReportBlock) -> None:
    """Show a shared interpretation/recommendation/declared label once."""
    if block.kind == "note" or not block.items:
        return
    # Cited document facts are recognisable by their [n]; when every OTHER
    # item shares one status, label it once ('... unless cited'). That short
    # form is used only if none of the other items carries a citation, so a
    # cited AI interpretation is never mistaken for a verified document fact.
    cited = [i for i in block.items if i.status == "verified"]
    rest = [i for i in block.items if i.status != "verified"]
    statuses = {item.status for item in rest}
    if cited and any(i.citations for i in rest):
        return                                        # keep per-item labels
    if (rest and len(statuses) == 1 and (status := statuses.pop()) in BLOCK_LABELS
            and all(i.citations for i in cited)):
        block.label = BLOCK_LABELS[status] + (" unless cited" if cited else "")
        block.status = status
        for item in rest:
            item.label = None


def _model_line(profile: InventionAIProfile, prefix: str) -> str | None:
    for warning in profile.quality_warnings:
        if warning.startswith(prefix):
            return warning
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_report(profile_data, draft_meta: dict | None = None) -> ReportDocument:
    """Render saved profile data (dict or model) into one report document.

    draft_meta: generation_number, updated_at (editable draft) or, for a
    submitted snapshot, submission_id, submitted_at and invention_id.
    """
    profile = (profile_data if isinstance(profile_data, InventionAIProfile)
               else InventionAIProfile.model_validate(profile_data))
    meta = draft_meta or {}
    citations = _Citations()
    sections: list[ReportSection] = []
    missing_everywhere: list[tuple[str, str, int]] = []    # (path, label, section)
    partial_everywhere: list[tuple[str, str, int, str]] = []

    for number, key, title, elements in SECTIONS:
        if key == "sources":
            continue
        blocks: list[ReportBlock] = []
        fields: list[ReportField] = []
        missing: list[str] = []
        partial: list[str] = []
        seen: set[str] = set()
        facts: list[ReportItem] = []

        def flush_facts():
            if facts:
                blocks.append(ReportBlock(kind="facts", items=list(facts)))
                facts.clear()

        def absent(el, number=number, missing=missing, partial=partial):
            if not el.important:
                return
            related = [(label, SECTION_OF[path]) for path, label in RELATED.get(el.path, [])
                       if _documented(profile, path)]
            if related:
                local = ", ".join(
                    f"{label} ({'this section' if n == number else f'Section {n}'})"
                    for label, n in related)
                partial.append(f"{el.label}: no separate description was extracted from the "
                               f"uploaded materials. Related documented information: {local}.")
                partial_everywhere.append((el.path, el.label, number, ", ".join(
                    f"{label} (Section {n})" for label, n in related)))
            else:
                missing.append(el.label)
                missing_everywhere.append((el.path, el.label, number))

        for el in elements:
            value = _get(profile, el.path)
            is_list = el.kind in ("facts_list", "bullets", "table")
            fields.append(ReportField(path=el.path, label=el.label,
                                      kind="list" if is_list else "text"))
            if is_list:
                present = [c for c in value if _present(c)]
                claims = [c for c in present if _norm(c.value) not in seen]
                if not claims:
                    if not present:          # items shown earlier are not "missing"
                        absent(el)
                    continue
                seen.update(_norm(c.value) for c in claims)
                indexed = [(i, c) for i, c in enumerate(value) if c in claims]
                if el.kind == "facts_list":
                    facts.append(_joined(claims, el.path, citations, el.label))
                    continue
                flush_facts()
                blocks.append(ReportBlock(
                    kind="table" if el.kind == "table" else "bullets", heading=el.label,
                    items=[_item(c, f"{el.path}[{i}]", citations) for i, c in indexed]))
                continue
            if not _present(value):
                absent(el)
                continue
            if _norm(value.value) in seen:
                continue
            seen.add(_norm(value.value))
            if el.kind == "fact":
                facts.append(_item(value, el.path, citations, name=el.label))
            else:
                flush_facts()
                heading = el.label if len([e for e in elements if e.kind == "prose"]) > 1 else None
                blocks.append(ReportBlock(kind="paragraph", heading=heading,
                                          items=[_item(value, el.path, citations)]))
        flush_facts()

        # Section-specific content that is not a plain claim field.
        if key == "novelty" and any(b.items for b in blocks):
            blocks.append(ReportBlock(kind="note", text=(
                "Novelty statements are the inventors' claims and have not been "
                "independently assessed.")))
        if key == "prototype_readiness":
            trl = []
            if profile.readiness.reported_trl is not None:
                trl.append(ReportItem(text=f"TRL {profile.readiness.reported_trl}",
                                      name="Declared TRL", status="declared",
                                      label=STATUS_LABELS["declared"],
                                      path="readiness.reported_trl"))
            if profile.readiness.suggested_trl is not None:
                matches = profile.readiness.suggested_trl == profile.readiness.reported_trl
                trl.append(ReportItem(text=f"TRL {profile.readiness.suggested_trl} " + (
                                          "(matches the declared TRL)" if matches else
                                          "(indicative estimate; not a certification)"),
                                      name="AI-estimated TRL", status="interpretation",
                                      label=STATUS_LABELS["interpretation"],
                                      path="readiness.suggested_trl"))
            if trl:
                blocks.insert(1 if blocks and blocks[0].kind == "paragraph" else 0,
                              ReportBlock(kind="facts", items=trl))
            fields.append(ReportField(path="readiness.suggested_trl",
                                      label="AI-estimated TRL (1-9)", kind="number"))
        if key == "limitations_risks":
            items = _discrepancy_items(profile, citations)
            if items:
                blocks.append(ReportBlock(kind="bullets", heading="Contradictions and discrepancies",
                                          items=items))

        if key != "gaps_next_steps":
            for text in partial:
                blocks.append(ReportBlock(kind="note", text=text))
            if missing:
                documented = bool(partial) or any(b.kind != "note" for b in blocks)
                text = (NOT_DOCUMENTED if not documented else
                        f"{', '.join(missing)}: {NOT_DOCUMENTED[0].lower() + NOT_DOCUMENTED[1:]}")
                blocks.append(ReportBlock(kind="note", text=text))
            elif not blocks:
                blocks.append(ReportBlock(kind="note", text=NOT_DOCUMENTED))
        for block in blocks:
            _collapse_labels(block)
        sections.append(ReportSection(number=number, key=key, title=title, blocks=blocks,
                                      fields=fields,
                                      documented=any(b.kind != "note" for b in blocks)))

    # Section 14: gaps + ONE reconciled list of unavailable information.
    gaps = next(s for s in sections if s.key == "gaps_next_steps")
    shown = {_norm(i.text) for b in gaps.blocks for i in b.items}
    missing_paths = {path: n for path, _, n in missing_everywhere}
    partial_paths = {path for path, *_ in partial_everywhere}
    covered: set[str] = set()
    not_documented: list[str] = []
    for note in dict.fromkeys(m.strip() for m in profile.missing_information if m.strip()):
        if _norm(note) in shown:
            continue                                   # already listed above as a gap
        path, generic = _match_field(note)
        if path in missing_paths:
            covered.add(path)                          # AI wording replaces the generic line
            not_documented.append(f"{note.rstrip('. ')} (Section {missing_paths[path]})")
        elif path and generic and (path in partial_paths or _has(profile, path)):
            continue                                   # stale: the field is in the report
        elif path in SECTION_OF and not re.search(r"\(Section \d+\)", note):
            not_documented.append(f"{note.rstrip('. ')} (Section {SECTION_OF[path]})")
        else:
            not_documented.append(note)
    not_documented += [f"{label} (Section {n})" for path, label, n in missing_everywhere
                       if path not in covered]
    unique: dict[str, str] = {}
    for entry in not_documented:                       # first wording wins, case-insensitive
        unique.setdefault(_norm(entry), entry)
    not_documented = list(unique.values())
    if partial_everywhere:
        gaps.blocks.append(ReportBlock(
            kind="bullets", heading="Partly documented",
            items=[ReportItem(text=f"{label} (Section {n}) — related information: {where}",
                              status="info") for _, label, n, where in partial_everywhere]))
    if not_documented:
        gaps.blocks.append(ReportBlock(
            kind="bullets", heading="Information not documented in the uploaded materials",
            items=[ReportItem(text=m, status="info") for m in not_documented]))
    if partial_everywhere or not_documented:
        gaps.blocks.append(ReportBlock(kind="note", text=(
            "Information that is not documented may still exist; it was not found "
            "in the uploaded materials.")))
    if not gaps.blocks:
        gaps.blocks.append(ReportBlock(kind="note", text=NOT_DOCUMENTED))
    gaps.fields.append(ReportField(path="missing_information",
                                   label="Missing information (one per line)", kind="lines"))
    gaps.documented = any(b.kind != "note" for b in gaps.blocks)

    # Section 15: documents analysed / excluded; numbered references.
    used = [d for d in profile.document_relevance if d.relevance == "relevant"]
    excluded = [d for d in profile.document_relevance if d.relevance != "relevant"]
    source_blocks = []
    if used:
        source_blocks.append(ReportBlock(kind="bullets", heading="Documents analysed", items=[
            ReportItem(text=f"{d.filename} — {d.explanation}".strip(" —"), status="info")
            for d in used]))
    if excluded:
        source_blocks.append(ReportBlock(kind="bullets", heading="Documents excluded from the analysis",
                                         items=[ReportItem(text=f"{d.filename} ({d.relevance}) — "
                                                                f"{d.explanation}".strip(" —"),
                                                           status="info") for d in excluded]))
    if not citations.entries:
        source_blocks.append(ReportBlock(kind="note", text="No verified source citations."))
    for entry in citations.entries:
        if not entry.excerpts:
            entry.note = NO_EXCERPT
    sections.append(ReportSection(number=15, key="sources", title="Source Documents and References",
                                  blocks=source_blocks, documented=bool(used or citations.entries)))

    title = (profile.identity.title.value.strip()
             if _present(profile.identity.title) else "Untitled invention")

    # Short header: what the invention is and which version this is.
    metadata = []
    if _present(profile.technology.primary_domain):
        metadata.append(MetaEntry(name="Technical domain", value=profile.technology.primary_domain.value))
    if profile.readiness.reported_trl is not None:
        metadata.append(MetaEntry(name="Declared TRL", value=str(profile.readiness.reported_trl)))
    if meta.get("submission_id"):
        submitted = _human_time(meta.get("submitted_at"))
        version = ("Submitted snapshot" + (f" of {submitted}" if submitted else "")
                   + " — a fixed copy; later draft edits do not change it")
        metadata.append(MetaEntry(name="Review status", value=REVIEW_STATUS))
    else:
        saved = _human_time(meta.get("updated_at"))
        version = "Current editable draft" + (f" — last saved {saved}" if saved else "")

    # Technical record for the appendix / diagnostics only.
    processing = []
    for name, value in (("Invention ID", meta.get("invention_id")),
                        ("Submission ID", meta.get("submission_id")),
                        ("AI generation", meta.get("generation_number"))):
        if value not in (None, ""):
            processing.append(MetaEntry(name=name, value=str(value)))
    provider = _model_line(profile, "AI provider:")
    if provider:
        processing.append(MetaEntry(name="AI model",
                                    value=provider.removeprefix("AI provider:").strip().rstrip(".")))
    consent = _model_line(profile, "Cloud processing:")
    if consent:
        processing.append(MetaEntry(name="Cloud processing",
                                    value=consent.removeprefix("Cloud processing:").strip()))
    diagnostics = [w for w in profile.quality_warnings
                   if not w.startswith(("AI provider:", "Cloud processing:"))]

    return ReportDocument(title=title, version=version, metadata=metadata, processing=processing,
                          sections=sections, sources=citations.entries, diagnostics=diagnostics)


def render_report_json(profile_data, draft_meta: dict | None = None) -> dict:
    return render_report(profile_data, draft_meta).model_dump(mode="json")
