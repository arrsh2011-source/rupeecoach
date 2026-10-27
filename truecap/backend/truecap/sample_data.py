"""Fictional sample companies used by tests and the demo. Any resemblance to real
companies is accidental; URLs use the reserved .example domain."""

from __future__ import annotations

from datetime import date, datetime, timezone

from truecap.checks import CheckContext
from truecap.domain import FactSet, Ledger, SourceType
from truecap.facts import FactKey as K

SAMPLE_TODAY = date(2026, 10, 27)
FETCHED = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
SAMPLE_INVESTORS = frozenset({"Banyan Seed Fund", "Monsoon Ventures"})


def sample_ctx() -> CheckContext:
    return CheckContext(today=SAMPLE_TODAY, reputable_investors=SAMPLE_INVESTORS)


def kisankart() -> tuple[str, FactSet]:
    """A seed-stage agritech with a mix of strengths, open questions and one red flag."""
    L = Ledger()
    mca = L.add("MCA master data for KISANKART AGRITECH PRIVATE LIMITED", SourceType.MCA,
                url="https://data.gov.in/resource/company-master-data.example", fetched_at=FETCHED,
                excerpt="Status: Active; Date of incorporation: 2021-06-14; Paid up capital: 1250000")
    filing = L.add("Latest financial statements on record dated 2025-03-31", SourceType.MCA,
                   url="https://data.gov.in/resource/company-master-data.example", fetched_at=FETCHED)
    fin = L.add("Filed revenue FY24 ₹1.80 crore (18000000), FY25 ₹2.10 crore (21000000)", SourceType.AGGREGATOR,
                url="https://companyinfo.example/kisankart/financials", fetched_at=FETCHED)
    web = L.add("Company website", SourceType.COMPANY_WEBSITE, url="https://kisankart.example", fetched_at=FETCHED,
                excerpt="Serving farmers since 2018. FY25 revenue of ₹4.5 crore. Rapid growth across India.")
    deck = L.add("About page: market size", SourceType.COMPANY_WEBSITE, url="https://kisankart.example/about",
                 fetched_at=FETCHED, excerpt="A $24 billion agri-inputs market")
    news1 = L.add("Kisankart raises seed round led by Banyan Seed Fund", SourceType.NEWS,
                  url="https://startupnews.example/kisankart-seed", published_on=date(2025, 11, 3), fetched_at=FETCHED,
                  excerpt="Kisankart has raised $1.5 million (1.5) in a seed round led by Banyan Seed Fund.")
    news2 = L.add("Agritech startups to watch", SourceType.NEWS, url="https://businessdaily.example/agritech-2026",
                  published_on=date(2026, 4, 10), fetched_at=FETCHED)
    prof_a = L.add("Public profile of Asha Rao", SourceType.FOUNDER_PROFILE, url="https://profiles.example/asha-rao",
                   fetched_at=FETCHED, excerpt="Co-founded FarmLoop (acquired 2019). IIT Kharagpur, B.Tech 2012.")
    prof_b = L.add("University alumni list", SourceType.NEWS, url="https://alumni.example/iitkgp-2012",
                   fetched_at=FETCHED, excerpt="Asha Rao, B.Tech Agricultural Engineering, 2012")
    gst = L.add("GSTIN shown in website footer", SourceType.COMPANY_WEBSITE, url="https://kisankart.example",
                fetched_at=FETCHED, excerpt="GSTIN 29AAGCB7383J1Z4")
    tm = L.add("Trademark search results for KISANKART", SourceType.WEB_SEARCH,
               url="https://search.example/?q=kisankart+trademark", fetched_at=FETCHED,
               excerpt="KISANKART, Class 35, applicant: another company, status: Opposed")
    comp = L.add("Funding of direct competitors", SourceType.AGGREGATOR, url="https://companyinfo.example/agri-inputs",
                 fetched_at=FETCHED)
    head = L.add("Employee estimates from public profiles", SourceType.AGGREGATOR,
                 url="https://companyinfo.example/kisankart/people", fetched_at=FETCHED,
                 excerpt="2025-01: 32 employees; 2026-09: 41 employees")
    site = L.add("Website check", SourceType.COMPUTED, url="https://kisankart.example", fetched_at=FETCHED)

    F = FactSet(L)
    F.put(K.COMPANY_NAME, "KISANKART AGRITECH PRIVATE LIMITED", mca.id)
    F.put(K.CIN, "U01100KA2021PTC149876", mca.id)
    F.put(K.STATUS, "Active", mca.id)
    F.put(K.INCORPORATION_DATE, "2021-06-14", mca.id)
    F.put(K.COMPANY_TYPE, "Private Limited (company limited by shares)", mca.id)
    F.put(K.REGISTERED_OFFICE, "HSR Layout, Bengaluru, Karnataka 560102", mca.id)
    F.put(K.PAID_UP_CAPITAL, 1_250_000, mca.id)
    F.put(K.LAST_FILING_DATE, "2025-03-31", filing.id)
    F.put(K.CLAIMED_FOUNDING_YEAR, 2018, web.id)
    F.put(K.WEBSITE, "https://kisankart.example", web.id)
    F.put(K.SOCIAL_PROFILE, {"platform": "LinkedIn", "url": "https://social.example/kisankart"}, prof_a.id)
    F.put(K.GSTIN, "29AAGCB7383J1Z4", gst.id)

    F.put(K.DIRECTOR, {"name": "Asha Rao", "din": "09123456", "appointed_on": "2021-06-14", "ceased_on": None,
                       "disqualified": False, "other_active_directorships": 1}, mca.id)
    F.put(K.DIRECTOR, {"name": "Vikram Shetty", "din": "09123457", "appointed_on": "2021-06-14", "ceased_on": None,
                       "disqualified": False, "other_active_directorships": 0}, mca.id)
    F.put(K.FOUNDER, {"name": "Asha Rao", "role": "CEO"}, web.id, prof_a.id)
    F.put(K.FOUNDER_CLAIM, {"name": "Asha Rao", "claim": "IIT Kharagpur graduate", "status": "corroborated"},
          prof_a.id, prof_b.id)
    F.put(K.FOUNDER_EXPERIENCE, {"name": "Asha Rao", "prior_startups": 1, "domain_years": 9}, prof_a.id)

    F.put(K.MARKET_SIZE_CLAIM, {"text": "A $24 billion agri-inputs market", "third_party_source": False}, deck.id)
    F.put(K.INDEPENDENT_COVERAGE, {"outlet": "Business Daily", "date": "2026-04-10"}, news2.id)
    F.put(K.INDEPENDENT_COVERAGE, {"outlet": "Startup News", "date": "2025-11-03"}, news1.id)
    for name, funding in [("AgroDirect", 60e6), ("FarmMart", 25e6), ("KhetBazaar", 4e6)]:
        F.put(K.COMPETITOR, {"name": name, "funding_usd": funding}, comp.id)
    F.put(K.LICENSE_REQUIRED, None, deck.id)

    F.put(K.REVENUE_CLAIM, {"fy": "FY25", "amount_inr": 45_000_000}, web.id)
    F.put(K.REVENUE_FILED, {"fy": "FY24", "amount_inr": 18_000_000}, fin.id)
    F.put(K.REVENUE_FILED, {"fy": "FY25", "amount_inr": 21_000_000}, fin.id)
    F.put(K.VAGUE_CLAIM, {"text": "Rapid growth across India"}, web.id)
    F.put(K.EMPLOYEE_COUNT, {"count": 32, "as_of": "2025-01-01"}, head.id)
    F.put(K.EMPLOYEE_COUNT, {"count": 41, "as_of": "2026-09-01"}, head.id)
    F.put(K.WEBSITE_STATUS, {"live": True, "last_updated": "2026-09-15"}, site.id)

    F.put(K.FUNDING_ROUND, {"round": "Seed", "date": "2025-11-03", "amount_usd": 1_500_000,
                            "investors": ["Banyan Seed Fund"], "independently_reported": True}, news1.id)
    F.put(K.TRADEMARK, {"mark": "KISANKART", "status": "opposed", "owner_matches_company": False}, tm.id)
    return "Kisankart Agritech", F


def struck_off() -> tuple[str, FactSet]:
    """A company the registry lists as struck off, with an overdue filing and a disqualified director."""
    L = Ledger()
    mca = L.add("MCA master data for DORMANTCO TECH PRIVATE LIMITED", SourceType.MCA,
                url="https://data.gov.in/resource/company-master-data.example", fetched_at=FETCHED)
    F = FactSet(L)
    F.put(K.STATUS, "Strike Off", mca.id)
    F.put(K.INCORPORATION_DATE, "2017-02-01", mca.id)
    F.put(K.LAST_FILING_DATE, "2019-03-31", mca.id)
    F.put(K.DIRECTOR, {"name": "R. Mehta", "din": "07000001", "disqualified": True,
                       "other_active_directorships": 7}, mca.id)
    return "Dormantco Tech", F


def sparse() -> tuple[str, FactSet]:
    """Almost nothing found: should score from what exists but with Low confidence."""
    L = Ledger()
    mca = L.add("MCA master data for TINY LABS PRIVATE LIMITED", SourceType.MCA,
                url="https://data.gov.in/resource/company-master-data.example", fetched_at=FETCHED)
    F = FactSet(L)
    F.put(K.STATUS, "Active", mca.id)
    F.put(K.INCORPORATION_DATE, "2025-08-01", mca.id)
    return "Tiny Labs", F
