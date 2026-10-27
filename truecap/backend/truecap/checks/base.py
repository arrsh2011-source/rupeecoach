"""Check framework.

A check is a small deterministic function over a `FactSet`. It returns a `Verdict`
(pass / fail / unknown + neutral detail + the evidence it relied on). Checks never
call an LLM and never guess: no relevant facts means UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from truecap.domain import Category, CheckResult, Fact, FactSet, Flag, Outcome, Severity


@dataclass
class CheckContext:
    today: date = field(default_factory=date.today)
    reputable_investors: frozenset[str] = frozenset()


@dataclass
class Verdict:
    outcome: Outcome
    detail: str
    evidence_ids: list[str] = field(default_factory=list)
    severity: Severity | None = None  # set to raise a flag
    flag_title: str | None = None
    question: str | None = None


CheckFn = Callable[[FactSet, CheckContext], Verdict]


@dataclass(frozen=True)
class CheckSpec:
    id: str
    category: Category
    title: str
    weight: float
    fn: CheckFn

    def run(self, facts: FactSet, ctx: CheckContext) -> CheckResult:
        v = self.fn(facts, ctx)
        unknown_ids = [e for e in v.evidence_ids if e not in facts.ledger]
        if unknown_ids:
            raise ValueError(f"check {self.id} cited unknown evidence {unknown_ids}")
        if v.outcome != Outcome.UNKNOWN and not v.evidence_ids:
            raise ValueError(f"check {self.id} returned {v.outcome} without evidence")
        flag = None
        if v.severity is not None:
            flag = Flag(
                severity=v.severity,
                title=v.flag_title or self.title,
                detail=v.detail,
                question=v.question,
                evidence_ids=v.evidence_ids,
                check_id=self.id,
                category=self.category,
            )
        return CheckResult(
            check_id=self.id,
            category=self.category,
            title=self.title,
            outcome=v.outcome,
            detail=v.detail,
            evidence_ids=v.evidence_ids,
            weight=self.weight,
            flag=flag,
        )


REGISTRY: dict[str, CheckSpec] = {}


def check(id: str, category: Category, title: str, weight: float = 1.0) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        if id in REGISTRY:
            raise ValueError(f"duplicate check id {id}")
        REGISTRY[id] = CheckSpec(id=id, category=category, title=title, weight=weight, fn=fn)
        return fn

    return register


def unknown(detail: str) -> Verdict:
    return Verdict(Outcome.UNKNOWN, detail)


def ev(*facts: Fact | None) -> list[str]:
    """Collect evidence ids from facts, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for f in facts:
        if f is not None:
            for e in f.evidence_ids:
                seen.setdefault(e, None)
    return list(seen)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def inr(amount: float) -> str:
    """Format rupees in crore / lakh, the way Indian filings are read."""
    if amount >= 1e7:
        return f"₹{amount / 1e7:,.2f} crore"
    if amount >= 1e5:
        return f"₹{amount / 1e5:,.2f} lakh"
    return f"₹{amount:,.0f}"
