from datetime import date, timedelta
import requests, zipfile, io, csv
from math import radians, cos, sin, asin, sqrt

# ── CONFIG ────────────────────────────────────────────────────
BASE_URL = "https://oeffentlichevergabe.de/api/notice-exports"

# Server-side filters (sent as params)
CPV_PREFIXES    = ["45"]              # Construction works only
NUTS_PREFIXES   = ["DE21", "DE27",    # Oberbayern, Schwaben (Profile A)
                   "DED",  "DEG",     # Saxony, Thuringia  (Profile B)
                   "DE22", "DE23",    # Niederbayern, Oberpfalz (buffer)
                   "DE14", "DE11"]    # Tübingen, Stuttgart (southern buffer)
FETCH_DAYS_BACK = 21                  # last 3 weeks — enough to get 40+ good tenders
MAX_FETCH       = 500                 # safety cap

# Local filter: only these notice types = "competition / bidding phase"
COMPETITION_NOTICE_TYPES = {
    "cn-standard",   # standard open/restricted/negotiated competition
    "cn-social",     # social services competition
    "cn-desg",       # concession competition
}

# ── STEP 1: FETCH FROM PORTAL ─────────────────────────────────
def fetch_day(pub_day: str) -> list[dict]:
    """Download one day's CSV ZIP and return raw notice rows."""
    r = requests.get(BASE_URL, params={"pubDay": pub_day, "format": "csv.zip"}, timeout=120)
    if r.status_code != 200:
        return []
    z = zipfile.ZipFile(io.BytesIO(r.content))
    tables = {}
    for name in z.namelist():
        if name.endswith(".csv"):
            key = name.split("/")[-1].replace(".csv", "")
            reader = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8"))
            tables[key] = list(reader)
    return tables

raw_notices = []
for i in range(1, FETCH_DAYS_BACK + 1):
    pub_day = (date.today() - timedelta(days=i)).isoformat()
    tables = fetch_day(pub_day)
    if tables:
        raw_notices.extend(tables.get("notice", []))

# ── STEP 2: COMPETITION FILTER (notice type) ──────────────────
competition_notices = [
    n for n in raw_notices
    if n.get("noticeType") in COMPETITION_NOTICE_TYPES
]

# ── STEP 3: CPV FILTER (local, because lots may override) ─────
# Server gave us CPV=45 already, but double-check including lot-level CPVs
def matches_cpv(notice, cpv_prefixes):
    cpvs = [notice.get("cpvMain", "")]
    # additional CPVs are comma-separated in some exports
    cpvs += (notice.get("cpvAdditional") or "").split(",")
    return any(
        c.strip().startswith(prefix)
        for c in cpvs for prefix in cpv_prefixes
        if c.strip()
    )

cpv_filtered = [n for n in competition_notices if matches_cpv(n, CPV_PREFIXES)]

# ── STEP 4: NUTS / REGION FILTER ──────────────────────────────
def matches_nuts(notice, nuts_prefixes):
    nuts = notice.get("nutsCode") or notice.get("organisationCountrySubdivision") or ""
    return any(nuts.startswith(prefix) for prefix in nuts_prefixes)

region_filtered = [n for n in cpv_filtered if matches_nuts(n, NUTS_PREFIXES)]

# ── STEP 5: DEADLINE FILTER — still open ──────────────────────
today = date.today()

def still_open(notice):
    dl = notice.get("deadlineDate") or notice.get("publicOpeningDate")
    if not dl:
        return True   # unknown deadline → keep, LLM will handle
    try:
        return date.fromisoformat(dl[:10]) >= today
    except ValueError:
        return True

open_notices = [n for n in region_filtered if still_open(n)]

# ── RESULT ────────────────────────────────────────────────────
print(f"Fetched:       {len(raw_notices)}")
print(f"Competition:   {len(competition_notices)}")
print(f"CPV 45:        {len(cpv_filtered)}")
print(f"Region match:  {len(region_filtered)}")
print(f"Still open:    {len(open_notices)}")
# Target: ~40–80 notices to pass to LV enrichment