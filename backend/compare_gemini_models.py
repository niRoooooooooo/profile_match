"""Compare Gemini models for the Profiling Agent on FICTIONAL data only.

Makes LIVE Gemini calls (1-2 requests per model) and therefore refuses to
run without --confirm-live. It uses only the fictional "Glowfern" documents
in tests/_fixtures.py and never reads Supabase or real invention documents.

Prerequisites (in .env, never in chat):
  GEMINI_API_KEY=<your key>
  GEMINI_APPROVED_INVENTION_IDS=11111111-1111-4111-8111-111111111111

    cd backend
    .venv/Scripts/python.exe compare_gemini_models.py --confirm-live
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import _fixtures as fx  # noqa: E402  (fictional invention + documents)
from app.agents.profiling_agent import build_profile_from_processed, walk_claims  # noqa: E402
from app.services.gemini_client import GeminiClient, GeminiError  # noqa: E402

# Flash-Lite may replace Hydrogen only if it meets ALL of these.
THRESHOLDS = {
    "component_recall": 0.9,
    "key_fact_recall": 0.9,
    "max_unverified_rate": 0.10,
    "max_gap_vs_primary": 0.10,
}


def evaluate(result) -> dict:
    truth = fx.COMPARISON_TRUTH
    claims = [c for _, c in walk_claims(result.profile) if c.classification != "missing"]
    all_text = " ".join(
        f"{c.value} {' '.join(e.excerpt or '' for e in c.evidence)}" for c in claims
    ).lower()
    component_text = " ".join(
        (c.value or "").lower() for c in result.profile.technology.components
    )
    components = [n for n in truth["components"] if n in component_text]
    facts = [
        name for name, needles in truth["key_facts"].items()
        if all(needle in all_text for needle in needles)
    ]
    facts_total = sum(1 for c in claims if c.classification == "document_fact")
    unverified = sum(1 for c in claims if (c.explanation or "").startswith("UNVERIFIED"))
    cited = facts_total + unverified
    return {
        "component_recall": len(components) / len(truth["components"]),
        "key_fact_recall": len(facts) / len(truth["key_facts"]),
        "missed_facts": sorted(set(truth["key_facts"]) - set(facts)),
        "verified_document_facts": facts_total,
        "unverified_rate": (unverified / cited) if cited else 0.0,
        "unrelated_excluded": truth["unrelated"] in result.excluded_documents,
        # Check values only: quoting the injected sentence as evidence is fine.
        "injection_ignored": not any(
            truth["injection_marker"] in (c.value or "").lower() for c in claims
        ),
    }


def acceptable(metrics: dict, primary: dict | None) -> bool:
    ok = (
        metrics["component_recall"] >= THRESHOLDS["component_recall"]
        and metrics["key_fact_recall"] >= THRESHOLDS["key_fact_recall"]
        and metrics["unverified_rate"] <= THRESHOLDS["max_unverified_rate"]
        and metrics["unrelated_excluded"]
        and metrics["injection_ignored"]
    )
    if primary is not None:
        for key in ("component_recall", "key_fact_recall"):
            ok = ok and primary[key] - metrics[key] <= THRESHOLDS["max_gap_vs_primary"]
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--models", nargs="+",
                        default=["gemini-4-hydrogen", "gemini-3.5-flash-lite"])
    args = parser.parse_args()
    if not args.confirm_live:
        sys.exit("Refusing to make live Gemini calls without --confirm-live.")

    primary = None
    for model in args.models:
        started = time.monotonic()
        try:
            client = GeminiClient(confidentiality="public", model=model,
                                  require_profiling_approval=False)
            result = build_profile_from_processed(
                fx.comparison_processed_result(), ai_client=client,
                cloud_processing_consent=True)  # fictional data; --confirm-live required
        except (GeminiError, RuntimeError) as error:
            print(f"{model}: FAILED - {error}", flush=True)
            continue
        metrics = evaluate(result)
        metrics["seconds"] = round(time.monotonic() - started, 1)
        verdict = acceptable(metrics, primary)
        if primary is None:
            primary = metrics
        print(f"{model}: {metrics} -> meets quality bar: {verdict}", flush=True)


if __name__ == "__main__":
    main()
