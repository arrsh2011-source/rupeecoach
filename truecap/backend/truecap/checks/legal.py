from __future__ import annotations

import re

from truecap.checks.base import CheckContext, Verdict, check, ev, parse_date, unknown
from truecap.domain import Category, FactSet, Outcome, Severity
from truecap.facts import FactKey
from truecap.validators import validate_gstin

C = Category.LEGAL
INACTIVE_STATUSES = ("strike", "striking", "struck", "dormant", "liquidat", "dissolved", "amalgamated", "inactive")
SERIOUS_CASE_TYPES = re.compile(
    r"\b(insolvency|ibc|winding[- ]up|criminal|cheque|138|fraud|sebi|enforcement directorate|gst|tax)\b", re.I
)


@check("legal.company_active", C, "Company status is Active on the registry", weight=2.0)
def company_active(facts: FactSet, ctx: CheckContext) -> Verdict:
    f = facts.first(FactKey.STATUS)
    if f is None:
        return unknown("Company status was not found on the registry.")
    status = str(f.value)
    if any(s in status.lower() for s in INACTIVE_STATUSES):
        return Verdict(
            Outcome.FAIL,
            f"Registry status is \"{status}\".",
            ev(f),
            Severity.RED,
            "Company is not Active on the registry",
            f"The registry lists the company as \"{status}\". Which entity runs the business today?",
        )
    if status.lower() == "active":
        return Verdict(Outcome.PASS, "Registry status is \"Active\".", ev(f), Severity.GREEN, "Active on the registry")
    return unknown(f"Registry status \"{status}\" could not be interpreted.")


@check("legal.director_disqualification", C, "No disqualified directors", weight=1.5)
def director_disqualification(facts: FactSet, ctx: CheckContext) -> Verdict:
    directors = [d for d in facts.all(FactKey.DIRECTOR) if d.value.get("disqualified") is not None]
    if not directors:
        return unknown("Director disqualification status was not found.")
    dq = [d for d in directors if d.value["disqualified"]]
    if dq:
        names = ", ".join(d.value["name"] for d in dq)
        return Verdict(
            Outcome.FAIL,
            f"Registry data lists the following director(s) as disqualified: {names}.",
            ev(*dq),
            Severity.RED,
            "Director listed as disqualified",
            f"What is the current status of {dq[0].value['name']}'s director disqualification?",
        )
    return Verdict(Outcome.PASS, "No current director is listed as disqualified.", ev(*directors))


@check("legal.litigation", C, "Material litigation", weight=1.5)
def litigation(facts: FactSet, ctx: CheckContext) -> Verdict:
    cases = facts.all(FactKey.LITIGATION_CASE)
    pending_against = [
        c for c in cases
        if c.value.get("status") == "pending" and c.value.get("company_role") in ("respondent", "accused")
    ]
    serious = [c for c in pending_against if SERIOUS_CASE_TYPES.search(c.value.get("case_type", ""))]
    if serious:
        c = serious[0]
        return Verdict(
            Outcome.FAIL,
            f"Court records show a pending \"{c.value['case_type']}\" matter against the company "
            f"at {c.value['forum']} (\"{c.value['title']}\").",
            ev(*serious),
            Severity.RED,
            "Pending court matter against the company",
            f"What is the status of the \"{c.value['case_type']}\" matter at {c.value['forum']}?",
        )
    if pending_against:
        c = pending_against[0]
        return Verdict(
            Outcome.FAIL,
            f"Court records show {len(pending_against)} pending matter(s) against the company, "
            f"e.g. a \"{c.value['case_type']}\" matter at {c.value['forum']}.",
            ev(*pending_against),
            Severity.YELLOW,
            "Pending court matter(s)",
            "Can you summarise the pending court matters and their expected impact?",
        )
    searched = facts.first(FactKey.LITIGATION_SEARCH_DONE)
    if searched is not None:
        return Verdict(Outcome.PASS, "No pending matters against the company were found.", ev(searched, *cases))
    # Web search finding nothing is weak evidence; only an official search can pass this check.
    return unknown("No official court-records search was available; court records should be checked manually.")


@check("legal.gst_registration", C, "GST registration valid")
def gst_registration(facts: FactSet, ctx: CheckContext) -> Verdict:
    f = facts.first(FactKey.GSTIN)
    if f is None:
        return unknown("No GSTIN was found in public sources.")
    ok, reason = validate_gstin(str(f.value))
    if not ok:
        return Verdict(
            Outcome.FAIL,
            f"The GSTIN shown publicly ({f.value}) {reason}.",
            ev(f),
            Severity.RED,
            "Published GSTIN is not valid",
            "Can you confirm the company's correct GSTIN?",
        )
    status = facts.first(FactKey.GST_STATUS)
    if status is not None and str(status.value).lower() != "active":
        return Verdict(
            Outcome.FAIL,
            f"GST registration {f.value} has status \"{status.value}\".",
            ev(f, status),
            Severity.RED,
            "GST registration not active",
            "Why is the GST registration not active?",
        )
    if status is not None:
        return Verdict(Outcome.PASS, f"GSTIN {f.value} is valid and Active.", ev(f, status))
    # Format is valid but live status needs the GST portal (CAPTCHA), so we can't pass yet.
    return unknown(f"GSTIN {f.value} is correctly formed; live status should be checked on the GST portal.")


@check("legal.trademark", C, "Brand name trademark")
def trademark(facts: FactSet, ctx: CheckContext) -> Verdict:
    marks = facts.all(FactKey.TRADEMARK)
    if not marks:
        return unknown("No trademark record for the brand name was found.")
    problem = [
        m for m in marks
        if not m.value.get("owner_matches_company") or m.value["status"] in ("opposed", "refused", "abandoned")
    ]
    if problem:
        m = problem[0]
        owner = "another party" if not m.value.get("owner_matches_company") else "the company"
        return Verdict(
            Outcome.FAIL,
            f"The mark \"{m.value['mark']}\" is held by {owner} with status \"{m.value['status']}\".",
            ev(*problem),
            Severity.YELLOW,
            "Brand trademark not secured",
            f"What is the plan for securing the \"{m.value['mark']}\" trademark?",
        )
    return Verdict(
        Outcome.PASS,
        f"The company holds the \"{marks[0].value['mark']}\" mark ({marks[0].value['status']}).",
        ev(*marks),
    )


@check("legal.incorporation_claim", C, "Founding date claim matches incorporation date")
def incorporation_claim(facts: FactSet, ctx: CheckContext) -> Verdict:
    inc = facts.first(FactKey.INCORPORATION_DATE)
    claim = facts.first(FactKey.CLAIMED_FOUNDING_YEAR)
    if inc is None or claim is None:
        return unknown("A founding-year claim and an incorporation date were not both available.")
    inc_year = parse_date(inc.value).year
    claimed = int(claim.value)
    if claimed < inc_year - 1:  # one year of pre-incorporation work is normal
        return Verdict(
            Outcome.FAIL,
            f"Company materials state it was founded in {claimed}; the registry shows incorporation in {inc_year}.",
            ev(claim, inc),
            Severity.YELLOW,
            "Founding year differs from incorporation date",
            f"Was the business run through a different entity between {claimed} and {inc_year}?",
        )
    return Verdict(
        Outcome.PASS,
        f"Claimed founding year {claimed} is consistent with incorporation in {inc_year}.",
        ev(claim, inc),
    )
