"""LLM fact extraction with verbatim-quote verification.

The model returns structured facts, each with the evidence ids it relies on and a quote.
A fact is accepted only if its quote appears word-for-word in the source text of one of
the cited entries. Reliability rules are then applied in code, not by the model.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from truecap.domain import FactSet, Reliability
from truecap.facts import FactKey as K


class Cited(BaseModel):
    evidence_ids: list[str] = Field(description="Ids like E3 of the sources that state this fact")
    quote: str = Field(description="Exact text copied from one of those sources, at most 300 characters")


class XFounder(Cited):
    name: str
    role: str | None


class XFounderClaim(Cited):
    name: str
    claim: str = Field(description="What the company or founder claims, e.g. 'IIT Bombay graduate'")
    status: Literal["corroborated", "contradicted", "unverified"]
    finding: str | None = Field(description="What the independent source says, if corroborated or contradicted")


class XExperience(Cited):
    name: str
    prior_startups: int
    domain_years: int | None


class XDirector(Cited):
    name: str
    din: str | None
    appointed_on: str | None = Field(description="YYYY-MM-DD")
    ceased_on: str | None = Field(description="YYYY-MM-DD, null if still a director")
    other_active_directorships: int | None


class XFunding(Cited):
    round: str
    date: str | None = Field(description="YYYY-MM-DD or YYYY-MM")
    amount_usd: float | None
    investors: list[str]


class XRevenue(Cited):
    fy: str = Field(description="Financial year label like FY24 (year ending March 2024)")
    amount_inr: int = Field(description="Rupees. 1 crore = 10000000, 1 lakh = 100000")


class XMarketClaim(Cited):
    text: str
    third_party_source: bool = Field(description="True only if the claim names a research firm or report")


class XCompetitor(Cited):
    name: str
    funding_usd: float | None


class XCoverage(Cited):
    outlet: str
    date: str = Field(description="YYYY-MM-DD")


class XLicence(Cited):
    regulator: str
    license: str


class XLicenceNeed(Cited):
    required: bool
    regulator: str | None
    license: str | None


class XShare(Cited):
    share: float = Field(description="Fraction of revenue from the largest customer, 0 to 1")


class XText(Cited):
    text: str


class XHeadcount(Cited):
    count: int
    as_of: str = Field(description="YYYY-MM-DD")


class XCase(Cited):
    title: str
    forum: str
    case_type: str
    status: Literal["pending", "disposed"]
    company_role: Literal["petitioner", "respondent", "accused", "other"]


class XTrademark(Cited):
    mark: str
    status: Literal["registered", "pending", "objected", "opposed", "refused", "abandoned"]
    owner_matches_company: bool


class XYear(Cited):
    year: int


class XSocial(Cited):
    platform: str
    url: str


class Extraction(BaseModel):
    founders: list[XFounder]
    founder_claims: list[XFounderClaim]
    founder_experience: list[XExperience]
    directors: list[XDirector]
    funding_rounds: list[XFunding]
    revenue_claims: list[XRevenue] = Field(description="Revenue figures the company itself states")
    revenue_filed: list[XRevenue] = Field(description="Revenue figures attributed to MCA/RoC filings")
    market_size_claims: list[XMarketClaim]
    competitors: list[XCompetitor]
    coverage: list[XCoverage] = Field(description="Independent media articles about the company")
    licence_need: XLicenceNeed | None
    licences_held: list[XLicence]
    top_customer_share: XShare | None
    vague_claims: list[XText] = Field(description="Traction claims with no figures or dates, e.g. 'rapid growth'")
    headcount: list[XHeadcount]
    court_cases: list[XCase]
    trademarks: list[XTrademark]
    claimed_founding_year: XYear | None
    social_profiles: list[XSocial]


SYSTEM = """You extract facts about one company from the numbered sources given. Rules:
- Only facts a source states explicitly. Never infer, estimate or fill gaps; leave lists empty instead.
- Every item cites the evidence ids it comes from, and `quote` is text copied exactly from one of those sources.
- Use the source's own words in text fields. Neutral wording only.
- revenue_claims: figures the company states (its website, press releases, founder interviews).
  revenue_filed: figures a source attributes to MCA/RoC filings or financial statements.
- founder_claims: claims about founders' education or past roles. corroborated = an independent source states the same;
  contradicted = an independent source states something incompatible; otherwise unverified.
- court_cases: company_role is the company's side in the case.
- Dates as YYYY-MM-DD where the source gives a day, else YYYY-MM."""


def build_prompt(company: str, ledger_rows: list[tuple[str, str, str, str | None, str]]) -> str:
    parts = [f"Company: {company}\n\nSources:"]
    for eid, stype, rel, url, text in ledger_rows:
        parts.append(f"\n[{eid}] type={stype} reliability={rel} url={url or '-'}\n{text}")
    return "\n".join(parts)


# --- quote verification -------------------------------------------------------

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ", "₹": "rs "})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_TRANS).lower()
    s = s.replace("rs.", "rs ")
    return " ".join(s.split())


def quote_supported(quote: str, sources: list[str]) -> bool:
    q = _norm(quote)
    if len(q) < 3:
        return False
    parts = [p.strip() for p in re.split(r"\.\.\.|…", q) if p.strip()]
    hay = [_norm(s) for s in sources]
    return any(all(p in h for p in parts) for h in hay)


def apply_extraction(ext: Extraction, facts: FactSet, source_text: dict[str, str]) -> list[str]:
    """Add verified facts to `facts`. Returns a log of what was dropped and why."""
    log: list[str] = []
    ledger = facts.ledger

    def ok(item: Cited, label: str) -> list[str] | None:
        ids = [e for e in dict.fromkeys(item.evidence_ids) if e in ledger and e in source_text]
        if not ids:
            log.append(f"dropped {label}: cites no known source")
            return None
        if not quote_supported(item.quote, [source_text[e] for e in ids]):
            log.append(f"dropped {label}: quote not found in cited source: {item.quote[:80]!r}")
            return None
        for e in ids:  # surface the quote in the ledger so readers see the exact supporting text
            ev = ledger.get(e)
            if item.quote not in (ev.excerpt or ""):
                ev.excerpt = ((ev.excerpt + " … ") if ev.excerpt else "") + item.quote
        return ids

    def independent(ids: list[str]) -> bool:
        return any(ledger.get(e).reliability != Reliability.SELF_REPORTED for e in ids)

    def put(key, value, item, label, subject=None):
        if (ids := ok(item, label)) is not None:
            facts.put(key, value, *ids, subject=subject, quote=item.quote)
            return ids
        return None

    for x in ext.founders:
        put(K.FOUNDER, {"name": x.name, "role": x.role}, x, f"founder {x.name}", x.name)
    for x in ext.founder_claims:
        if (ids := ok(x, f"founder claim {x.claim}")) is None:
            continue
        status = x.status if independent(ids) else "unverified"  # self-reported sources can't verify themselves
        facts.put(K.FOUNDER_CLAIM, {"name": x.name, "claim": x.claim, "status": status, "finding": x.finding},
                  *ids, subject=x.name, quote=x.quote)
    for x in ext.founder_experience:
        put(K.FOUNDER_EXPERIENCE, {"name": x.name, "prior_startups": x.prior_startups,
                                   "domain_years": x.domain_years}, x, f"experience {x.name}", x.name)
    for x in ext.directors:
        put(K.DIRECTOR, {"name": x.name, "din": x.din, "appointed_on": x.appointed_on, "ceased_on": x.ceased_on,
                         "disqualified": None, "other_active_directorships": x.other_active_directorships},
            x, f"director {x.name}", x.name)
    for x in ext.funding_rounds:
        if (ids := ok(x, f"funding {x.round}")) is None:
            continue
        facts.put(K.FUNDING_ROUND, {"round": x.round, "date": x.date, "amount_usd": x.amount_usd,
                                    "investors": x.investors, "independently_reported": independent(ids)},
                  *ids, quote=x.quote)
    for x in ext.revenue_claims:
        put(K.REVENUE_CLAIM, {"fy": x.fy, "amount_inr": x.amount_inr}, x, f"revenue claim {x.fy}")
    for x in ext.revenue_filed:
        if (ids := ok(x, f"filed revenue {x.fy}")) is None:
            continue
        # A "filed" figure that only the company reports is treated as a company claim.
        key = K.REVENUE_FILED if independent(ids) else K.REVENUE_CLAIM
        facts.put(key, {"fy": x.fy, "amount_inr": x.amount_inr}, *ids, quote=x.quote)
    for x in ext.market_size_claims:
        put(K.MARKET_SIZE_CLAIM, {"text": x.text, "third_party_source": x.third_party_source}, x, "market size")
    for x in ext.competitors:
        put(K.COMPETITOR, {"name": x.name, "funding_usd": x.funding_usd}, x, f"competitor {x.name}")
    for x in ext.coverage:
        if (ids := ok(x, f"coverage {x.outlet}")) is not None and independent(ids):
            facts.put(K.INDEPENDENT_COVERAGE, {"outlet": x.outlet, "date": x.date}, *ids, quote=x.quote)
    if ext.licence_need is not None:
        x = ext.licence_need
        value = {"regulator": x.regulator, "license": x.license} if x.required and x.regulator and x.license else None
        put(K.LICENSE_REQUIRED, value, x, "licence need")
    for x in ext.licences_held:
        if (ids := ok(x, f"licence {x.license}")) is not None and independent(ids):
            facts.put(K.LICENSE_HELD, {"regulator": x.regulator, "license": x.license}, *ids, quote=x.quote)
    if ext.top_customer_share is not None and 0 <= ext.top_customer_share.share <= 1:
        put(K.TOP_CUSTOMER_SHARE, ext.top_customer_share.share, ext.top_customer_share, "customer share")
    for x in ext.vague_claims:
        put(K.VAGUE_CLAIM, {"text": x.text}, x, "vague claim")
    for x in ext.headcount:
        put(K.EMPLOYEE_COUNT, {"count": x.count, "as_of": x.as_of}, x, "headcount")
    for x in ext.court_cases:
        put(K.LITIGATION_CASE, {"title": x.title, "forum": x.forum, "case_type": x.case_type, "status": x.status,
                                "company_role": x.company_role}, x, f"case {x.title}")
    for x in ext.trademarks:
        put(K.TRADEMARK, {"mark": x.mark, "status": x.status, "owner_matches_company": x.owner_matches_company},
            x, f"trademark {x.mark}")
    if ext.claimed_founding_year is not None:
        put(K.CLAIMED_FOUNDING_YEAR, ext.claimed_founding_year.year, ext.claimed_founding_year, "founding year")
    for x in ext.social_profiles:
        put(K.SOCIAL_PROFILE, {"platform": x.platform, "url": x.url}, x, f"social {x.platform}")
    return log
