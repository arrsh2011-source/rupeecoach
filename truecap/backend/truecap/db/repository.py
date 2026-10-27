"""Persist and reload reports together with their full evidence ledger."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from truecap.db.models import Base, CheckRow, EvidenceRow, FactRow, FounderReply, ReplyStatus, ReportRow
from truecap.domain import Evidence, Fact, FactSet, Ledger
from truecap.report.models import FounderReplyView, Report


def make_engine(url: str) -> Engine:
    return create_engine(url, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def save_report(session: Session, *, user_id: int, company_id: int, report: Report, facts: FactSet,
                job_id: int | None = None) -> ReportRow:
    card = report.scorecard
    row = ReportRow(
        user_id=user_id,
        company_id=company_id,
        job_id=job_id,
        generated_at=report.generated_at,
        stage=report.stage.stage,
        overall_score=card.overall,
        confidence=card.confidence,
        weights_version=card.weights_version,
        payload=report.model_dump(mode="json"),
    )
    row.evidence = [
        EvidenceRow(
            evidence_key=e.id, claim=e.claim, source_type=e.source_type, reliability=e.reliability,
            url=e.url, title=e.title, excerpt=e.excerpt, fetched_at=e.fetched_at,
        )
        for e in facts.ledger
    ]
    row.facts = [
        FactRow(key=f.key, value={"v": f.value, "quote": f.quote}, subject=f.subject, evidence_keys=f.evidence_ids)
        for key in sorted(facts.keys())
        for f in facts.all(key)
    ]
    row.checks = [
        CheckRow(
            check_id=r.check_id, category=r.category, outcome=r.outcome, detail=r.detail,
            weight=r.weight, evidence_keys=r.evidence_ids,
        )
        for c in card.categories
        for r in c.checks
    ]
    session.add(row)
    session.flush()
    return row


def load_factset(row: ReportRow) -> FactSet:
    """Rebuild the ledger and facts exactly as they were when the report was generated."""
    ledger = Ledger(
        Evidence(
            id=e.evidence_key, claim=e.claim, source_type=e.source_type, reliability=e.reliability,
            url=e.url, title=e.title, excerpt=e.excerpt, fetched_at=e.fetched_at,
        )
        for e in sorted(row.evidence, key=lambda e: int(e.evidence_key[1:]))
    )
    return FactSet(
        ledger,
        (
            Fact(key=f.key, value=f.value["v"], quote=f.value.get("quote"), subject=f.subject,
                 evidence_ids=f.evidence_keys)
            for f in row.facts
        ),
    )


def reports_for_user(session: Session, user_id: int) -> list[ReportRow]:
    stmt = select(ReportRow).where(ReportRow.user_id == user_id).order_by(ReportRow.generated_at.desc())
    return list(session.scalars(stmt))


def get_report_for_user(session: Session, report_id: int, user_id: int) -> ReportRow | None:
    """Reports are private: a user can only load their own."""
    stmt = select(ReportRow).where(ReportRow.id == report_id, ReportRow.user_id == user_id)
    return session.scalars(stmt).first()


def approved_replies(session: Session, company_id: int) -> dict[str, list[FounderReplyView]]:
    stmt = select(FounderReply).where(
        FounderReply.company_id == company_id, FounderReply.status == ReplyStatus.APPROVED
    ).order_by(FounderReply.reviewed_at)
    out: dict[str, list[FounderReplyView]] = {}
    for r in session.scalars(stmt):
        out.setdefault(r.check_id, []).append(
            FounderReplyView(
                submitted_by=f"{r.submitted_name}, {r.submitted_role}", body=r.body, approved_at=r.reviewed_at
            )
        )
    return out
