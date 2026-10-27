"""The report as the API returns it. Every user-visible statement carries evidence ids."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from truecap.domain import Category, Evidence, Severity
from truecap.scoring import ScoreCard, StageDecision

DISCLAIMER_LINE = (
    "Not investment advice. This report checks public claims against public records, "
    "may be incomplete or out of date, and is AI-assisted. Verify independently."
)
DISCLAIMER_URL = "/disclaimer"


class FieldStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_FOUND = "not_found"


class FounderReplyView(BaseModel):
    submitted_by: str  # name and role, as submitted
    body: str
    approved_at: datetime


class FlagView(BaseModel):
    severity: Severity
    category: Category
    title: str
    detail: str
    question: str | None
    evidence_ids: list[str]
    check_id: str
    replies: list[FounderReplyView] = Field(default_factory=list)


class Pro(BaseModel):
    text: str
    category: Category
    evidence_ids: list[str]
    check_id: str


class Con(BaseModel):
    text: str
    category: Category
    evidence_ids: list[str]
    check_id: str
    question: str | None
    category_impact: float  # negative: points this costs in its category
    overall_impact: float  # negative: points this costs overall

    @property
    def impact_label(self) -> str:
        return f"{self.category_impact:+.1f} on {self.category.value.title()}"


class FundamentalField(BaseModel):
    key: str
    label: str
    value: str | None
    status: FieldStatus
    evidence_ids: list[str] = Field(default_factory=list)


class FounderQuestion(BaseModel):
    question: str
    category: Category
    check_id: str
    evidence_ids: list[str]


class ManualCheck(BaseModel):
    """A check TrueCap could not automate (portal needs CAPTCHA/login). The user verifies it."""

    title: str
    why: str
    url: str
    check_id: str


class Report(BaseModel):
    company_name: str
    generated_at: datetime
    disclaimer: str = DISCLAIMER_LINE
    disclaimer_url: str = DISCLAIMER_URL
    stage: StageDecision
    scorecard: ScoreCard
    flags: list[FlagView]
    pros: list[Pro]
    cons: list[Con]
    fundamentals: list[FundamentalField]
    questions: list[FounderQuestion]
    manual_checks: list[ManualCheck]
    evidence: list[Evidence]
    guard_log: list[str] = Field(default_factory=list)  # what the guards removed, for audit
