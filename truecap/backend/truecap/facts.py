"""Canonical fact keys and the shape of their values.

The extraction step (LLM or deterministic parser) must emit facts using only these
keys. Values are plain JSON so they can be stored in the database as-is.
"""

from __future__ import annotations


class FactKey:
    # --- Company registry (MCA / data.gov.in) --------------------------------
    COMPANY_NAME = "company.name"  # str
    CIN = "company.cin"  # str, 21 chars
    STATUS = "company.status"  # str, e.g. "Active", "Strike Off", "Dormant"
    INCORPORATION_DATE = "company.incorporation_date"  # ISO date str
    COMPANY_TYPE = "company.type"  # str, e.g. "Private Limited"
    REGISTERED_OFFICE = "company.registered_office"  # str
    PAID_UP_CAPITAL = "company.paid_up_capital_inr"  # int (rupees)
    LAST_FILING_DATE = "company.last_filing_date"  # ISO date of latest balance sheet/AR on record
    CLAIMED_FOUNDING_YEAR = "company.claimed_founding_year"  # int, as claimed by the company
    WEBSITE = "company.website"  # str URL
    SOCIAL_PROFILE = "company.social_profile"  # {"platform": str, "url": str}
    EMPLOYEE_COUNT = "company.employee_count"  # {"count": int, "as_of": ISO date}
    GSTIN = "company.gstin"  # str
    GST_STATUS = "company.gst_status"  # str, e.g. "Active", "Cancelled"

    # --- People -----------------------------------------------------------------
    DIRECTOR = "director.record"
    # {"name": str, "din": str|None, "appointed_on": ISO|None, "ceased_on": ISO|None,
    #  "disqualified": bool|None, "other_active_directorships": int|None}
    FOUNDER = "founder.identified"  # {"name": str, "role": str|None}
    FOUNDER_CLAIM = "founder.claim_check"
    # {"name": str, "claim": str, "status": "corroborated"|"contradicted"|"unverified",
    #  "finding": str|None}  finding = what the independent source says
    FOUNDER_EXPERIENCE = "founder.experience"
    # {"name": str, "prior_startups": int, "domain_years": int|None}

    # --- Market -----------------------------------------------------------------
    MARKET_SIZE_CLAIM = "market.size_claim"  # {"text": str, "third_party_source": bool}
    COMPETITOR = "market.competitor"  # {"name": str, "funding_usd": float|None}
    INDEPENDENT_COVERAGE = "market.independent_coverage"  # {"outlet": str, "date": ISO}
    LICENSE_REQUIRED = "regulatory.license_required"  # {"regulator": str, "license": str} or None if not required
    LICENSE_HELD = "regulatory.license_held"  # {"regulator": str, "license": str}

    # --- Traction ---------------------------------------------------------------
    REVENUE_CLAIM = "traction.revenue_claim"  # {"fy": "FY24", "amount_inr": int}
    TOP_CUSTOMER_SHARE = "traction.top_customer_share"  # float 0..1 of revenue
    VAGUE_CLAIM = "traction.vague_claim"  # {"text": str}
    WEBSITE_STATUS = "traction.website_status"  # {"live": bool, "last_updated": ISO|None}

    # --- Financials -------------------------------------------------------------
    REVENUE_FILED = "financials.revenue_filed"  # {"fy": "FY24", "amount_inr": int}
    FUNDING_ROUND = "funding.round"
    # {"round": str, "date": ISO|None, "amount_usd": float|None, "investors": [str],
    #  "independently_reported": bool}

    # --- Legal ------------------------------------------------------------------
    LITIGATION_CASE = "litigation.case"
    # {"title": str, "forum": str, "case_type": str, "status": "pending"|"disposed",
    #  "company_role": "petitioner"|"respondent"|"accused"|"other"}
    LITIGATION_SEARCH_DONE = "litigation.search_completed"  # {"scope": str}; official search ran
    TRADEMARK = "trademark.record"
    # {"mark": str, "status": "registered"|"pending"|"objected"|"opposed"|"refused"|"abandoned",
    #  "owner_matches_company": bool}


def fy_label(fy: str) -> str:
    """Normalise financial-year labels: 'fy24', 'FY 2024', '2023-24' -> 'FY24'."""
    s = fy.upper().replace(" ", "").replace("FY", "")
    if "-" in s:
        s = s.split("-")[-1]
    return f"FY{s[-2:]}"
