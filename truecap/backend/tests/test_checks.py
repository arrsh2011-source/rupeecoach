from collections import Counter

import pytest

from truecap.checks import REGISTRY, run_all
from truecap.domain import Category, FactSet, Ledger, Outcome, Severity
from truecap.domain import SourceType as S
from truecap.facts import FactKey as K
from truecap.guards import is_neutral
from truecap import sample_data


def run(check_id, b, ctx):
    return REGISTRY[check_id].run(b.facts, ctx)


# --- framework invariants -----------------------------------------------------


def test_each_category_has_four_to_six_checks():
    counts = Counter(spec.category for spec in REGISTRY.values())
    assert set(counts) == set(Category)
    assert all(4 <= n <= 6 for n in counts.values()), counts


def test_every_check_is_unknown_with_no_facts(ctx):
    results = run_all(FactSet(Ledger()), ctx)
    assert len(results) == len(REGISTRY)
    assert all(r.outcome == Outcome.UNKNOWN and not r.evidence_ids for r in results)


@pytest.mark.parametrize("make", [sample_data.kisankart, sample_data.struck_off, sample_data.sparse])
def test_decided_checks_cite_evidence_and_are_neutral(make, ctx):
    _, facts = make()
    for r in run_all(facts, ctx):
        if r.outcome != Outcome.UNKNOWN:
            assert r.evidence_ids and all(e in facts.ledger for e in r.evidence_ids)
        assert is_neutral(r.detail), r.detail
        if r.flag:
            assert is_neutral(r.flag.title) and is_neutral(r.flag.question or "")
            if r.flag.severity != Severity.GREEN:
                assert r.flag.question, f"{r.check_id} raises a {r.flag.severity} flag without a question"


# --- team ---------------------------------------------------------------------


def test_background_claim_contradicted_is_red(b, ctx):
    b.put(K.FOUNDER_CLAIM, {"name": "A", "claim": "ex-Google", "status": "contradicted",
                            "finding": "the public profile lists no Google role"}, S.FOUNDER_PROFILE)
    r = run("team.background_claims", b, ctx)
    assert r.outcome == Outcome.FAIL and r.flag.severity == Severity.RED
    assert "\"ex-Google\"" in r.detail


def test_background_claims_unverified_only_is_unknown(b, ctx):
    b.put(K.FOUNDER_CLAIM, {"name": "A", "claim": "ex-Google", "status": "unverified"}, S.COMPANY_WEBSITE)
    assert run("team.background_claims", b, ctx).outcome == Outcome.UNKNOWN


def test_relevant_experience(b, ctx):
    b.put(K.FOUNDER_EXPERIENCE, {"name": "A", "prior_startups": 0, "domain_years": 1}, S.FOUNDER_PROFILE)
    assert run("team.relevant_experience", b, ctx).outcome == Outcome.FAIL
    b.put(K.FOUNDER_EXPERIENCE, {"name": "B", "prior_startups": 0, "domain_years": 5}, S.FOUNDER_PROFILE)
    r = run("team.relevant_experience", b, ctx)
    assert r.outcome == Outcome.PASS and r.flag is None
    b.put(K.FOUNDER_EXPERIENCE, {"name": "C", "prior_startups": 2}, S.FOUNDER_PROFILE)
    assert run("team.relevant_experience", b, ctx).flag.severity == Severity.GREEN


def test_founder_turnover_window(b, ctx):
    b.put(K.DIRECTOR, {"name": "A", "ceased_on": "2025-12-01"})
    b.put(K.DIRECTOR, {"name": "B", "ceased_on": "2020-01-01"})  # outside 24 months
    b.put(K.DIRECTOR, {"name": "C", "ceased_on": None})
    assert run("team.founder_turnover", b, ctx).outcome == Outcome.PASS
    b.put(K.DIRECTOR, {"name": "D", "ceased_on": "2026-03-01"})
    r = run("team.founder_turnover", b, ctx)
    assert r.outcome == Outcome.FAIL and r.flag.severity == Severity.YELLOW


def test_director_commitment(b, ctx):
    b.put(K.DIRECTOR, {"name": "A", "other_active_directorships": 2})
    assert run("team.director_commitment", b, ctx).outcome == Outcome.PASS
    b.put(K.DIRECTOR, {"name": "B", "other_active_directorships": 6})
    assert run("team.director_commitment", b, ctx).outcome == Outcome.FAIL


# --- market -------------------------------------------------------------------


def test_market_size_claim(b, ctx):
    b.put(K.MARKET_SIZE_CLAIM, {"text": "$5B market", "third_party_source": True}, S.COMPANY_WEBSITE)
    assert run("market.size_claim_sourced", b, ctx).outcome == Outcome.PASS
    b.put(K.MARKET_SIZE_CLAIM, {"text": "$50B TAM", "third_party_source": False}, S.COMPANY_WEBSITE)
    assert run("market.size_claim_sourced", b, ctx).outcome == Outcome.FAIL


def test_independent_coverage_recency(b, ctx):
    b.put(K.INDEPENDENT_COVERAGE, {"outlet": "Old Times", "date": "2022-01-01"}, S.NEWS)
    assert run("market.independent_coverage", b, ctx).outcome == Outcome.FAIL
    b.put(K.INDEPENDENT_COVERAGE, {"outlet": "New Times", "date": "2026-06-01"}, S.NEWS)
    assert run("market.independent_coverage", b, ctx).outcome == Outcome.PASS


def test_competitive_density(b, ctx):
    for i in range(3):
        b.put(K.COMPETITOR, {"name": f"C{i}", "funding_usd": 20e6}, S.AGGREGATOR)
    assert run("market.competitive_density", b, ctx).outcome == Outcome.PASS
    b.put(K.COMPETITOR, {"name": "C4", "funding_usd": 90e6}, S.AGGREGATOR)
    assert run("market.competitive_density", b, ctx).outcome == Outcome.FAIL


def test_regulatory_license(b, ctx):
    b.put(K.LICENSE_REQUIRED, {"regulator": "RBI", "license": "NBFC registration"}, S.WEB_SEARCH)
    r = run("market.regulatory_license", b, ctx)
    assert r.outcome == Outcome.FAIL and "RBI" in r.detail
    b.put(K.LICENSE_HELD, {"regulator": "rbi", "license": "NBFC registration"}, S.NEWS)
    assert run("market.regulatory_license", b, ctx).outcome == Outcome.PASS


# --- traction -----------------------------------------------------------------


def test_revenue_claim_vs_filing(b, ctx):
    b.put(K.REVENUE_CLAIM, {"fy": "FY 2025", "amount_inr": 11_000_000}, S.COMPANY_WEBSITE)
    b.put(K.REVENUE_FILED, {"fy": "2024-25", "amount_inr": 10_000_000}, S.MCA)
    assert run("traction.revenue_claim_matches_filings", b, ctx).outcome == Outcome.PASS  # within 25%
    b.put(K.REVENUE_CLAIM, {"fy": "FY25", "amount_inr": 30_000_000}, S.COMPANY_WEBSITE)
    r = run("traction.revenue_claim_matches_filings", b, ctx)
    assert r.outcome == Outcome.FAIL and r.flag.severity == Severity.RED
    assert "state FY25 revenue of ₹3.00 crore; filed financials show ₹1.00 crore" in r.detail


def test_revenue_claim_different_years_is_unknown(b, ctx):
    b.put(K.REVENUE_CLAIM, {"fy": "FY26", "amount_inr": 5}, S.COMPANY_WEBSITE)
    b.put(K.REVENUE_FILED, {"fy": "FY24", "amount_inr": 1}, S.MCA)
    assert run("traction.revenue_claim_matches_filings", b, ctx).outcome == Outcome.UNKNOWN


def test_customer_concentration(b, ctx):
    b.put(K.TOP_CUSTOMER_SHARE, 0.7, S.COMPANY_WEBSITE)
    r = run("traction.customer_concentration", b, ctx)
    assert r.outcome == Outcome.FAIL and "70%" in r.detail


def test_headcount_trend(b, ctx):
    b.put(K.EMPLOYEE_COUNT, {"count": 100, "as_of": "2025-01-01"}, S.AGGREGATOR)
    assert run("traction.headcount_trend", b, ctx).outcome == Outcome.UNKNOWN
    b.put(K.EMPLOYEE_COUNT, {"count": 60, "as_of": "2026-06-01"}, S.AGGREGATOR)
    assert run("traction.headcount_trend", b, ctx).outcome == Outcome.FAIL


def test_web_presence(b, ctx):
    b.put(K.WEBSITE_STATUS, {"live": True, "last_updated": "2024-01-01"}, S.COMPUTED)
    assert run("traction.web_presence", b, ctx).outcome == Outcome.FAIL


# --- financials ---------------------------------------------------------------


@pytest.mark.parametrize(
    "filed_on, outcome, severity",
    [("2025-03-31", Outcome.PASS, Severity.GREEN), ("2024-03-31", Outcome.FAIL, Severity.YELLOW),
     ("2021-03-31", Outcome.FAIL, Severity.RED)],
)
def test_filings_current(b, ctx, filed_on, outcome, severity):
    b.put(K.LAST_FILING_DATE, filed_on)
    r = run("financials.filings_current", b, ctx)
    assert (r.outcome, r.flag.severity) == (outcome, severity)


def test_funding_verified_and_investors(b, ctx):
    b.put(K.FUNDING_ROUND, {"round": "Seed", "investors": ["monsoon ventures"], "independently_reported": True}, S.NEWS)
    assert run("financials.funding_verified", b, ctx).outcome == Outcome.PASS
    assert run("financials.institutional_investors", b, ctx).outcome == Outcome.PASS
    b.put(K.FUNDING_ROUND, {"round": "Pre-Series A", "investors": [], "independently_reported": False},
          S.COMPANY_WEBSITE)
    r = run("financials.funding_verified", b, ctx)
    assert r.outcome == Outcome.FAIL and "PAS-3" in r.flag.question


def test_unknown_investors_never_fail(b, ctx):
    b.put(K.FUNDING_ROUND, {"round": "Seed", "investors": ["Some Angel"], "independently_reported": True}, S.NEWS)
    assert run("financials.institutional_investors", b, ctx).outcome == Outcome.UNKNOWN


def test_revenue_trend(b, ctx):
    b.put(K.REVENUE_FILED, {"fy": "FY24", "amount_inr": 10_000_000})
    b.put(K.REVENUE_FILED, {"fy": "FY25", "amount_inr": 7_000_000})
    assert run("financials.revenue_trend", b, ctx).outcome == Outcome.FAIL


# --- legal --------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, outcome",
    [("Active", Outcome.PASS), ("Strike Off", Outcome.FAIL), ("Under process of Striking Off", Outcome.FAIL),
     ("Dormant under section 455", Outcome.FAIL), ("Amalgamated", Outcome.FAIL), ("Something new", Outcome.UNKNOWN)],
)
def test_company_active(b, ctx, status, outcome):
    b.put(K.STATUS, status)
    assert run("legal.company_active", b, ctx).outcome == outcome


def test_director_disqualification(b, ctx):
    b.put(K.DIRECTOR, {"name": "A", "disqualified": False})
    assert run("legal.director_disqualification", b, ctx).outcome == Outcome.PASS
    b.put(K.DIRECTOR, {"name": "B", "disqualified": True})
    r = run("legal.director_disqualification", b, ctx)
    assert r.outcome == Outcome.FAIL and r.flag.severity == Severity.RED


def test_litigation_rules(b, ctx):
    assert run("legal.litigation", b, ctx).outcome == Outcome.UNKNOWN
    b.put(K.LITIGATION_CASE, {"title": "X v. Co", "forum": "Civil Court", "case_type": "Commercial suit filed",
                              "status": "pending", "company_role": "respondent"}, S.COURT)
    r = run("legal.litigation", b, ctx)
    assert r.outcome == Outcome.FAIL and r.flag.severity == Severity.YELLOW  # "filed" must not match a serious type
    b.put(K.LITIGATION_CASE, {"title": "Bank v. Co", "forum": "NCLT Mumbai", "case_type": "IBC Section 7",
                              "status": "pending", "company_role": "respondent"}, S.COURT)
    assert run("legal.litigation", b, ctx).flag.severity == Severity.RED


def test_litigation_passes_only_after_official_search(b, ctx):
    b.put(K.LITIGATION_CASE, {"title": "Co v. Y", "forum": "HC", "case_type": "Recovery", "status": "pending",
                              "company_role": "petitioner"}, S.COURT)
    assert run("legal.litigation", b, ctx).outcome == Outcome.UNKNOWN
    b.put(K.LITIGATION_SEARCH_DONE, {"scope": "ecourts"}, S.COURT)
    assert run("legal.litigation", b, ctx).outcome == Outcome.PASS


def test_gst_registration(b, ctx):
    b.put(K.GSTIN, "27AAPFU0939F1ZA", S.COMPANY_WEBSITE)
    assert run("legal.gst_registration", b, ctx).outcome == Outcome.FAIL


def test_gst_registration_valid_needs_status_to_pass(b, ctx):
    b.put(K.GSTIN, "27AAPFU0939F1ZV", S.COMPANY_WEBSITE)
    assert run("legal.gst_registration", b, ctx).outcome == Outcome.UNKNOWN
    b.put(K.GST_STATUS, "Cancelled", S.GST)
    assert run("legal.gst_registration", b, ctx).outcome == Outcome.FAIL


def test_trademark(b, ctx):
    b.put(K.TRADEMARK, {"mark": "ACME", "status": "registered", "owner_matches_company": True}, S.IP_INDIA)
    assert run("legal.trademark", b, ctx).outcome == Outcome.PASS


def test_incorporation_claim_allows_one_year(b, ctx):
    b.put(K.INCORPORATION_DATE, "2021-06-14")
    b.put(K.CLAIMED_FOUNDING_YEAR, 2020, S.COMPANY_WEBSITE)
    assert run("legal.incorporation_claim", b, ctx).outcome == Outcome.PASS
