"""POST /api/analyze: hard filter then LLM reasoning (Story 3.2).

Thin glue only -- Story 3.1's `hard_filter()` and Story 2.2/2.3's
`reasoning.analyze()` own the actual logic. Hard-filtered rejects get a
placeholder `TenderAnalysis` (all criteria BLOCK) instead of being dropped,
matching Story 0.3's mock `analyses.json` shape so the frontend always gets
one entry per tender.
"""
from fastapi import APIRouter, HTTPException

from app.api.tenders import load_tenders
from app.filters.hard_filter import hard_filter
from app.llm import reasoning
from app.models import AnalysisCriteria, CompanyProfile, CriterionResult, Tender, TenderAnalysis

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


def _distance_km(tender: Tender, company: CompanyProfile) -> float:
    """Same convention as `hard_filter._distance_km`: tenders only carry
    distance from the two anchor cities, so mirror the id-based split here
    too (not `reasoning.compact_tender`'s location-text lookup, which raises
    for a custom Profile C whose `location` isn't literally Augsburg/Plauen)."""
    if company.id == "profile-b":
        return tender.distance_from_plauen_km
    return tender.distance_from_augsburg_km


def _hard_reject_analysis(tender_id: str, reason: str) -> TenderAnalysis:
    block = CriterionResult(status="BLOCK", reason=f"Excluded before reasoning — {reason}")
    return TenderAnalysis(
        tender_id=tender_id,
        verdict="REJECT",
        summary=f"Excluded before reasoning — {reason}",
        hard_reject_reason=reason,
        criteria=AnalysisCriteria(
            reference_eligibility=block,
            financial_capacity=block,
            regulatory_familiarity=block,
            competitive_position=block,
            strategic_fit=block,
        ),
    )


@router.post("", response_model=list[TenderAnalysis])
def post_analyze(profile: CompanyProfile):
    tenders = load_tenders()
    survivors: list[Tender] = []
    distances_km: dict[str, float] = {}
    results_by_id: dict[str, TenderAnalysis] = {}

    for tender in tenders:
        reason = hard_filter(tender, profile)
        if reason is not None:
            results_by_id[tender.id] = _hard_reject_analysis(tender.id, reason)
        else:
            survivors.append(tender)
            distances_km[tender.id] = _distance_km(tender, profile)

    try:
        analyses = reasoning.analyze(profile, survivors, distances_km=distances_km)
    except reasoning.ReasoningInputError as exc:
        raise HTTPException(503, detail={"code": "not_configured", "message": str(exc)})
    except reasoning.ReasoningError as exc:
        raise HTTPException(502, detail={"code": "reasoning_failed", "message": str(exc)})

    for analysis in analyses:
        results_by_id[analysis.tender_id] = analysis

    return [results_by_id[tender.id] for tender in tenders]
