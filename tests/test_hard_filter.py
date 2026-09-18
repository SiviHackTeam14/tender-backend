from datetime import date, timedelta

from app.filters.hard_filter import hard_filter
from app.models import CompanyProfile, Tender

TODAY = date.today()
FAR_FUTURE = (TODAY + timedelta(days=365)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
LONG_AGO = (TODAY - timedelta(days=30)).isoformat()


def make_company(**overrides) -> CompanyProfile:
    defaults = dict(
        id="profile-a",
        name="Brenner & Sohn Tiefbau GmbH",
        location="Augsburg",
        nuts_code="DE27",
        distance_limit_km=150,
        focus_areas=["road_construction"],
        min_contract_eur=100_000,
        max_contract_eur=2_000_000,
        max_guarantee_eur=500_000,
        role="main_contractor",
        available_from=LONG_AGO,
        revenue_eur=31_000_000,
        reg_familiarity="very_high",
        certifications=["ISO_9001"],
        can_show_references=["road rehabilitation >€800k"],
        cannot_show=["bridges"],
    )
    defaults.update(overrides)
    return CompanyProfile(**defaults)


def make_tender(**overrides) -> Tender:
    defaults = dict(
        id="T001",
        title="Kreisstraßensanierung Königsbrunn",
        location="Königsbrunn, Bayern",
        nuts_code="DE27",
        distance_from_augsburg_km=10,
        distance_from_plauen_km=300,
        value_eur=500_000,
        trade_type="road_construction",
        role_required="main_contractor",
        deadline=FAR_FUTURE,
        construction_window_start=None,
        construction_window_end=None,
        references_required="2 road projects >€800k last 5 years",
        certifications_required=[],
        guarantee_required_eur=90_000,
        eigenleistung_min_pct=30,
        hidden_blockers=[],
        source_url="https://example.com/tender/t001",
        lv_url=None,
    )
    defaults.update(overrides)
    return Tender(**defaults)


def test_survives_all_checks():
    assert hard_filter(make_tender(), make_company()) is None


def test_too_far():
    tender = make_tender(distance_from_augsburg_km=200)
    company = make_company(distance_limit_km=150)
    assert hard_filter(tender, company) == "TOO_FAR: 200km exceeds 150km limit"


def test_too_large():
    tender = make_tender(value_eur=3_000_000)
    company = make_company(max_contract_eur=2_000_000)
    assert hard_filter(tender, company) == "TOO_LARGE: €3,000,000 exceeds max €2,000,000"


def test_too_small():
    tender = make_tender(value_eur=50_000)
    company = make_company(min_contract_eur=100_000)
    assert hard_filter(tender, company) == "TOO_SMALL: €50,000 below min €100,000"


def test_value_none_skips_size_check():
    tender = make_tender(value_eur=None)
    assert hard_filter(tender, make_company()) is None


def test_wrong_role():
    tender = make_tender(role_required="subcontractor")
    company = make_company(role="main_contractor")
    assert (
        hard_filter(tender, company)
        == "WRONG_ROLE: tender requires subcontractor, company is main_contractor"
    )


def test_role_required_none_skips_check():
    tender = make_tender(role_required=None)
    company = make_company(role="subcontractor")
    assert hard_filter(tender, company) is None


def test_no_capacity():
    tender = make_tender(construction_window_start=(TODAY + timedelta(days=1)).isoformat())
    company = make_company(available_from=FAR_FUTURE)
    reason = hard_filter(tender, company)
    assert reason is not None
    assert reason.startswith("NO_CAPACITY:")


def test_no_capacity_skipped_when_dates_missing():
    tender = make_tender(construction_window_start=None)
    company = make_company(available_from=FAR_FUTURE)
    assert hard_filter(tender, company) is None


def test_expired():
    tender = make_tender(deadline=YESTERDAY)
    assert hard_filter(tender, make_company()) == "EXPIRED: submission deadline has passed"


def test_distance_uses_plauen_field_for_profile_b():
    tender = make_tender(distance_from_augsburg_km=5, distance_from_plauen_km=250)
    company = make_company(id="profile-b", distance_limit_km=200)
    assert hard_filter(tender, company) == "TOO_FAR: 250km exceeds 200km limit"
