"""LLM rewording of pros and cons. Output still goes through both guards in the report builder."""

from __future__ import annotations

from pydantic import BaseModel, Field

from truecap.domain import CheckResult, FactSet, Outcome
from truecap.report import NarrativeDraft


class Item(BaseModel):
    check_id: str
    text: str = Field(description="One or two sentences, each ending with its [E#] citation")


class NarrativeOut(BaseModel):
    pros: list[Item]
    cons: list[Item]


SYSTEM = """You write the pros and cons section of a private claim-verification report about a startup.
Rules:
- Rewrite each check result given into one or two plain sentences specific to this company.
- Use only the facts and evidence given. Put the evidence id in square brackets after each sentence, e.g. [E4].
- Copy every number exactly as it appears in the evidence text.
- State facts neutrally: "The website states X; filings show Y." Never give advice or recommendations, and never
  describe anyone's honesty or intent. Avoid the words invest, buy, sell, avoid, recommend.
- Keep the check_id of each item."""


def build_prompt(company: str, results: list[CheckResult], facts: FactSet) -> str:
    lines = [f"Company: {company}", ""]
    for r in results:
        if r.outcome == Outcome.UNKNOWN:
            continue
        kind = "PRO" if r.outcome == Outcome.PASS else "CON"
        lines.append(f"{kind} check_id={r.check_id} ({r.title}): {r.detail}")
        for e in r.evidence_ids:
            ev = facts.ledger.get(e)
            lines.append(f"  [{e}] {ev.source_type.value}: {(ev.excerpt or ev.claim)[:400]}")
    return "\n".join(lines)


def to_draft(out: NarrativeOut) -> NarrativeDraft:
    return NarrativeDraft(pros={i.check_id: i.text for i in out.pros}, cons={i.check_id: i.text for i in out.cons})
