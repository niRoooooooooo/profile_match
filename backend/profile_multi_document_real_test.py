"""Test the Profiling Agent using fictional invention documents."""

from app.agents.profiling_agent import build_profile_from_processed
from app.services.document_processor import ProcessingResult, ProcessedFile
from app.services.document_parser import ParsedDocument, DocumentChunk


def make_file(filename, text):
    return ProcessedFile(
        document_id=filename,
        filename=filename,
        parsed=ParsedDocument(
            filename=filename,
            file_type="pdf",
            total_pages=1,
            chunks=[
                DocumentChunk(
                    source_file=filename,
                    page=1,
                    text=text
                )
            ]
        )
    )


processed = ProcessingResult(
    invention_id="00000000-0000-0000-0000-000000000001",
    owner_id="00000000-0000-0000-0000-000000000002",
    invention={
        "title": "Smart Greenhouse Temperature Monitoring System",
        "abstract": "An IoT greenhouse monitoring invention",
        "domain": "Agricultural Technology",
        "trl": None,
        "ip_status": "Not filed",
        "inventors": ["Demo Inventor"],
        "keywords": ["IoT", "Greenhouse"]
    },
    documents=[
        make_file(
            "greenhouse_overview.pdf",
            """
            Smart Greenhouse Temperature Monitoring System.

            Problem: Farmers need to monitor greenhouse
            temperature remotely.

            Solution: The system uses an ESP32 controller,
            DHT22 sensor and Wi-Fi connectivity to collect
            temperature readings.

            A web dashboard displays sensor data.
            The objective is to let farmers monitor
            greenhouse conditions remotely.
            """
        ),
        make_file(
            "greenhouse_prototype.pdf",
            """
            Smart Greenhouse Temperature Monitoring System.

            A laboratory prototype was assembled using
            an ESP32 controller and DHT22 sensor.

            Temperature readings were demonstrated
            on a local web dashboard.

            No independent field testing was performed.

            Intended applications include greenhouse
            farming and agricultural monitoring.

            No patent application has been filed.

            Manufacturing costs and market demand
            have not been evaluated.
            """
        ),
        make_file(
            "unrelated_assignment.pdf",
            """
            Database Management Assignment.

            This document covers SQL joins,
            normalization and database indexing.
            """
        )
    ]
)


def show(claim):
    if claim is None:
        return "None"
    return f"{claim.value} [{claim.classification}]"


print("Starting Gemini profiling test (fictional data; live API call)...", flush=True)

try:
    result = build_profile_from_processed(processed)
    profile = result.profile

    print("\nPROFILE GENERATED: PASSED")

    print("\nINCLUDED DOCUMENTS:")
    print(result.included_documents)

    print("\nEXCLUDED DOCUMENTS:")
    print(result.excluded_documents)

    print("\nTITLE:")
    print(show(profile.identity.title))

    print("\nSUMMARY:")
    print(show(profile.identity.concise_summary))

    print("\nDOMAIN:")
    print(show(profile.technology.primary_domain))

    print("\nTECHNICAL COMPONENTS:")
    for component in profile.technology.components:
        print("-", show(component))
        for source in component.evidence:
            print(
                "  Evidence:",
                source.source_file,
                "Page:",
                source.page
            )

    print("\nAPPLICATIONS:")
    for application in profile.applications.use_cases:
        print("-", show(application))

    print("\nPROTOTYPE:")
    print(show(profile.development.prototype_status))

    print("\nPATENT:")
    print(show(profile.intellectual_property.patent_status))

    print("\nTRL:")
    print(profile.readiness.suggested_trl)

    print("\nWARNINGS:")
    for warning in result.warnings:
        print("-", warning)

    print("\nPYDANTIC VALIDATION: PASSED")

except Exception as error:
    print("\nTEST FAILED")
    print(type(error).__name__, str(error))

    if error.__cause__:
        print(
            "CAUSE:",
            type(error.__cause__).__name__,
            str(error.__cause__)
        )

