from app.models import (
    AnalysisCriteria,
    CompanyProfile,
    CriterionResult,
    Tender,
    TenderAnalysis,
)


def test_company_profile_round_trip():
    profile = CompanyProfile(
        id="a",
        name="Brenner & Sohn Tiefbau GmbH",
        location="Augsburg",
        nuts_code="DE27",
        distance_limit_km=50,
        focus_areas=["roads", "sewers"],
        min_contract_eur=50000,
        max_contract_eur=2000000,
        max_guarantee_eur=100000,
        role="main_contractor",
        available_from="2026-01-01",
        revenue_eur=5000000,
        reg_familiarity="high",
        certifications=["ISO 9001"],
        can_show_references=["A61 resurfacing"],
        cannot_show=["rail-side"],
    )
    assert profile.model_dump()["role"] == "main_contractor"


def test_tender_allows_nullable_fields():
    tender = Tender(
        id="t1",
        title="Road rehabilitation",
        location="Augsburg",
        nuts_code="DE27",
        distance_from_augsburg_km=5,
        distance_from_plauen_km=300,
        value_eur=None,
        trade_type=None,
        role_required=None,
        deadline="2026-03-01",
        construction_window_start=None,
        construction_window_end=None,
        references_required=None,
        certifications_required=[],
        guarantee_required_eur=None,
        eigenleistung_min_pct=None,
        hidden_blockers=[],
        source_url="https://example.com/tender/t1",
        lv_url=None,
    )
    assert tender.value_eur is None
    assert tender.lv_url is None
    assert tender.trade_type is None
    assert tender.role_required is None
    assert tender.references_required is None
    assert tender.complexity_markers == []
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Tender.model_validate(tender.model_dump() | {"role_required": "either"})
    assert Tender.model_validate(tender.model_dump() | {
        "complexity_markers": ["Arbeiten im laufenden Betrieb"]
    }).complexity_markers == ["Arbeiten im laufenden Betrieb"]


def test_tender_analysis_criteria_requires_all_five_keys():
    analysis = TenderAnalysis(
        tender_id="t1",
        verdict="BID",
        summary="Strong match on references and geography.",
        hard_reject_reason=None,
        criteria=AnalysisCriteria(
            reference_eligibility=CriterionResult(status="PASS", reason="Road rehab refs match exactly"),
            financial_capacity=CriterionResult(status="PASS", reason="Within revenue band"),
            regulatory_familiarity=CriterionResult(status="WARNING", reason="Limited GAEB experience"),
            competitive_position=CriterionResult(status="PASS", reason="Local presence"),
            strategic_fit=CriterionResult(status="PASS", reason="Matches focus areas"),
        ),
    )
    dumped = analysis.model_dump()["criteria"]
    assert set(dumped.keys()) == {
        "reference_eligibility",
        "financial_capacity",
        "regulatory_familiarity",
        "competitive_position",
        "strategic_fit",
    }
