"""Web research with Claude's web search tool. Every cited snippet becomes a ledger entry.

Only `cited_text` (verbatim text from the source) counts as source text later on; the
model's own sentences are kept as the entry's claim for readability, never as proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from truecap.domain import Ledger, utcnow
from truecap.research.classify import classify, domain_of
from truecap.research.llm import LLM, Finding, Usage
from truecap.validators import validate_cin

SYSTEM = """You research Indian startups for a private claim-verification report used by angel investors.
Rules:
- Use web search. State only what sources say, and cite every sentence.
- Neutral, factual wording. No opinions, predictions, advice or characterisations of anyone's conduct.
- Prefer independent sources (news, company-data sites quoting MCA filings, court records) over the company's own pages and press releases.
- Public pages only. Do not use content that needs a login.
- If something is not found, write "<TAG> Not found." with no citation. Never guess.
- Write each finding as a separate short paragraph that starts with its tag in square brackets."""

TOPICS = """Research these topics and tag each paragraph:
[WEBSITE] The company's official website URL.
[FOUNDERS] Founders and key people: names, roles, education and past employers, earlier startups or exits.
[DIRECTORS] Directors with DINs, appointment and cessation dates, as shown on company-data sites.
[FUNDING] Funding rounds: round name, date, amount, investors.
[FINANCIALS] Revenue and profit figures, saying for each whether it comes from MCA/RoC filings or from the company. Employee counts with dates.
[CLAIMS] Specific claims the company makes about itself: founding year, revenue, users, customers, market size.
[LEGAL] Court cases, NCLT/insolvency matters, regulatory actions, trademark disputes involving the company.
[MARKET] Direct competitors and how much each has raised. Any licence the business needs (e.g. RBI, SEBI, IRDAI, FSSAI) and whether the company holds it.
[COVERAGE] Independent media coverage, with outlet and date."""


@dataclass
class ResearchEvidence:
    ledger: Ledger
    source_text: dict[str, str] = field(default_factory=dict)  # evidence id -> verbatim source text
    uncited: list[str] = field(default_factory=list)
    website: str | None = None


def describe_company(name: str, cin: str | None, city: str | None, website: str | None, known: dict[str, str]) -> str:
    lines = [f"Company: {name}"]
    if cin:
        lines.append(f"CIN: {cin}")
    if city:
        lines.append(f"City: {city}")
    if website:
        lines.append(f"Website: {website}")
    lines += [f"{k}: {v}" for k, v in known.items()]
    return "\n".join(lines)


_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+", re.I)


def findings_to_evidence(findings: list[Finding], ledger: Ledger, company_domain: str | None) -> ResearchEvidence:
    out = ResearchEvidence(ledger=ledger)
    seen: dict[tuple[str, str], str] = {}
    for f in findings:
        if f.text.startswith("[WEBSITE]") and not out.website:
            m = _URL_RE.search(f.text)
            out.website = m.group(0).rstrip(".,") if m else None
        if not f.citations:
            if "not found" not in f.text.lower() and len(f.text) > 20:
                out.uncited.append(f.text)
            continue
        for c in f.citations:
            key = (c.url, c.cited_text.strip())
            if key in seen:
                continue
            stype, rel = classify(c.url, company_domain)
            e = ledger.add(f.text[:600], stype, url=c.url, title=c.title, excerpt=c.cited_text.strip()[:1500],
                           reliability=rel, fetched_at=utcnow())
            seen[key] = e.id
            out.source_text[e.id] = c.cited_text
    return out


def run_web_research(llm: LLM, company: str, max_searches: int) -> tuple[list[Finding], Usage]:
    return llm.web_research(SYSTEM, f"{company}\n\n{TOPICS}", max_searches)


# --- company resolution ---------------------------------------------------------

RESOLVE_SYSTEM = """You identify Indian companies registered with the MCA. Use web search on company-data sites.
List every distinct registered company that could match, one per line, exactly in this format:
CANDIDATE | <registered name> | <21-character CIN> | <city or state>
Only list companies whose CIN you saw in a source. If none, write: CANDIDATE | none"""

_CAND_RE = re.compile(r"CANDIDATE\s*\|\s*([^|\n]+?)\s*\|\s*([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\s*\|\s*([^\n]*)", re.I)


@dataclass
class WebCandidate:
    name: str
    cin: str
    place: str


def resolve_via_web(llm: LLM, name: str, city: str | None, website: str | None) -> tuple[list[WebCandidate], Usage]:
    prompt = f"Find the registered company (or companies) matching: {name}"
    if city:
        prompt += f", based in {city}"
    if website:
        prompt += f", website {website}"
    findings, usage = llm.web_research(RESOLVE_SYSTEM, prompt, max_searches=2)
    found: dict[str, WebCandidate] = {}
    for f in findings:
        for m in _CAND_RE.finditer(f.text):
            cin = m.group(2).upper()
            if validate_cin(cin):
                found.setdefault(cin, WebCandidate(m.group(1).strip(), cin, m.group(3).strip()))
    return list(found.values()), usage


def site_domain(url: str | None) -> str | None:
    d = domain_of(url)
    return d.removeprefix("www.") if d else None
