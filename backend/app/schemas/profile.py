
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


# -----------------------------------------
# Evidence and claim classification
# -----------------------------------------

ClaimType = Literal[
    "document_fact",
    "registration_fact",
    "inference",
    "recommendation",
    "missing",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(
        description="Exact source document filename"
    )

    page: int | None = Field(
        default=None,
        ge=1
    )

    section: str | None = None

    excerpt: str | None = Field(
        default=None,
        description="Short supporting text, if available"
    )


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(
        default=None,
        description=(
            "The actual information being extracted. "
            "Use null ONLY when classification is missing. "
            "If a meaningful value is provided, classify "
            "it as document_fact, registration_fact, "
            "inference, or recommendation."
        )
    )

    # FIX: Classification is now REQUIRED.
    # The AI model must explicitly decide the claim type.
    classification: ClaimType = Field(
        ...,
        description=(
            "REQUIRED classification for every claim. "
            "document_fact: explicitly supported by "
            "uploaded document text and source evidence. "
            "registration_fact: directly supplied in the "
            "invention registration. "
            "inference: AI interpretation not directly "
            "established by source evidence. "
            "recommendation: suggested future action. "
            "missing: information is unavailable; "
            "value MUST be null. "
            "Never use missing with a non-null value."
        )
    )

    evidence: list[Evidence] = Field(
        default_factory=list,
        description=(
            "Source evidence for document facts. "
            "Include source filename and a short exact "
            "excerpt, with page or section if known. "
            "Do not invent document references."
        )
    )

    explanation: str | None = Field(
        default=None,
        description=(
            "Optional explanation of uncertainty, "
            "reasoning, or evidence limitations."
        )
    )

    @model_validator(mode="after")
    def validate_claim(self):

        # Missing claims cannot contain values.
        if self.classification == "missing":

            if self.value is not None:
                raise ValueError(
                    "Missing claims must have null values."
                )

        # All other classifications require values.
        elif not self.value or not self.value.strip():
            raise ValueError(
                "Non-missing claims require a value."
            )

        # Document facts must contain evidence.
        if (
            self.classification == "document_fact"
            and not self.evidence
        ):
            raise ValueError(
                "Document facts require source evidence."
            )

        return self


# -----------------------------------------
# 1. Invention identity
# -----------------------------------------

class InventionIdentity(BaseModel):
    title: Claim | None = None
    concise_summary: Claim | None = None
    detailed_summary: Claim | None = None

    inventors: list[Claim] = Field(
        default_factory=list
    )

    institution: Claim | None = None

    keywords: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 2. Problem and solution
# -----------------------------------------

class ProblemSolution(BaseModel):
    problem: Claim | None = None
    solution: Claim | None = None
    working_mechanism: Claim | None = None
    objective: Claim | None = None


# -----------------------------------------
# 3. Technical information
# -----------------------------------------

class TechnicalProfile(BaseModel):
    primary_domain: Claim | None = None

    secondary_domains: list[Claim] = Field(
        default_factory=list
    )

    techniques: list[Claim] = Field(
        default_factory=list
    )

    components: list[Claim] = Field(
        default_factory=list
    )

    novelty: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 4. Applications
# -----------------------------------------

class ApplicationsProfile(BaseModel):
    use_cases: list[Claim] = Field(
        default_factory=list
    )

    industries: list[Claim] = Field(
        default_factory=list
    )

    target_customers: list[Claim] = Field(
        default_factory=list
    )

    product_forms: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 5. Development and validation
# -----------------------------------------

class DevelopmentProfile(BaseModel):
    prototype_status: Claim | None = None

    testing_methods: list[Claim] = Field(
        default_factory=list
    )

    experimental_results: list[Claim] = Field(
        default_factory=list
    )

    technical_limitations: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 6. Technology readiness
# -----------------------------------------

class ReadinessProfile(BaseModel):
    reported_trl: int | None = Field(
        default=None,
        ge=1,
        le=9
    )

    suggested_trl: int | None = Field(
        default=None,
        ge=1,
        le=9
    )

    justification: Claim | None = None

    verification_needed: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 7. Intellectual property
# -----------------------------------------

class IntellectualPropertyProfile(BaseModel):
    patent_status: Claim | None = None
    ownership_claims: Claim | None = None

    disclosed_prior_art: list[Claim] = Field(
        default_factory=list
    )

    licensing_restrictions: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 8. Commercialization
# -----------------------------------------

class CommercializationProfile(BaseModel):
    product_concept: Claim | None = None
    manufacturing_requirements: Claim | None = None
    scalability: Claim | None = None
    supply_chain: Claim | None = None
    documented_costs: Claim | None = None
    maintenance_requirements: Claim | None = None


# -----------------------------------------
# 9. Partner requirements
# No actual company matching in Phase 4.
# -----------------------------------------

class PartnerRequirements(BaseModel):
    required_capabilities: list[Claim] = Field(
        default_factory=list
    )

    potential_partner_types: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# 10. Gaps and further requirements
# -----------------------------------------

class ResearchGaps(BaseModel):
    missing_tests: list[Claim] = Field(
        default_factory=list
    )

    regulatory_questions: list[Claim] = Field(
        default_factory=list
    )

    engineering_requirements: list[Claim] = Field(
        default_factory=list
    )

    funding_requirements: list[Claim] = Field(
        default_factory=list
    )

    missing_evidence: list[Claim] = Field(
        default_factory=list
    )


# -----------------------------------------
# Document relevance assessment
# -----------------------------------------

class DocumentRelevance(BaseModel):
    filename: str

    relevance: Literal[
        "relevant",
        "unrelated",
        "uncertain"
    ]

    explanation: str


# -----------------------------------------
# Discrepancy reporting
# -----------------------------------------

class ProfileDiscrepancy(BaseModel):
    field: str

    # Additive (backward compatible): existing drafts have no "kind" and are
    # read as registration_vs_document. Defaults are plain strings (not
    # nullable) to keep the Gemini response schema simple.
    kind: Literal[
        "registration_vs_document",
        "between_documents",
    ] = "registration_vs_document"

    registration_value: str = ""
    document_value: str

    # For between_documents: the conflicting value from the other document.
    other_document_value: str = ""

    evidence: list[Evidence] = Field(
        default_factory=list
    )

    explanation: str | None = None


# -----------------------------------------
# Complete AI-generated invention profile
# -----------------------------------------

class InventionAIProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"

    identity: InventionIdentity = Field(
        default_factory=InventionIdentity
    )

    problem_solution: ProblemSolution = Field(
        default_factory=ProblemSolution
    )

    technology: TechnicalProfile = Field(
        default_factory=TechnicalProfile
    )

    applications: ApplicationsProfile = Field(
        default_factory=ApplicationsProfile
    )

    development: DevelopmentProfile = Field(
        default_factory=DevelopmentProfile
    )

    readiness: ReadinessProfile = Field(
        default_factory=ReadinessProfile
    )

    intellectual_property: IntellectualPropertyProfile = Field(
        default_factory=IntellectualPropertyProfile
    )

    commercialization: CommercializationProfile = Field(
        default_factory=CommercializationProfile
    )

    partner_requirements: PartnerRequirements = Field(
        default_factory=PartnerRequirements
    )

    gaps: ResearchGaps = Field(
        default_factory=ResearchGaps
    )

    document_relevance: list[DocumentRelevance] = Field(
        default_factory=list
    )

    discrepancies: list[ProfileDiscrepancy] = Field(
        default_factory=list
    )

    missing_information: list[str] = Field(
        default_factory=list
    )

    quality_warnings: list[str] = Field(
        default_factory=list
    )
