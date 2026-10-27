"""Print a report for a fictional sample company: `python -m truecap.demo [kisankart|struck_off|sparse]`."""

from __future__ import annotations

import sys

from truecap import sample_data
from truecap.domain import Outcome, Stage
from truecap.report import build_report

_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
_OUTCOME = {Outcome.PASS: "✓", Outcome.FAIL: "✗", Outcome.UNKNOWN: "?"}


def main(argv: list[str]) -> None:
    which = argv[1] if len(argv) > 1 else "kisankart"
    stage = Stage(argv[2]) if len(argv) > 2 else None
    name, facts = getattr(sample_data, which)()
    r = build_report(name, facts, sample_data.sample_ctx(), stage_override=stage)
    card = r.scorecard

    print(f"\n{r.company_name}\n{r.disclaimer}\n")
    overall = "n/a" if card.overall is None else f"{card.overall}/10"
    print(f"Diligence Score {overall}   confidence: {card.confidence.value.upper()} (coverage {card.coverage:.0%})")
    print(f"Stage: {r.stage.stage.value} — {r.stage.reason}\n")
    for c in card.categories:
        bar = "█" * round(c.score or 0) + "░" * (10 - round(c.score or 0))
        s = "  ? " if c.score is None else f"{c.score:4.1f}"
        print(f"  {c.category.value:<11}{bar} {s}  weight {c.weight:.0%}  "
              f"({c.passed} pass, {c.failed} fail, {c.unknown} unknown)")
        for chk in c.checks:
            print(f"      {_OUTCOME[chk.outcome]} {chk.title}: {chk.detail}  {chk.evidence_ids}")
    print("\nFlags")
    for f in r.flags:
        print(f"  {_ICON[f.severity]} {f.title}: {f.detail} {f.evidence_ids}")
    print("\nPros")
    for p in r.pros:
        print(f"  + {p.text} {p.evidence_ids}")
    print("\nCons")
    for c in r.cons:
        print(f"  - {c.text} [{c.impact_label}] {c.evidence_ids}")
    print("\nFundamentals")
    for f in r.fundamentals:
        print(f"  {f.label:<28}{f.status.value:<11}{f.value or '—'}")
    print("\nQuestions to ask the founder")
    for i, q in enumerate(r.questions, 1):
        print(f"  {i}. {q.question}")
    if r.manual_checks:
        print("\nVerify yourself (official portals need a CAPTCHA)")
        for m in r.manual_checks:
            print(f"  • {m.title}: {m.url}")
    print("\nEvidence ledger")
    for e in r.evidence:
        print(f"  {e.id:<4}{e.reliability.value:<14}{e.claim}  {e.url or ''}")
    if r.guard_log:
        print("\nGuard log")
        for line in r.guard_log:
            print(f"  {line}")


if __name__ == "__main__":
    main(sys.argv)
