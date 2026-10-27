from __future__ import annotations

from truecap.checks.base import CheckContext, Verdict, check, ev, months_between, parse_date, unknown
from truecap.domain import Category, FactSet, Outcome, Severity
from truecap.facts import FactKey

C = Category.TEAM
TURNOVER_WINDOW_MONTHS = 24
TURNOVER_THRESHOLD = 2
BUSY_DIRECTOR_THRESHOLD = 5


@check("team.founders_identified", C, "Founders and directors identified")
def founders_identified(facts: FactSet, ctx: CheckContext) -> Verdict:
    people = facts.all(FactKey.FOUNDER) + facts.all(FactKey.DIRECTOR)
    if not people:
        return unknown("No founder or director names were found in public sources.")
    names = sorted({p.value["name"] for p in people})
    return Verdict(Outcome.PASS, f"Identified: {', '.join(names)}.", ev(*people))


@check("team.background_claims", C, "Founder background claims corroborated", weight=1.5)
def background_claims(facts: FactSet, ctx: CheckContext) -> Verdict:
    claims = facts.all(FactKey.FOUNDER_CLAIM)
    checked = [c for c in claims if c.value["status"] != "unverified"]
    if not checked:
        return unknown("No founder background claims could be checked against an independent source.")
    contradicted = [c for c in checked if c.value["status"] == "contradicted"]
    if contradicted:
        c = contradicted[0]
        finding = c.value.get("finding") or "the independent source shows something different"
        return Verdict(
            Outcome.FAIL,
            f"{c.value['name']}'s profile states \"{c.value['claim']}\"; {finding}.",
            ev(*contradicted),
            Severity.RED,
            "Founder claim differs from independent source",
            f"Can you share documentation for \"{c.value['claim']}\"?",
        )
    return Verdict(
        Outcome.PASS,
        f"{len(checked)} founder background claim(s) match independent sources.",
        ev(*checked),
        Severity.GREEN,
        "Founder background corroborated",
    )


@check("team.relevant_experience", C, "Founders have prior startup or domain experience")
def relevant_experience(facts: FactSet, ctx: CheckContext) -> Verdict:
    exp = facts.all(FactKey.FOUNDER_EXPERIENCE)
    if not exp:
        return unknown("Founder work history was not found in public sources.")
    repeat = [e for e in exp if e.value.get("prior_startups", 0) > 0]
    if repeat:
        names = ", ".join(e.value["name"] for e in repeat)
        return Verdict(
            Outcome.PASS,
            f"Repeat founder(s): {names}.",
            ev(*repeat),
            Severity.GREEN,
            "Repeat founder",
        )
    domain = [e for e in exp if (e.value.get("domain_years") or 0) >= 3]
    if domain:
        return Verdict(Outcome.PASS, "At least one founder has 3+ years in this domain.", ev(*domain))
    return Verdict(
        Outcome.FAIL,
        "Public profiles show no prior startups and under 3 years of domain experience for the founders.",
        ev(*exp),
        Severity.YELLOW,
        "Limited prior domain experience",
        "What experience in this sector does the founding team bring, beyond what is on public profiles?",
    )


@check("team.founder_turnover", C, "Founder / director turnover")
def founder_turnover(facts: FactSet, ctx: CheckContext) -> Verdict:
    directors = facts.all(FactKey.DIRECTOR)
    if not directors:
        return unknown("Director appointment history was not found.")
    recent_exits = []
    for d in directors:
        ceased = parse_date(d.value.get("ceased_on"))
        if ceased and months_between(ceased, ctx.today) <= TURNOVER_WINDOW_MONTHS:
            recent_exits.append(d)
    if len(recent_exits) >= TURNOVER_THRESHOLD:
        names = ", ".join(d.value["name"] for d in recent_exits)
        return Verdict(
            Outcome.FAIL,
            f"{len(recent_exits)} directors left in the last {TURNOVER_WINDOW_MONTHS} months ({names}).",
            ev(*recent_exits),
            Severity.YELLOW,
            "High director turnover",
            "Why did these directors step down, and are they still shareholders?",
        )
    return Verdict(
        Outcome.PASS,
        f"{len(recent_exits)} director exit(s) in the last {TURNOVER_WINDOW_MONTHS} months.",
        ev(*directors),
    )


@check("team.director_commitment", C, "Directors' other active directorships")
def director_commitment(facts: FactSet, ctx: CheckContext) -> Verdict:
    directors = [d for d in facts.all(FactKey.DIRECTOR) if d.value.get("other_active_directorships") is not None]
    if not directors:
        return unknown("Other directorships of the directors were not found.")
    busy = [d for d in directors if d.value["other_active_directorships"] >= BUSY_DIRECTOR_THRESHOLD]
    if busy:
        d = busy[0]
        return Verdict(
            Outcome.FAIL,
            f"{d.value['name']} is a director in {d.value['other_active_directorships']} other active companies.",
            ev(*busy),
            Severity.YELLOW,
            "Director holds many other directorships",
            f"How much of {d.value['name']}'s time goes to this company?",
        )
    return Verdict(Outcome.PASS, "No director holds 5 or more other active directorships.", ev(*directors))
