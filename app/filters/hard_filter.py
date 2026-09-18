"""Deterministic, no-LLM eligibility filter (Story 3.1).

Runs before any Gemini call so obviously ineligible tenders never spend
tokens: geography, contract size, role, availability, deadline. Returns a
reason string ready to drop straight into `TenderAnalysis.hard_reject_reason`,
or `None` for a survivor that goes on to LLM reasoning.
"""

from datetime import date

from app.models import CompanyProfile, Tender


def _distance_km(tender: Tender, company: CompanyProfile) -> float:
    """Tenders only carry distance from the two anchor cities (Profile A's
    Augsburg, Profile B's Plauen), not a generic distance to an arbitrary
    company location. Mirrors the frontend's TenderCardComponent.distanceKm
    convention (tender-card.ts) so both sides agree on a custom profile's
    verdict: Plauen distance for profile-b, Augsburg distance otherwise."""
    if company.id == "profile-b":
        return tender.distance_from_plauen_km
    return tender.distance_from_augsburg_km


def hard_filter(tender: Tender, company: CompanyProfile) -> str | None:
    """Returns a human-readable reject reason, or None if the tender survives."""

    distance_km = _distance_km(tender, company)
    if distance_km > company.distance_limit_km:
        return f"TOO_FAR: {distance_km:g}km exceeds {company.distance_limit_km:g}km limit"

    if tender.value_eur is not None:
        if tender.value_eur > company.max_contract_eur:
            return f"TOO_LARGE: €{tender.value_eur:,.0f} exceeds max €{company.max_contract_eur:,.0f}"
        if tender.value_eur < company.min_contract_eur:
            return f"TOO_SMALL: €{tender.value_eur:,.0f} below min €{company.min_contract_eur:,.0f}"

    if tender.role_required is not None and tender.role_required != company.role:
        return f"WRONG_ROLE: tender requires {tender.role_required}, company is {company.role}"

    if tender.construction_window_start and company.available_from:
        if tender.construction_window_start < company.available_from:
            return (
                f"NO_CAPACITY: project starts {tender.construction_window_start}, "
                f"company free from {company.available_from}"
            )

    if tender.deadline and tender.deadline < date.today().isoformat():
        return "EXPIRED: submission deadline has passed"

    return None
