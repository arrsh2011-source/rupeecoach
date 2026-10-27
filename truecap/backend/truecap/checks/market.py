from __future__ import annotations

from truecap.checks.base import CheckContext, Verdict, check, ev, months_between, parse_date, unknown
from truecap.domain import Category, FactSet, Outcome, Severity
from truecap.facts import FactKey

C = Category.MARKET
COVERAGE_WINDOW_MONTHS = 18
WELL_FUNDED_USD = 10_000_000
CROWDED_THRESHOLD = 4


@check("market.size_claim_sourced", C, "Market size claim cites a third-party source")
def size_claim_sourced(facts: FactSet, ctx: CheckContext) -> Verdict:
    claims = facts.all(FactKey.MARKET_SIZE_CLAIM)
    if not claims:
        return unknown("No market size claim was found.")
    unsourced = [c for c in claims if not c.value.get("third_party_source")]
    if unsourced:
        c = unsourced[0]
        return Verdict(
            Outcome.FAIL,
            f"The company states \"{c.value['text']}\" without citing a source.",
            ev(*unsourced),
            Severity.YELLOW,
            "Market size claim has no cited source",
            "Which report or calculation is the market size figure based on?",
        )
    return Verdict(Outcome.PASS, "Market size claims cite third-party research.", ev(*claims))


@check("market.independent_coverage", C, "Recent independent media coverage")
def independent_coverage(facts: FactSet, ctx: CheckContext) -> Verdict:
    items = facts.all(FactKey.INDEPENDENT_COVERAGE)
    if not items:
        return unknown("No independent media coverage was found.")
    recent = [
        i for i in items
        if (d := parse_date(i.value.get("date"))) and months_between(d, ctx.today) <= COVERAGE_WINDOW_MONTHS
    ]
    if recent:
        outlets = ", ".join(sorted({i.value["outlet"] for i in recent}))
        return Verdict(Outcome.PASS, f"Covered in the last {COVERAGE_WINDOW_MONTHS} months by {outlets}.", ev(*recent))
    return Verdict(
        Outcome.FAIL,
        f"The most recent independent coverage found is older than {COVERAGE_WINDOW_MONTHS} months.",
        ev(*items),
        Severity.YELLOW,
        "No recent independent coverage",
        "What has changed in the business since the last press coverage?",
    )


@check("market.competitive_density", C, "Well-funded direct competitors")
def competitive_density(facts: FactSet, ctx: CheckContext) -> Verdict:
    comps = facts.all(FactKey.COMPETITOR)
    if not comps:
        return unknown("No direct competitors were identified.")
    funded = [c for c in comps if (c.value.get("funding_usd") or 0) >= WELL_FUNDED_USD]
    if len(funded) >= CROWDED_THRESHOLD:
        names = ", ".join(c.value["name"] for c in funded[:5])
        return Verdict(
            Outcome.FAIL,
            f"{len(funded)} direct competitors have each raised $10M or more ({names}).",
            ev(*funded),
            Severity.YELLOW,
            "Several well-funded competitors",
            f"What does the company do that {funded[0].value['name']} cannot easily copy?",
        )
    return Verdict(
        Outcome.PASS,
        f"{len(funded)} of {len(comps)} identified competitors have raised $10M or more.",
        ev(*comps),
    )


@check("market.regulatory_license", C, "Required regulatory licence held")
def regulatory_license(facts: FactSet, ctx: CheckContext) -> Verdict:
    req = facts.first(FactKey.LICENSE_REQUIRED)
    if req is None:
        return unknown("Whether this business needs a regulatory licence was not determined.")
    if req.value is None:
        return Verdict(Outcome.PASS, "No sector-specific licence appears to be required.", ev(req))
    held = [
        h for h in facts.all(FactKey.LICENSE_HELD)
        if h.value.get("regulator", "").lower() == req.value["regulator"].lower()
    ]
    if held:
        return Verdict(
            Outcome.PASS,
            f"{req.value['license']} from {req.value['regulator']} found on record.",
            ev(req, *held),
            Severity.GREEN,
            "Regulatory licence on record",
        )
    return Verdict(
        Outcome.FAIL,
        f"The business model typically needs a {req.value['license']} from {req.value['regulator']}; "
        "no such licence was found in public records.",
        ev(req),
        Severity.YELLOW,
        "Regulatory licence not found",
        f"Does the company hold a {req.value['license']}, or operate through a licensed partner?",
    )
