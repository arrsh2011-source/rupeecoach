"""SQLAlchemy models. Postgres in production; SQLite works for tests and local dev."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from truecap.domain import utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class JobStatus(StrEnum):
    QUEUED = "queued"
    AWAITING_PICK = "awaiting_pick"  # several companies matched; user must choose
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ReplyStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reports: Mapped[list[ReportRow]] = relationship(back_populates="user")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    cin: Mapped[str | None] = mapped_column(String(21), unique=True)
    city: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchJob(Base):
    """Postgres-backed job queue row (workers claim with SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "research_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    query: Mapped[dict] = mapped_column(default=dict)  # {"name", "city", "website"}
    candidates: Mapped[list] = mapped_column(default=list)
    stage_override: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED, index=True)
    step: Mapped[str | None] = mapped_column(String(40))  # resolve, gather, extract, check, score, write
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    message: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SourceDocument(Base):
    """Cache of fetched public documents, shared across users to keep repeat lookups cheap."""

    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("url", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    url: Mapped[str] = mapped_column(String(2000), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # reports are private to this user
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("research_jobs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stage: Mapped[str] = mapped_column(String(20))
    overall_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(10))
    weights_version: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column()  # full Report JSON as shown to the user

    user: Mapped[User] = relationship(back_populates="reports")
    evidence: Mapped[list[EvidenceRow]] = relationship(cascade="all, delete-orphan")
    facts: Mapped[list[FactRow]] = relationship(cascade="all, delete-orphan")
    checks: Mapped[list[CheckRow]] = relationship(cascade="all, delete-orphan")


class EvidenceRow(Base):
    """The evidence ledger: claim, source, URL, date fetched. Every number traces here."""

    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("report_id", "evidence_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    evidence_key: Mapped[str] = mapped_column(String(10))  # "E12"
    claim: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30))
    reliability: Mapped[str] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FactRow(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(JSON)
    subject: Mapped[str | None] = mapped_column(String(200))
    evidence_keys: Mapped[list] = mapped_column()


class CheckRow(Base):
    """Result of each check: pass / fail / unknown, with the evidence it relied on."""

    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float)
    evidence_keys: Mapped[list] = mapped_column()


class FounderReply(Base):
    """Founder right-of-reply to a flag. Shown next to the flag only once an admin approves it."""

    __tablename__ = "founder_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(80))
    submitted_name: Mapped[str] = mapped_column(String(200))
    submitted_role: Mapped[str] = mapped_column(String(200))
    submitted_email: Mapped[str] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default=ReplyStatus.PENDING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmUsage(Base):
    """Spend tracking for the monthly budget cap."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("research_jobs.id"), index=True)
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
