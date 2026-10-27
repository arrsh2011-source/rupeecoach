from __future__ import annotations

from truecap.checks.base import CheckContext, Verdict, check, ev, inr, months_between, parse_date, unknown
from truecap.domain import Category, FactSet, Outcome, Severity
from truecap.facts import FactKey, fy_label

C = Category.FINANCIALS
FILING_OVERDUE_MONTHS = 20  # FY ends in March, AOC-4 is due ~Oct; allow for that plus slack
REVENUE_DECLINE = 0.25


@check("financials.filings_current", C, "Annual filings up to date", weight=1.5)
def filings_current(facts: FactSet, ctx: CheckContext) -> Verdict:
    f = facts.first(FactKey.LAST_FILING_DATE)
    if f is None:
        return unknown("The date of the latest annual filing was not found.")
    last = parse_date(f.value)
    age = months_between(last, ctx.today)
    if age > FILING_OVERDUE_MONTHS:
        return Verdict(
            Outcome.FAIL,
            f"The latest financial statements on record are dated {last:%d %b %Y} ({age} months ago).",
            ev(f),
            Severity.RED if age > 2 * FILING_OVERDUE_MONTHS else Severity.YELLOW,
            "Annual filings appear overdue",
            "Have the latest annual returns and financial statements been filed with the MCA?",
        )
    return Verdict(
        Outcome.PASS,
        f"Latest financial statements on record are dated {last:%d %b %Y}.",
        ev(f),
        Severity.GREEN,
        "Filings up to date",
    )


@check("financials.funding_verified", C, "Funding claims independently reported")
def funding_verified(facts: FactSet, ctx: CheckContext) -> Verdict:
    rounds = facts.all(FactKey.FUNDING_ROUND)
    if not rounds:
        return unknown("No funding rounds were found.")
    unreported = [r for r in rounds if not r.value.get("independently_reported")]
    if unreported:
        r = unreported[0]
        return Verdict(
            Outcome.FAIL,
            f"The {r.value['round']} round is mentioned only in company materials; "
            "no independent report or filing was found.",
            ev(*unreported),
            Severity.YELLOW,
            "Funding round not independently reported",
            f"Can you share the share allotment filing (PAS-3) or term sheet for the {r.value['round']} round?",
        )
    return Verdict(Outcome.PASS, f"All {len(rounds)} funding round(s) are independently reported.", ev(*rounds))


@check("financials.institutional_investors", C, "Backed by established investors")
def institutional_investors(facts: FactSet, ctx: CheckContext) -> Verdict:
    rounds = [r for r in facts.all(FactKey.FUNDING_ROUND) if r.value.get("independently_reported")]
    known = {i.lower() for i in ctx.reputable_investors}
    hits = [(r, i) for r in rounds for i in r.value.get("investors", []) if i.lower() in known]
    if hits:
        names = ", ".join(sorted({i for _, i in hits}))
        return Verdict(
            Outcome.PASS,
            f"Investors include {names}.",
            ev(*(r for r, _ in hits)),
            Severity.GREEN,
            "Established investors on the cap table",
        )
    # Not having a well-known investor is not a problem in itself, so this never fails.
    return unknown("No investors from the established-investor list were found.")


@check("financials.revenue_trend", C, "Filed revenue trend")
def revenue_trend(facts: FactSet, ctx: CheckContext) -> Verdict:
    filed = sorted(facts.all(FactKey.REVENUE_FILED), key=lambda f: fy_label(f.value["fy"]))
    if len(filed) < 2:
        return unknown("Fewer than two years of filed revenue were found.")
    prev, last = filed[-2], filed[-1]
    a, b = prev.value["amount_inr"], last.value["amount_inr"]
    pfy, lfy = fy_label(prev.value["fy"]), fy_label(last.value["fy"])
    if a > 0 and (a - b) / a >= REVENUE_DECLINE:
        return Verdict(
            Outcome.FAIL,
            f"Filed revenue went from {inr(a)} in {pfy} to {inr(b)} in {lfy}.",
            ev(prev, last),
            Severity.YELLOW,
            "Filed revenue declined",
            f"What caused revenue to fall between {pfy} and {lfy}?",
        )
    return Verdict(Outcome.PASS, f"Filed revenue went from {inr(a)} in {pfy} to {inr(b)} in {lfy}.", ev(prev, last))
