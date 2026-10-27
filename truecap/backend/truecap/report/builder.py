"""Assemble a report from facts: checks -> scores -> flags, pros/cons, questions.

Pros/cons text is deterministic by default. In the pipeline an LLM may propose
better-worded text per check (`narrative`); a proposal is used only if it passes the
strict wording guard and cites valid evidence, otherwise the deterministic text stays.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from truecap.checks import CheckContext, run_all
from truecap.domain import CheckResult, FactSet, Outcome, Severity, Stage, utcnow
from truecap.guards.citations import strip_uncited_sentences, validate_ids
from truecap.guards.wording import find_violations
from truecap.report.fundamentals import build_fundamentals
from truecap.report.manual import manual_checks_for
from truecap.report.models import Con, FlagView, FounderQuestion, FounderReplyView, Pro, Report
from truecap.scoring import ScoreCard, fail_impact, infer_stage, score

MAX_PROS = 5
MAX_CONS = 5
_SEVERITY_ORDER = {Severity.RED: 0, Severity.YELLOW: 1, Severity.GREEN: 2}


class NarrativeDraft(BaseModel):
    """LLM-proposed wording, keyed by check_id. Text must carry inline [E#] citations."""

    pros: dict[str, str] = {}
    cons: dict[str, str] = {}


class _Guard:
    def __init__(self, facts: FactSet) -> None:
        self.facts = facts
        self.log: list[str] = []

    def ok(self, text: str, evidence_ids: list[str], where: str, strict: bool = False) -> bool:
        reason = validate_ids(evidence_ids, self.facts.ledger)
        if reason:
            self.log.append(f"removed {where}: {reason}: {text!r}")
            return False
        violations = find_violations(text, strict=strict)
        if violations:
            terms = ", ".join(sorted({v.term for v in violations}))
            self.log.append(f"removed {where}: wording rule ({terms}): {text!r}")
            return False
        return True

    def llm_text(self, text: str | None, where: str) -> tuple[str, list[str]] | None:
        if not text:
            return None
        clean, ids, dropped = strip_uncited_sentences(text, self.facts.ledger)
        for d in dropped:
            self.log.append(f"removed sentence from {where}: {d.reason}: {d.text!r}")
        if not clean or not self.ok(clean, ids, where, strict=True):
            return None
        return clean, ids


def _flags(results: list[CheckResult], guard: _Guard, replies: dict[str, list[FounderReplyView]]) -> list[FlagView]:
    flags = []
    for r in results:
        if r.flag is None:
            continue
        f = r.flag
        text = " ".join(filter(None, [f.title, f.detail, f.question]))
        if guard.ok(text, f.evidence_ids, f"flag {f.check_id}"):
            flags.append(FlagView(**f.model_dump(), replies=replies.get(f.check_id, [])))
    return sorted(flags, key=lambda f: _SEVERITY_ORDER[f.severity])


def _pros(results: list[CheckResult], guard: _Guard, narrative: NarrativeDraft) -> list[Pro]:
    passed = [r for r in results if r.outcome == Outcome.PASS]
    # Verified strengths (green flags) first, then heavier checks.
    passed.sort(key=lambda r: (r.flag is None or r.flag.severity != Severity.GREEN, -r.weight))
    pros = []
    for r in passed:
        if len(pros) == MAX_PROS:
            break
        llm = guard.llm_text(narrative.pros.get(r.check_id), f"pro {r.check_id}")
        text, ids = llm if llm else (r.detail, r.evidence_ids)
        if guard.ok(text, ids, f"pro {r.check_id}"):
            pros.append(Pro(text=text, category=r.category, evidence_ids=ids, check_id=r.check_id))
    return pros


def _cons(results: list[CheckResult], card: ScoreCard, guard: _Guard, narrative: NarrativeDraft) -> list[Con]:
    failed = [(r, fail_impact(card, r.check_id)) for r in results if r.outcome == Outcome.FAIL]
    failed.sort(key=lambda ri: (_SEVERITY_ORDER[ri[0].flag.severity] if ri[0].flag else 1, ri[1].overall_points * -1))
    cons = []
    for r, impact in failed:
        if len(cons) == MAX_CONS:
            break
        llm = guard.llm_text(narrative.cons.get(r.check_id), f"con {r.check_id}")
        text, ids = llm if llm else (r.detail, r.evidence_ids)
        question = r.flag.question if r.flag else None
        if guard.ok(" ".join(filter(None, [text, question])), ids, f"con {r.check_id}"):
            cons.append(
                Con(
                    text=text,
                    category=r.category,
                    evidence_ids=ids,
                    check_id=r.check_id,
                    question=question,
                    category_impact=-impact.category_points,
                    overall_impact=-impact.overall_points,
                )
            )
    return cons


def _questions(flags: list[FlagView], cons: list[Con]) -> list[FounderQuestion]:
    seen: set[str] = set()
    out = []
    sources = [(f.question, f.category, f.check_id, f.evidence_ids) for f in flags if f.severity != Severity.GREEN]
    sources += [(c.question, c.category, c.check_id, c.evidence_ids) for c in cons]
    for q, cat, check_id, ids in sources:
        if q and q not in seen:
            seen.add(q)
            out.append(FounderQuestion(question=q, category=cat, check_id=check_id, evidence_ids=ids))
    return out


def build_report(
    company_name: str,
    facts: FactSet,
    ctx: CheckContext | None = None,
    stage_override: Stage | None = None,
    narrative: NarrativeDraft | None = None,
    replies: dict[str, list[FounderReplyView]] | None = None,
    generated_at: datetime | None = None,
) -> Report:
    ctx = ctx or CheckContext()
    narrative = narrative or NarrativeDraft()
    guard = _Guard(facts)

    results = run_all(facts, ctx)
    stage = infer_stage(facts, stage_override)
    card = score(results, stage.stage)
    flags = _flags(results, guard, replies or {})
    cons = _cons(results, card, guard, narrative)

    return Report(
        company_name=company_name,
        generated_at=generated_at or utcnow(),
        stage=stage,
        scorecard=card,
        flags=flags,
        pros=_pros(results, guard, narrative),
        cons=cons,
        fundamentals=build_fundamentals(facts),
        questions=_questions(flags, cons),
        manual_checks=manual_checks_for(results),
        evidence=list(facts.ledger),
        guard_log=guard.log,
    )
