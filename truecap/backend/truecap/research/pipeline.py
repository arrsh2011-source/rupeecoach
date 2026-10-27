"""Research pipeline: resolve -> registry -> web research -> website -> extract -> check/score -> write.

Each step reports progress. Failures in one source never stop the report; the checks
that needed that source simply stay UNKNOWN, which lowers confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from truecap.checks import CheckContext, run_all
from truecap.domain import FactSet, Ledger, Reliability, SourceType, Stage, utcnow
from truecap.facts import FactKey as K
from truecap.report import NarrativeDraft, Report, build_report
from truecap.research import extract, narrate
from truecap.research.budget import Budget
from truecap.research.llm import LLM, LLMError
from truecap.research.sources.registry import RegistryClient, RegistryRecord, add_registry_facts
from truecap.research.sources.website import WebsiteFetcher, find_gstins, normalise_site
from truecap.research.web_research import (
    describe_company, findings_to_evidence, resolve_via_web, run_web_research, site_domain,
)

log = logging.getLogger(__name__)
Progress = Callable[[str, int, str], None]


@dataclass
class ResearchQuery:
    name: str
    city: str | None = None
    website: str | None = None
    cin: str | None = None
    stage_override: Stage | None = None


@dataclass
class Candidate:
    name: str
    cin: str
    place: str | None
    status: str | None = None
    source: str = "registry"


class NeedsPick(Exception):
    """Several companies match; the user must choose one (then re-run with its CIN)."""

    def __init__(self, candidates: list[Candidate]) -> None:
        super().__init__(f"{len(candidates)} companies match")
        self.candidates = candidates


class NotFound(Exception):
    pass


@dataclass
class Deps:
    llm: LLM | None
    registry: RegistryClient
    website: WebsiteFetcher
    budget: Budget
    extraction_model: str
    writing_model: str
    max_web_searches: int = 8
    narrative_enabled: bool = True
    established_investors: frozenset[str] = frozenset()
    today: Callable[[], date] = date.today


@dataclass
class ResearchOutcome:
    company_name: str
    cin: str | None
    facts: FactSet
    narrative: NarrativeDraft
    report: Report
    log: list[str] = field(default_factory=list)
    cost_inr: float = 0.0


def _noop(step: str, pct: int, msg: str) -> None:
    pass


def _matches_city(rec: RegistryRecord, city: str | None) -> bool:
    if not city:
        return True
    hay = " ".join(str(rec.get(f) or "") for f in ("address", "state", "roc")).lower()
    return city.lower() in hay


def resolve(q: ResearchQuery, deps: Deps, notes: list[str]) -> RegistryRecord | Candidate | None:
    """Return a registry record, a web-only candidate, or None when nothing could be identified."""
    if q.cin:
        rec = deps.registry.by_cin(q.cin)
        if rec:
            return rec
        notes.append(f"CIN {q.cin} was not found in the configured registry datasets.")
        return Candidate(name=q.name, cin=q.cin.upper(), place=q.city, source="user")

    records = [r for r in deps.registry.search(q.name) if _matches_city(r, q.city)]
    if len(records) == 1:
        return records[0]
    if len(records) > 1:
        raise NeedsPick([Candidate(r.name, r.cin, r.state, r.status) for r in records])

    if deps.llm is None:
        return None
    deps.budget.ensure_room()
    try:
        web, usage = resolve_via_web(deps.llm, q.name, q.city, q.website)
    except LLMError as e:
        notes.append(f"Company lookup by web search failed: {e}")
        return None
    deps.budget.record(usage)
    if len(web) > 1:
        raise NeedsPick([Candidate(c.name, c.cin, c.place, source="web") for c in web])
    if len(web) == 1:
        rec = deps.registry.by_cin(web[0].cin)
        return rec or Candidate(web[0].name, web[0].cin, web[0].place, source="web")
    return None


def research(q: ResearchQuery, deps: Deps, progress: Progress = _noop) -> ResearchOutcome:
    notes: list[str] = []
    ledger = Ledger()
    facts = FactSet(ledger)

    progress("resolve", 5, "Identifying the company")
    found = resolve(q, deps, notes)
    if found is None and deps.llm is None and not deps.registry.enabled:
        raise NotFound("No data sources are configured. Add an Anthropic key and/or a data.gov.in key.")

    name, cin = q.name, q.cin
    progress("registry", 15, "Reading MCA company master data")
    if isinstance(found, RegistryRecord):
        add_registry_facts(found, ledger, facts)
        name, cin = found.name, found.cin
    elif isinstance(found, Candidate):
        name, cin = found.name, found.cin
        notes.append("Registry data was not available, so registry checks rely on web sources only.")
    else:
        notes.append("The company could not be matched to an MCA record.")

    website = q.website
    source_text: dict[str, str] = {}
    if deps.llm is not None:
        progress("web", 30, "Searching news, filings coverage, founders and court records")
        deps.budget.ensure_room()
        known = {"Registry status": str(facts.value(K.STATUS) or "unknown"),
                 "Incorporated": str(facts.value(K.INCORPORATION_DATE) or "unknown")}
        try:
            findings, usage = run_web_research(deps.llm, describe_company(name, cin, q.city, website, known),
                                               deps.max_web_searches)
            deps.budget.record(usage)
            res = findings_to_evidence(findings, ledger, site_domain(website))
            source_text.update(res.source_text)
            website = website or res.website
            if res.uncited:
                notes.append(f"Removed {len(res.uncited)} research statement(s) that cited no source.")
        except LLMError as e:
            notes.append(f"Web research failed: {e}")

    if website:
        website = normalise_site(website)
        # Search results from the company's own domain are self-reported, whenever the domain became known.
        own = site_domain(website)
        for ev in ledger:
            if ev.domain and (ev.domain == own or ev.domain.endswith("." + own)):
                ev.source_type, ev.reliability = SourceType.COMPANY_WEBSITE, Reliability.SELF_REPORTED
        progress("website", 50, f"Reading {own}")
        site = deps.website.fetch_site(website)
        check = ledger.add(f"Website check on {utcnow():%d %b %Y}: "
                           + ("homepage loaded" if site.live else "homepage did not load"),
                           SourceType.COMPUTED, url=normalise_site(website))
        last = max((p.last_modified for p in site.pages if p.last_modified), default=None)
        facts.put(K.WEBSITE_STATUS, {"live": site.live, "last_updated": last.date().isoformat() if last else None},
                  check.id)
        if site.error:
            notes.append(f"Website: {site.error}.")
        for page in site.pages:
            e = ledger.add(f"Company website page: {page.title or page.url}", SourceType.COMPANY_WEBSITE,
                           url=page.url, title=page.title)
            source_text[e.id] = page.text
            if page is site.pages[0]:
                facts.put(K.WEBSITE, normalise_site(page.url), e.id)
            for g in find_gstins(page.text):
                if not facts.has(K.GSTIN):
                    facts.put(K.GSTIN, g, e.id, quote=g)
                    e.excerpt = f"GSTIN {g}"

    if deps.llm is not None and source_text:
        progress("extract", 65, "Extracting facts and verifying quotes")
        rows = [(eid, ledger.get(eid).source_type.value, ledger.get(eid).reliability.value, ledger.get(eid).url,
                 text[:8000]) for eid, text in source_text.items()]
        deps.budget.ensure_room(5)
        try:
            ext, usage = deps.llm.structured(extract.SYSTEM, extract.build_prompt(name, rows), extract.Extraction,
                                             deps.extraction_model)
            deps.budget.record(usage)
            notes += extract.apply_extraction(ext, facts, source_text)
        except LLMError as e:
            notes.append(f"Fact extraction failed: {e}")

    progress("score", 80, "Running checks and scoring")
    ctx = CheckContext(today=deps.today(), reputable_investors=deps.established_investors)
    narrative = NarrativeDraft()
    if deps.llm is not None and deps.narrative_enabled:
        progress("write", 90, "Writing pros and cons")
        try:
            deps.budget.ensure_room(3)
            out, usage = deps.llm.structured(narrate.SYSTEM, narrate.build_prompt(name, run_all(facts, ctx), facts),
                                             narrate.NarrativeOut, deps.writing_model)
            deps.budget.record(usage)
            narrative = narrate.to_draft(out)
        except LLMError as e:
            notes.append(f"Narrative writing failed; using standard wording: {e}")

    report = build_report(name, facts, ctx, stage_override=q.stage_override, narrative=narrative)
    report.guard_log = notes + report.guard_log
    progress("done", 100, "Report ready")
    return ResearchOutcome(company_name=name, cin=cin, facts=facts, narrative=narrative, report=report,
                           log=report.guard_log, cost_inr=round(deps.budget.run_cost_inr(), 2))
