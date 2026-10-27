"""Fundamentals table: each field is verified, unverified or not found."""

from __future__ import annotations

from truecap.checks.base import ev, inr
from truecap.domain import Fact, FactSet
from truecap.facts import FactKey, fy_label
from truecap.report.models import FieldStatus, FundamentalField


def _status(facts: FactSet, items: list[Fact]) -> FieldStatus:
    if not items:
        return FieldStatus.NOT_FOUND
    return FieldStatus.VERIFIED if all(facts.is_verified(f) for f in items) else FieldStatus.UNVERIFIED


def _field(facts: FactSet, key: str, label: str, items: list[Fact], value: str | None) -> FundamentalField:
    return FundamentalField(
        key=key,
        label=label,
        value=value if items else None,
        status=_status(facts, items),
        evidence_ids=ev(*items),
    )


def _single(facts: FactSet, key: str, label: str, fmt=str) -> FundamentalField:
    f = facts.first(key)
    items = [f] if f else []
    return _field(facts, key, label, items, fmt(f.value) if f else None)


def build_fundamentals(facts: FactSet) -> list[FundamentalField]:
    out = [
        _single(facts, FactKey.CIN, "CIN"),
        _single(facts, FactKey.STATUS, "Registry status"),
        _single(facts, FactKey.INCORPORATION_DATE, "Incorporation date"),
        _single(facts, FactKey.COMPANY_TYPE, "Company type"),
        _single(facts, FactKey.REGISTERED_OFFICE, "Registered office"),
        _single(facts, FactKey.PAID_UP_CAPITAL, "Paid-up capital", lambda v: inr(float(v))),
    ]

    directors = [d for d in facts.all(FactKey.DIRECTOR) if not d.value.get("ceased_on")]
    out.append(
        _field(
            facts, FactKey.DIRECTOR, "Current directors", directors,
            ", ".join(d.value["name"] + (f" (DIN {d.value['din']})" if d.value.get("din") else "") for d in directors),
        )
    )

    rounds = facts.all(FactKey.FUNDING_ROUND)

    def round_text(r: Fact) -> str:
        v = r.value
        parts = [v["round"]]
        if v.get("date"):
            parts.append(v["date"][:7])
        if v.get("amount_usd"):
            parts.append(f"${v['amount_usd'] / 1e6:,.1f}M")
        if v.get("investors"):
            parts.append("led/joined by " + ", ".join(v["investors"]))
        return " · ".join(parts)

    out.append(_field(facts, FactKey.FUNDING_ROUND, "Funding rounds & investors", rounds,
                      "; ".join(round_text(r) for r in rounds)))

    counts = sorted(facts.all(FactKey.EMPLOYEE_COUNT), key=lambda f: f.value.get("as_of") or "")
    headcount = None
    if counts:
        latest = counts[-1].value
        headcount = f"~{latest['count']}" + (f" as of {latest['as_of'][:7]}" if latest.get("as_of") else "")
    out.append(_field(facts, FactKey.EMPLOYEE_COUNT, "Employees (estimate)", counts[-1:], headcount))

    filed = sorted(facts.all(FactKey.REVENUE_FILED), key=lambda f: fy_label(f.value["fy"]))
    revenue = None
    if filed:
        latest = filed[-1].value
        revenue = f"{inr(latest['amount_inr'])} ({fy_label(latest['fy'])})"
    out.append(_field(facts, FactKey.REVENUE_FILED, "Revenue (filed)", filed[-1:], revenue))

    web = facts.all(FactKey.WEBSITE) + facts.all(FactKey.SOCIAL_PROFILE)
    web_parts = [str(f.value) for f in facts.all(FactKey.WEBSITE)]
    web_parts += [f.value["platform"] for f in facts.all(FactKey.SOCIAL_PROFILE)]
    out.append(_field(facts, "presence", "Website & social", web, ", ".join(web_parts)))
    return out
