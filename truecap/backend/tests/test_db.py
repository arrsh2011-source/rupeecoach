from datetime import datetime, timezone

import pytest

from truecap.db.models import Company, FounderReply, ReplyStatus, User
from truecap.db.repository import (
    approved_replies, get_report_for_user, init_db, load_factset, make_engine, reports_for_user, save_report,
    session_factory,
)
from truecap.report import build_report
from truecap.sample_data import kisankart


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as s:
        yield s


def _setup(session):
    alice, bob = User(email="alice@example.com"), User(email="bob@example.com")
    co = Company(name="Kisankart Agritech", normalized_name="kisankart agritech")
    session.add_all([alice, bob, co])
    session.flush()
    return alice, bob, co


def test_report_round_trip_keeps_full_ledger(session, ctx):
    alice, _, co = _setup(session)
    name, facts = kisankart()
    report = build_report(name, facts, ctx)
    row = save_report(session, user_id=alice.id, company_id=co.id, report=report, facts=facts)
    session.commit()

    assert row.overall_score == report.scorecard.overall
    assert len(row.evidence) == len(facts.ledger)
    assert len(row.checks) == sum(len(c.checks) for c in report.scorecard.categories)

    reloaded = load_factset(row)
    assert reloaded.ledger.ids() == facts.ledger.ids()
    assert reloaded.keys() == facts.keys()
    rebuilt = build_report(name, reloaded, ctx, generated_at=report.generated_at)
    assert rebuilt.scorecard == report.scorecard  # every number reproducible from the stored ledger


def test_reports_are_private(session, ctx):
    alice, bob, co = _setup(session)
    name, facts = kisankart()
    row = save_report(session, user_id=alice.id, company_id=co.id, report=build_report(name, facts, ctx), facts=facts)
    assert get_report_for_user(session, row.id, alice.id) is not None
    assert get_report_for_user(session, row.id, bob.id) is None
    assert reports_for_user(session, bob.id) == []


def test_only_approved_replies_are_shown(session):
    _, _, co = _setup(session)
    common = dict(company_id=co.id, check_id="legal.trademark", submitted_name="Asha Rao", submitted_role="CEO",
                  submitted_email="asha@kisankart.example")
    session.add_all([
        FounderReply(**common, body="pending one"),
        FounderReply(**common, body="approved one", status=ReplyStatus.APPROVED,
                     reviewed_at=datetime(2026, 10, 1, tzinfo=timezone.utc)),
    ])
    session.flush()
    replies = approved_replies(session, co.id)
    assert [r.body for r in replies["legal.trademark"]] == ["approved one"]
    assert replies["legal.trademark"][0].submitted_by == "Asha Rao, CEO"
