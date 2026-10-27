from __future__ import annotations

from truecap.checks.base import CheckContext, Verdict, check, ev, inr, months_between, parse_date, unknown
from truecap.domain import Category, FactSet, Outcome, Severity
from truecap.facts import FactKey, fy_label

C = Category.TRACTION
CLAIM_TOLERANCE = 1.25  # claims up to 25% above filed figures are treated as consistent
CONCENTRATION_THRESHOLD = 0.5
HEADCOUNT_DROP = 0.3
STALE_WEBSITE_MONTHS = 12


@check("traction.revenue_claim_matches_filings", C, "Revenue claims match filed financials", weight=2.0)
def revenue_claim_matches_filings(facts: FactSet, ctx: CheckContext) -> Verdict:
    claims = {fy_label(c.value["fy"]): c for c in facts.all(FactKey.REVENUE_CLAIM)}
    filed = {fy_label(f.value["fy"]): f for f in facts.all(FactKey.REVENUE_FILED)}
    common = sorted(set(claims) & set(filed))
    if not common:
        return unknown("No revenue claim could be compared with a filed figure for the same year.")
    for fy in reversed(common):
        c, f = claims[fy], filed[fy]
        claimed, actual = c.value["amount_inr"], f.value["amount_inr"]
        if actual >= 0 and claimed > actual * CLAIM_TOLERANCE:
            return Verdict(
                Outcome.FAIL,
                f"Company materials state {fy} revenue of {inr(claimed)}; filed financials show {inr(actual)}.",
                ev(c, f),
                Severity.RED,
                "Revenue claim differs from filings",
                f"Can you reconcile the {fy} revenue figure with the filed financial statements?",
            )
    return Verdict(
        Outcome.PASS,
        f"Claimed revenue is consistent with filed financials for {', '.join(common)}.",
        ev(*(claims[fy] for fy in common), *(filed[fy] for fy in common)),
        Severity.GREEN,
        "Revenue claims match filings",
    )


@check("traction.customer_concentration", C, "Customer concentration")
def customer_concentration(facts: FactSet, ctx: CheckContext) -> Verdict:
    f = facts.first(FactKey.TOP_CUSTOMER_SHARE)
    if f is None:
        return unknown("Customer concentration was not disclosed.")
    share = float(f.value)
    if share > CONCENTRATION_THRESHOLD:
        return Verdict(
            Outcome.FAIL,
            f"The largest customer accounts for about {share:.0%} of revenue.",
            ev(f),
            Severity.YELLOW,
            "Single customer is a large share of revenue",
            "What is the contract term with the largest customer, and what happens if it ends?",
        )
    return Verdict(Outcome.PASS, f"The largest customer accounts for about {share:.0%} of revenue.", ev(f))


@check("traction.specific_metrics", C, "Traction claims are specific and measurable")
def specific_metrics(facts: FactSet, ctx: CheckContext) -> Verdict:
    vague = facts.all(FactKey.VAGUE_CLAIM)
    if vague:
        quoted = "; ".join(f"\"{v.value['text']}\"" for v in vague[:2])
        return Verdict(
            Outcome.FAIL,
            f"Traction is described without figures or dates: {quoted}.",
            ev(*vague),
            Severity.YELLOW,
            "Traction claims are not specific",
            "Can you share the exact numbers and time period behind these statements?",
        )
    specific = facts.all(FactKey.REVENUE_CLAIM)
    if specific:
        return Verdict(Outcome.PASS, "Traction claims include specific figures and periods.", ev(*specific))
    return unknown("No traction claims were found to assess.")


@check("traction.headcount_trend", C, "Headcount trend")
def headcount_trend(facts: FactSet, ctx: CheckContext) -> Verdict:
    points = sorted(
        (f for f in facts.all(FactKey.EMPLOYEE_COUNT) if f.value.get("as_of")),
        key=lambda f: f.value["as_of"],
    )
    if len(points) < 2:
        return unknown("Not enough dated headcount data points to see a trend.")
    first, last = points[0], points[-1]
    a, b = first.value["count"], last.value["count"]
    if a > 0 and (a - b) / a >= HEADCOUNT_DROP:
        return Verdict(
            Outcome.FAIL,
            f"Estimated headcount went from {a} ({first.value['as_of'][:7]}) to {b} ({last.value['as_of'][:7]}).",
            ev(first, last),
            Severity.YELLOW,
            "Headcount has fallen",
            "What drove the reduction in team size?",
        )
    return Verdict(
        Outcome.PASS,
        f"Estimated headcount went from {a} ({first.value['as_of'][:7]}) to {b} ({last.value['as_of'][:7]}).",
        ev(first, last),
    )


@check("traction.web_presence", C, "Website live and maintained")
def web_presence(facts: FactSet, ctx: CheckContext) -> Verdict:
    f = facts.first(FactKey.WEBSITE_STATUS)
    if f is None:
        return unknown("The company website could not be checked.")
    if not f.value.get("live"):
        return Verdict(
            Outcome.FAIL,
            "The company website did not load when checked.",
            ev(f),
            Severity.YELLOW,
            "Website not reachable",
            "Is the website down temporarily, or has the product moved?",
        )
    updated = parse_date(f.value.get("last_updated"))
    if updated and months_between(updated, ctx.today) > STALE_WEBSITE_MONTHS:
        return Verdict(
            Outcome.FAIL,
            f"The website loads but shows no updates since {updated:%b %Y}.",
            ev(f),
            Severity.YELLOW,
            "Website not recently updated",
            "Where does the company publish product updates now?",
        )
    return Verdict(Outcome.PASS, "The company website is live and recently updated.", ev(f))
