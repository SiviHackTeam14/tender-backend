"""Shared data contracts frozen in Epic 0. Field names/types must match the
TypeScript interfaces in `frontend/src/app/models/` exactly (Story 0.1)."""

from typing import Literal, Optional

from pydantic import BaseModel

Role = Literal["main_contractor", "subcontractor"]
RoleRequired = Literal["main_contractor", "subcontractor", "either"]
RegFamiliarity = Literal["low", "medium", "high", "very_high"]
CriterionStatus = Literal["PASS", "WARNING", "BLOCK"]
Verdict = Literal["BID", "MAYBE", "REJECT"]


class CompanyProfile(BaseModel):
    """A bidder's company profile used to filter and score tenders.

    No cross-field invariants (e.g. min_contract_eur <= max_contract_eur) are
    enforced here, matching the TS side — that logic belongs to Epic 3's
    hard-filter, not the shared model layer.
    """

    id: str
    name: str
    location: str
    nuts_code: str
    distance_limit_km: float
    focus_areas: list[str]
    min_contract_eur: float
    max_contract_eur: float
    max_guarantee_eur: float
    role: Role
    available_from: str  # ISO date
    revenue_eur: float
    reg_familiarity: RegFamiliarity
    certifications: list[str]
    can_show_references: list[str]
    cannot_show: list[str]


class Tender(BaseModel):
    """A published tender notice as consumed by the hard filter and LLM reasoning.

    No cross-field invariants (e.g. construction_window_start <=
    construction_window_end) are enforced here, matching the TS side.
    """

    id: str
    title: str
    location: str
    nuts_code: str
    distance_from_augsburg_km: float
    distance_from_plauen_km: float
    value_eur: Optional[float]
    trade_type: str
    role_required: RoleRequired
    deadline: str  # ISO date
    construction_window_start: Optional[str]
    construction_window_end: Optional[str]
    references_required: str
    certifications_required: list[str]
    guarantee_required_eur: Optional[float]
    eigenleistung_min_pct: Optional[float]
    hidden_blockers: list[str]
    source_url: str
    lv_url: Optional[str]


class CriterionResult(BaseModel):
    """The pass/warn/block verdict and reason for one scoring criterion."""

    status: CriterionStatus
    reason: str


class AnalysisCriteria(BaseModel):
    """The five fixed scoring criteria for a tender analysis.

    Named as its own model (the frozen spec describes this as an inline
    object type) so Pydantic validates the exact key set; Story 0.1 should
    mirror it as a named `AnalysisCriteria` TS interface to avoid drift.
    """

    reference_eligibility: CriterionResult
    financial_capacity: CriterionResult
    regulatory_familiarity: CriterionResult
    competitive_position: CriterionResult
    strategic_fit: CriterionResult


class TenderAnalysis(BaseModel):
    """The bid/no-bid verdict and per-criterion breakdown for one tender."""

    tender_id: str
    verdict: Verdict
    summary: str
    hard_reject_reason: Optional[str]
    criteria: AnalysisCriteria
