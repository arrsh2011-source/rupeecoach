"""Official portals that require a CAPTCHA or login. TrueCap never automates them;
when the related check is UNKNOWN the report links the user to verify it themselves."""

from __future__ import annotations

from truecap.domain import CheckResult, Outcome
from truecap.report.models import ManualCheck

MANUAL_PORTALS: dict[str, tuple[str, str, str]] = {
    # check_id: (title, why, url)
    "legal.company_active": (
        "Company status on MCA",
        "Confirm the company is Active using its CIN on the MCA master data page.",
        "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
    ),
    "legal.director_disqualification": (
        "Director details on MCA",
        "Check each director's DIN status on the MCA master data page.",
        "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
    ),
    "legal.gst_registration": (
        "GST registration status",
        "Search the GSTIN on the GST portal to confirm it is Active and belongs to this company.",
        "https://services.gst.gov.in/services/searchtp",
    ),
    "legal.trademark": (
        "Trademark on IP India",
        "Search the brand name on the IP India trademark register and check the owner.",
        "https://tmrsearch.ipindia.gov.in/eregister/",
    ),
    "legal.litigation": (
        "Court cases on eCourts",
        "Search by party name (the company and its directors) on eCourts. Also check NCLT for insolvency matters.",
        "https://services.ecourts.gov.in/ecourtindia_v6/",
    ),
    "financials.filings_current": (
        "Annual filings on MCA",
        "Check the date of the latest AOC-4 / MGT-7 filing on the MCA portal.",
        "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
    ),
}


def manual_checks_for(results: list[CheckResult]) -> list[ManualCheck]:
    return [
        ManualCheck(title=t, why=w, url=u, check_id=r.check_id)
        for r in results
        if r.outcome == Outcome.UNKNOWN and r.check_id in MANUAL_PORTALS
        for t, w, u in [MANUAL_PORTALS[r.check_id]]
    ]
