from datetime import datetime, timezone

import pytest

from truecap.domain import Severity, Stage
from truecap.guards import is_neutral
from truecap.report import NarrativeDraft, build_report
from truecap.report.models import FieldStatus, FounderReplyView
from truecap.sample_data import kisankart, sparse, struck_off
from truecap.scoring import Confidence


@pytest.fixture
def report(ctx):
    name, facts = kisankart()
    return build_report(name, facts, ctx)


def _visible_statements(r):
    for f in r.flags:
        yield f.detail, f.evidence_ids
    for p in r.pros:
        yield p.text, p.evidence_ids
    for c in r.cons:
        yield c.text, c.evidence_ids
    for q in r.questions:
        yield q.question, q.evidence_ids


@pytest.mark.parametrize("make", [kisankart, struck_off, sparse])
def test_every_statement_is_sourced_and_neutral(make, ctx):
    name, facts = make()
    r = build_report(name, facts, ctx)
    ids = {e.id for e in r.evidence}
    for text, evidence_ids in _visible_statements(r):
        assert evidence_ids and set(evidence_ids) <= ids, text
        assert is_neutral(text), text
    assert r.disclaimer.startswith("Not investment advice")
    assert r.guard_log == []


def test_kisankart_report_shape(report):
    card = report.scorecard
    assert report.stage.stage == Stage.SEED
    assert card.confidence == Confidence.HIGH
    assert 0 < card.overall < 10
    assert report.flags[0].severity == Severity.RED
    assert report.flags[0].check_id == "traction.revenue_claim_matches_filings"
    severities = [f.severity for f in report.flags]
    assert severities == sorted(severities, key=["red", "yellow", "green"].index)
    assert 3 <= len(report.pros) <= 5 and 3 <= len(report.cons) <= 5
    assert report.cons[0].check_id == "traction.revenue_claim_matches_filings"
    assert report.cons[0].category_impact < 0
    assert report.cons[0].impact_label.endswith("on Traction")
    assert len({q.question for q in report.questions}) == len(report.questions)


def test_fundamentals_statuses(report):
    by_key = {f.key: f for f in report.fundamentals}
    assert by_key["company.cin"].status == FieldStatus.VERIFIED
    assert by_key["financials.revenue_filed"].status == FieldStatus.UNVERIFIED  # single secondary source
    assert by_key["company.paid_up_capital_inr"].value == "₹12.50 lakh"
    labels = {f.label for f in report.fundamentals}
    for required in ["Incorporation date", "Company type", "Registered office", "Current directors",
                     "Paid-up capital", "Funding rounds & investors", "Employees (estimate)", "Revenue (filed)",
                     "Website & social"]:
        assert required in labels


def test_not_found_fields(ctx):
    name, facts = sparse()
    r = build_report(name, facts, ctx)
    by_key = {f.key: f for f in r.fundamentals}
    assert by_key["company.registered_office"].status == FieldStatus.NOT_FOUND
    assert by_key["company.registered_office"].value is None


def test_manual_checks_listed_for_unknown_portal_checks(report):
    assert {m.check_id for m in report.manual_checks} == {"legal.litigation", "legal.gst_registration"}


def test_struck_off_company(ctx):
    name, facts = struck_off()
    r = build_report(name, facts, ctx)
    red = {f.check_id for f in r.flags if f.severity == Severity.RED}
    assert {"legal.company_active", "legal.director_disqualification", "financials.filings_current"} <= red
    assert r.scorecard.category("legal").score == 0.0


def test_stage_override_reweights_without_new_research(ctx):
    name, facts = kisankart()
    seed = build_report(name, facts, ctx)
    series_a = build_report(name, facts, ctx, stage_override=Stage.SERIES_A)
    assert series_a.stage.overridden
    assert series_a.scorecard.weights != seed.scorecard.weights
    assert series_a.scorecard.overall != seed.scorecard.overall


def test_llm_narrative_used_only_when_it_passes_guards(ctx):
    name, facts = kisankart()
    narrative = NarrativeDraft(
        pros={
            "legal.company_active": "The registry lists the company as Active [E1].",
            "financials.filings_current": "A great investment with current filings [E2].",  # advice -> rejected
        },
        cons={
            "traction.revenue_claim_matches_filings": "The website cites FY25 revenue of ₹4.5 crore [E4], while "
                                                      "filed figures show ₹2.10 crore [E3].",
            "market.size_claim_sourced": "The market is $90 billion [E5].",  # number not in source -> rejected
        },
    )
    r = build_report(name, facts, ctx, narrative=narrative)
    pros = {p.check_id: p.text for p in r.pros}
    cons = {c.check_id: c.text for c in r.cons}
    assert pros["legal.company_active"] == "The registry lists the company as Active [E1]."
    assert "great investment" not in pros["financials.filings_current"]
    assert "[E3]" in cons["traction.revenue_claim_matches_filings"]
    assert "$90 billion" not in cons["market.size_claim_sourced"]
    assert len(r.guard_log) == 2


def test_founder_replies_attached_to_flag(ctx):
    name, facts = kisankart()
    reply = FounderReplyView(submitted_by="Asha Rao, CEO", body="FY25 figure on the site includes GMV; fixed.",
                             approved_at=datetime(2026, 10, 20, tzinfo=timezone.utc))
    r = build_report(name, facts, ctx, replies={"traction.revenue_claim_matches_filings": [reply]})
    flag = next(f for f in r.flags if f.check_id == "traction.revenue_claim_matches_filings")
    assert flag.replies == [reply]


def test_report_serialises_to_json(report):
    data = report.model_dump(mode="json")
    assert data["scorecard"]["categories"][0]["checks"]
    assert data["evidence"][0]["id"] == "E1"
