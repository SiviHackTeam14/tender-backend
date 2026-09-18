"""Regenerates Story 0.3 mock fixtures: profiles.json, tenders.json, analyses.json.

Source of truth for backend/app/data/*.json. Run this again (from a venv with
the backend's requirements installed) whenever backend/app/models.py changes,
to catch drift between the fixtures and the frozen contract:

    cd backend && source .venv/bin/activate && python scripts/generate_fixtures.py

After running, mirror the three files byte-identical into
frontend/src/app/data/ (Story 0.3's AC).
"""
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
BACKEND_DATA = BACKEND_ROOT / "app" / "data"

sys.path.insert(0, str(BACKEND_ROOT))

# ---------------------------------------------------------------------------
# profiles.json
# ---------------------------------------------------------------------------

PROFILE_A = {
    "id": "profile-a",
    "name": "Brenner & Sohn Tiefbau GmbH",
    "location": "Augsburg",
    "nuts_code": "DE27",
    "distance_limit_km": 150,
    "focus_areas": ["road_construction", "sewers", "pipelines", "earthworks", "municipal_civil"],
    "min_contract_eur": 400000,
    "max_contract_eur": 4000000,
    "max_guarantee_eur": 1500000,
    "role": "main_contractor",
    "available_from": "2027-03-01",
    "revenue_eur": 31000000,
    "reg_familiarity": "very_high",
    "certifications": ["ISO_9001"],
    "can_show_references": [
        "road rehabilitation >€800k",
        "sewer renewal",
        "site development",
    ],
    "cannot_show": ["rail-side", "bridges", "outside Germany"],
}

PROFILE_B = {
    "id": "profile-b",
    "name": "Elektro Vogtland GmbH",
    "location": "Plauen",
    "nuts_code": "DED4",
    "distance_limit_km": 200,
    "focus_areas": ["electrical_installation", "fire_alarm", "building_automation"],
    "min_contract_eur": 80000,
    "max_contract_eur": 900000,
    "max_guarantee_eur": 300000,
    "role": "subcontractor",
    "available_from": "2026-11-01",
    "revenue_eur": 8000000,
    "reg_familiarity": "high",
    "certifications": ["ISO_9001"],
    "can_show_references": [
        "school refurbishments",
        "hospital ward",
        "office fit-out",
        "care homes",
    ],
    "cannot_show": ["high voltage", "ATEX explosion-protected", "main contractor multi-trade"],
}

PROFILES = [PROFILE_A, PROFILE_B]

# ---------------------------------------------------------------------------
# tenders.json
# ---------------------------------------------------------------------------

TENDERS = [
    {
        "id": "T001",
        "title": "Kreisstraßensanierung Königsbrunn",
        "location": "Königsbrunn, Bayern",
        "nuts_code": "DE27",
        "distance_from_augsburg_km": 42,
        "distance_from_plauen_km": 335,
        "value_eur": 1200000,
        "trade_type": "road_construction",
        "role_required": "main_contractor",
        "deadline": "2026-11-10",
        "construction_window_start": "2027-04-01",
        "construction_window_end": "2027-09-30",
        "references_required": "At least 2 road rehabilitation projects >€800k completed in the last 5 years",
        "certifications_required": [],
        "guarantee_required_eur": 90000,
        "eigenleistung_min_pct": 30,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t001",
        "lv_url": None,
    },
    {
        "id": "T002",
        "title": "Kanalsanierung Friedberg",
        "location": "Friedberg, Bayern",
        "nuts_code": "DE27",
        "distance_from_augsburg_km": 22,
        "distance_from_plauen_km": 345,
        "value_eur": 850000,
        "trade_type": "sewers",
        "role_required": "main_contractor",
        "deadline": "2026-11-24",
        "construction_window_start": "2027-03-15",
        "construction_window_end": "2027-08-15",
        "references_required": "Comparable district sewer renewal project, minimum DN300, last 5 years",
        "certifications_required": [],
        "guarantee_required_eur": 65000,
        "eigenleistung_min_pct": 25,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t002",
        "lv_url": None,
    },
    {
        "id": "T003",
        "title": "Erschließung Neubaugebiet Gersthofen",
        "location": "Gersthofen, Bayern",
        "nuts_code": "DE27",
        "distance_from_augsburg_km": 8,
        "distance_from_plauen_km": 330,
        "value_eur": 2100000,
        "trade_type": "earthworks",
        "role_required": "main_contractor",
        "deadline": "2026-12-01",
        "construction_window_start": "2027-05-01",
        "construction_window_end": "2028-03-31",
        "references_required": "Housing-estate site development, minimum 3 hectares, last 8 years",
        "certifications_required": [],
        "guarantee_required_eur": 180000,
        "eigenleistung_min_pct": 40,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t003",
        "lv_url": None,
    },
    {
        "id": "T004",
        "title": "Sanierung Fußgängerbrücke Donauwörth",
        "location": "Donauwörth, Bayern",
        "nuts_code": "DE27",
        "distance_from_augsburg_km": 45,
        "distance_from_plauen_km": 370,
        "value_eur": 1400000,
        "trade_type": "bridge_construction",
        "role_required": "main_contractor",
        "deadline": "2026-11-17",
        "construction_window_start": "2027-03-01",
        "construction_window_end": "2027-10-31",
        "references_required": "At least one comparable bridge rehabilitation or new-build project executed as main contractor in the last 10 years",
        "certifications_required": [],
        "guarantee_required_eur": 110000,
        "eigenleistung_min_pct": 35,
        "hidden_blockers": [
            "Bridge rehabilitation reference is mandatory per tender conditions — no substitution accepted",
        ],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t004",
        "lv_url": None,
    },
    {
        "id": "T005",
        "title": "Elektroinstallation Schulsanierung Zwickau",
        "location": "Zwickau, Sachsen",
        "nuts_code": "DED4",
        "distance_from_augsburg_km": 340,
        "distance_from_plauen_km": 55,
        "value_eur": 420000,
        "trade_type": "electrical_installation",
        "role_required": "subcontractor",
        "deadline": "2026-11-05",
        "construction_window_start": "2027-01-15",
        "construction_window_end": "2027-07-31",
        "references_required": "At least one comparable school refurbishment electrical fit-out in the last 6 years",
        "certifications_required": [],
        "guarantee_required_eur": 35000,
        "eigenleistung_min_pct": None,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t005",
        "lv_url": None,
    },
    {
        "id": "T006",
        "title": "Elektro-Sanierung Krankenhausstation Plauen",
        "location": "Plauen, Sachsen",
        "nuts_code": "DED4",
        "distance_from_augsburg_km": 330,
        "distance_from_plauen_km": 6,
        "value_eur": 610000,
        "trade_type": "electrical_installation",
        "role_required": "subcontractor",
        "deadline": "2026-11-20",
        "construction_window_start": "2027-02-01",
        "construction_window_end": "2027-09-30",
        "references_required": "One hospital or comparable healthcare-facility electrical installation in the last 5 years",
        "certifications_required": [],
        "guarantee_required_eur": 45000,
        "eigenleistung_min_pct": None,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t006",
        "lv_url": None,
    },
    {
        "id": "T007",
        "title": "Büro Elektro-Ausbau Chemnitz",
        "location": "Chemnitz, Sachsen",
        "nuts_code": "DED2",
        "distance_from_augsburg_km": 350,
        "distance_from_plauen_km": 90,
        "value_eur": 260000,
        "trade_type": "electrical_installation",
        "role_required": "subcontractor",
        "deadline": "2026-11-28",
        "construction_window_start": "2027-01-01",
        "construction_window_end": "2027-05-31",
        "references_required": "One comparable office fit-out electrical installation in the last 5 years",
        "certifications_required": [],
        "guarantee_required_eur": 20000,
        "eigenleistung_min_pct": None,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t007",
        "lv_url": None,
    },
    {
        # Real tender from 33_61_2026_Ausschreibungsunterlagen/ (Story 0.3 mandated contrast case).
        "id": "T008",
        "title": "Sanierung Rolandbrunnen – Erneuerung Brunnentechnik",
        "location": "Nordhausen, Thüringen",
        "nuts_code": "DEG0",
        "distance_from_augsburg_km": 400,
        "distance_from_plauen_km": 160,
        "value_eur": None,
        "trade_type": "water_technology",
        "role_required": None,
        "deadline": "2026-10-07",
        "construction_window_start": None,
        "construction_window_end": None,
        "references_required": "Nachweis als erfahrener Wassertechnik-Fachbetrieb (LV Vorbemerkungen); comparable public fountain/water-feature technology installation",
        "certifications_required": ["DIN_EN_1090_stainless_welding"],
        "guarantee_required_eur": None,
        "eigenleistung_min_pct": None,
        "hidden_blockers": [
            "Requires a certified Wassertechnik-Fachbetrieb to deliver the whole water system as one closed scope (LV Vorbemerkungen)",
            "V2A stainless-steel basin lining must be welded on-site by a holder of a valid DIN EN 1090 welding certificate",
        ],
        "source_url": "https://www.evergabe-online.info/ (Stadtverwaltung Nordhausen, Vergabenummer 33/61/2026)",
        "lv_url": "33_61_2026_Ausschreibungsunterlagen/Vergabeunterlagen/LV_20260904_Nordhausen_Rolandbrunnen.pdf",
    },
    {
        "id": "T009",
        "title": "Umspannwerk-Ausbau Reichenbach",
        "location": "Reichenbach im Vogtland, Sachsen",
        "nuts_code": "DED4",
        "distance_from_augsburg_km": 325,
        "distance_from_plauen_km": 15,
        "value_eur": 780000,
        "trade_type": "high_voltage_electrical",
        "role_required": "subcontractor",
        "deadline": "2026-12-10",
        "construction_window_start": "2027-03-01",
        "construction_window_end": "2027-08-31",
        "references_required": "Proven experience with 20kV/30kV substation installations, minimum 2 references",
        "certifications_required": ["high_voltage_switchgear_qualification"],
        "guarantee_required_eur": 60000,
        "eigenleistung_min_pct": None,
        "hidden_blockers": [
            "Requires high-voltage switchgear (>1kV) qualification — explicitly outside the company's certified scope",
        ],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t009",
        "lv_url": None,
    },
    {
        "id": "T010",
        "title": "Sanierung Dorfstraße mit Kanalanschluss Zusmarshausen",
        "location": "Zusmarshausen, Bayern",
        "nuts_code": "DE27",
        "distance_from_augsburg_km": 18,
        "distance_from_plauen_km": 335,
        "value_eur": 3800000,
        "trade_type": "municipal_civil",
        "role_required": "main_contractor",
        "deadline": "2026-12-15",
        "construction_window_start": "2027-06-01",
        "construction_window_end": "2028-05-31",
        "references_required": "At least 2 municipal civil engineering projects >€2M in the last 5 years, one as sole main contractor",
        "certifications_required": [],
        "guarantee_required_eur": 1420000,
        "eigenleistung_min_pct": 45,
        "hidden_blockers": [],
        "source_url": "https://oeffentlichevergabe.de/notice/mock-t010",
        "lv_url": None,
    },
]

# ---------------------------------------------------------------------------
# analyses.json — pre-computed TenderAnalysis[] per profile, per tender.
# ---------------------------------------------------------------------------


def crit(status, reason):
    return {"status": status, "reason": reason}


def hard_reject(tender_id, reason_code, reason_text, radius_km, actual_km):
    full_reason = f"{reason_code}: {actual_km}km exceeds {radius_km}km limit"
    block = crit("BLOCK", f"Excluded before reasoning — {full_reason}")
    return {
        "tender_id": tender_id,
        "verdict": "REJECT",
        "summary": reason_text,
        "hard_reject_reason": full_reason,
        "criteria": {
            "reference_eligibility": block,
            "financial_capacity": block,
            "regulatory_familiarity": block,
            "competitive_position": block,
            "strategic_fit": block,
        },
    }


ANALYSES_A = [
    {
        "tender_id": "T001",
        "verdict": "BID",
        "summary": "Core trade, local terrain, refs match exactly. Guarantee well within credit line.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "Road rehab references match exactly"),
            "financial_capacity": crit("PASS", "€90k guarantee well within €1.5M capacity; the 30% self-performed share is standard for a job this size with two active crews"),
            "regulatory_familiarity": crit("PASS", "Bavarian district tender, home territory"),
            "competitive_position": crit("WARNING", "3–4 regional competitors likely"),
            "strategic_fit": crit("PASS", "Core trade, preferred size, local client type"),
        },
    },
    {
        "tender_id": "T002",
        "verdict": "BID",
        "summary": "A sewer renewal on home turf, sized right, with references that match one-to-one. Nothing here needs a second look.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "District sewer renewal matches the company's proven references directly"),
            "financial_capacity": crit("PASS", "€65k guarantee is a small fraction of the €1.5M capacity; the 25% self-performed share is easily covered by existing crews"),
            "regulatory_familiarity": crit("PASS", "Familiar Bavarian district client and procurement process"),
            "competitive_position": crit("PASS", "Comfortable mid-size lot, well inside the company's typical winning range"),
            "strategic_fit": crit("PASS", "Exactly the trade and scale this company wants more of"),
        },
    },
    {
        "tender_id": "T003",
        "verdict": "BID",
        "summary": "On the doorstep, the right trade, and a reference that matches word for word. Worth the estimating hours.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "Housing-estate site development reference matches directly"),
            "financial_capacity": crit("WARNING", "€180k guarantee is manageable alone but would stack with other live bids, and the 40% self-performed share adds real crew-scheduling pressure on top of that"),
            "regulatory_familiarity": crit("PASS", "8km from home base, well-known municipal client"),
            "competitive_position": crit("PASS", "Local presence gives a real edge over out-of-region bidders"),
            "strategic_fit": crit("PASS", "Multi-year earthworks scope the company actively wants"),
        },
    },
    {
        "tender_id": "T004",
        "verdict": "REJECT",
        "summary": "Right region, right size, right role — but the tender demands a bridge reference the company has explicitly ruled out showing. A specialist bridge contractor wins this, not us.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("BLOCK", "Requires a completed bridge rehabilitation/new-build reference; the company's portfolio explicitly excludes bridge work"),
            "financial_capacity": crit("PASS", "€110k guarantee well within €1.5M capacity"),
            "regulatory_familiarity": crit("PASS", "Local Bavarian district client, familiar procurement process"),
            "competitive_position": crit("WARNING", "Specialist bridge contractors will likely out-compete a firm with no bridge portfolio"),
            "strategic_fit": crit("BLOCK", "Bridge work sits outside the trades the company can credibly bid; the 35% self-performed share would also demand crew skills (bridge formwork, specialist reinforcement) the company doesn't currently have"),
        },
    },
    hard_reject("T005", "TOO_FAR", "340km from Augsburg is more than double the company's 150km operating radius — excluded before any reasoning.", 150, 340),
    hard_reject("T006", "TOO_FAR", "330km from Augsburg exceeds the company's 150km operating radius — excluded before any reasoning.", 150, 330),
    hard_reject("T007", "TOO_FAR", "350km from Augsburg exceeds the company's 150km operating radius — excluded before any reasoning.", 150, 350),
    hard_reject("T008", "TOO_FAR", "400km from Augsburg exceeds the company's 150km operating radius — excluded before any reasoning.", 150, 400),
    hard_reject("T009", "TOO_FAR", "325km from Augsburg exceeds the company's 150km operating radius — excluded before any reasoning.", 150, 325),
    {
        "tender_id": "T010",
        "verdict": "MAYBE",
        "summary": "The trade and territory are perfect, but this one guarantee would tie up almost the entire credit line — worth bidding only if it isn't run alongside another large guarantee commitment.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "Municipal civil engineering references exceed the €2M threshold required"),
            "financial_capacity": crit("WARNING", "€1.42M guarantee would consume nearly all of the €1.5M guarantee capacity at once"),
            "regulatory_familiarity": crit("PASS", "Familiar Bavarian municipal client, 18km from home base"),
            "competitive_position": crit("PASS", "Size and location favor a local, established contractor"),
            "strategic_fit": crit("WARNING", "45% self-performed share plus a near-ceiling guarantee makes this the largest, tightest bet of the week"),
        },
    },
]

ANALYSES_B = [
    hard_reject("T001", "TOO_FAR", "335km from Plauen exceeds the company's 200km operating radius — excluded before any reasoning.", 200, 335),
    hard_reject("T002", "TOO_FAR", "345km from Plauen exceeds the company's 200km operating radius — excluded before any reasoning.", 200, 345),
    hard_reject("T003", "TOO_FAR", "330km from Plauen exceeds the company's 200km operating radius — excluded before any reasoning.", 200, 330),
    hard_reject("T004", "TOO_FAR", "370km from Plauen exceeds the company's 200km operating radius — excluded before any reasoning.", 200, 370),
    {
        "tender_id": "T005",
        "verdict": "BID",
        "summary": "A school electrical fit-out, sized and located exactly where this company wins. References match one-to-one.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "School refurbishment references match this scope directly"),
            "financial_capacity": crit("PASS", "€35k guarantee is a small fraction of the €300k capacity"),
            "regulatory_familiarity": crit("PASS", "Saxony school-building client, familiar procurement process"),
            "competitive_position": crit("PASS", "Comfortable sub-€500k lot size, low competitive pressure from larger firms"),
            "strategic_fit": crit("PASS", "Exactly the trade and role this company wants"),
        },
    },
    {
        "tender_id": "T006",
        "verdict": "BID",
        "summary": "In Plauen itself, hospital-ward electrical work the company has done before. The reference match alone should carry this bid.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "Hospital ward block reference matches this scope directly"),
            "financial_capacity": crit("PASS", "€45k guarantee is a small fraction of the €300k capacity"),
            "regulatory_familiarity": crit("PASS", "Home city, well-known healthcare-facility client"),
            "competitive_position": crit("WARNING", "A few larger regional electrical firms may also chase this one"),
            "strategic_fit": crit("PASS", "Healthcare fit-out is core to the company's reference base"),
        },
    },
    {
        "tender_id": "T007",
        "verdict": "BID",
        "summary": "A small, comfortable office fit-out squarely in the company's proven scope. Low risk, low competition, easy yes.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("PASS", "Office fit-out reference matches this scope directly"),
            "financial_capacity": crit("PASS", "€20k guarantee is negligible against the €300k capacity"),
            "regulatory_familiarity": crit("PASS", "Familiar Saxony commercial-client procurement process"),
            "competitive_position": crit("PASS", "Small lot size keeps larger competitors uninterested"),
            "strategic_fit": crit("PASS", "Comfortable size and trade, adds to a proven reference type"),
        },
    },
    {
        "tender_id": "T008",
        "verdict": "REJECT",
        "summary": "Right region, and the SPS control cabinet looks like our kind of work at first glance — but this is a Wassertechnik-Fachbetrieb job requiring DIN EN 1090 welding certification we don't hold. A water-technology specialist wins this one.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("BLOCK", "LV Vorbemerkungen requires a certified Wassertechnik-Fachbetrieb reference; no comparable fountain/water-technology installation in the company's portfolio"),
            "financial_capacity": crit("WARNING", "Guarantee amount is not disclosed in the published documents; cannot confirm it fits within the €300k capacity"),
            "regulatory_familiarity": crit("WARNING", "Municipal client type is familiar, but the Wassertechnik-Fachbetrieb qualification requirement is unfamiliar territory"),
            "competitive_position": crit("BLOCK", "Specialist Wassertechnik and DIN EN 1090-certified stainless-steel welding firms will dominate this bid; the company holds neither qualification"),
            "strategic_fit": crit("BLOCK", "Fountain water technology is adjacent to but distinct from the company's core building-electrical trade; winning it would mean subcontracting the core scope"),
        },
    },
    {
        "tender_id": "T009",
        "verdict": "REJECT",
        "summary": "Close to home and a comfortable contract size, but high-voltage switchgear is explicitly outside what this company is certified and willing to bid — a hard no despite the fit everywhere else.",
        "hard_reject_reason": None,
        "criteria": {
            "reference_eligibility": crit("WARNING", "General electrical installation references exist, but none involve high-voltage switchgear specifically"),
            "financial_capacity": crit("PASS", "€60k guarantee well within €300k capacity"),
            "regulatory_familiarity": crit("PASS", "Saxony municipal/utility client, familiar territory"),
            "competitive_position": crit("BLOCK", "High-voltage switchgear work is explicitly outside the company's certified scope — cannot compete credibly"),
            "strategic_fit": crit("BLOCK", "Company profile explicitly excludes high-voltage and explosion-protected installations"),
        },
    },
    hard_reject("T010", "TOO_FAR", "335km from Plauen exceeds the company's 200km operating radius — excluded before any reasoning.", 200, 335),
]

ANALYSES = {"profile-a": ANALYSES_A, "profile-b": ANALYSES_B}

# ---------------------------------------------------------------------------
# Write + validate
# ---------------------------------------------------------------------------


def main():
    BACKEND_DATA.mkdir(parents=True, exist_ok=True)

    files = {
        "profiles.json": PROFILES,
        "tenders.json": TENDERS,
        "analyses.json": ANALYSES,
    }
    for name, data in files.items():
        path = BACKEND_DATA / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    # Validate against the frozen Pydantic models.
    from app.models import CompanyProfile, Tender, TenderAnalysis  # noqa: E402

    for p in PROFILES:
        CompanyProfile.model_validate(p)
    tender_ids = set()
    for t in TENDERS:
        Tender.model_validate(t)
        tender_ids.add(t["id"])
    assert len(tender_ids) == len(TENDERS), "duplicate tender ids"

    for profile_id, analyses in ANALYSES.items():
        assert profile_id in {p["id"] for p in PROFILES}, f"unknown profile id {profile_id}"
        seen = set()
        for a in analyses:
            TenderAnalysis.model_validate(a)
            assert a["tender_id"] in tender_ids, f"unknown tender id {a['tender_id']}"
            seen.add(a["tender_id"])
        missing = tender_ids - seen
        assert not missing, f"{profile_id} missing analyses for {missing}"

    print("OK: all fixtures validate against backend/app/models.py")
    print(f"tenders: {len(TENDERS)}")
    for profile_id, analyses in ANALYSES.items():
        counts = {}
        for a in analyses:
            counts[a["verdict"]] = counts.get(a["verdict"], 0) + 1
        print(f"{profile_id}: {counts}")


if __name__ == "__main__":
    main()
