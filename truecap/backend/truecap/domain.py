"""Core domain types shared by the pipeline, scoring engine and report builder.

Everything a report says must trace back to an `Evidence` entry in the `Ledger`.
Facts reference evidence by id; checks reference facts' evidence; flags, pros and
cons reference the evidence of the checks that produced them.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Iterable
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class Category(StrEnum):
    TEAM = "team"
    MARKET = "market"
    TRACTION = "traction"
    FINANCIALS = "financials"
    LEGAL = "legal"


class Stage(StrEnum):
    PRE_SEED = "pre_seed"
    SEED = "seed"
    SERIES_A = "series_a"
    GROWTH = "growth"  # Series B and later


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    RED = "red"  # checkable problem
    YELLOW = "yellow"  # something to ask about
    GREEN = "green"  # verified strength


class Reliability(StrEnum):
    """How much a source can be trusted to verify a fact on its own."""

    OFFICIAL = "official"  # government registry / court / IP office data
    SECONDARY = "secondary"  # independent: news, reputable databases, profiles
    SELF_REPORTED = "self_reported"  # company website, deck, founder's own claims


class SourceType(StrEnum):
    MCA = "mca"
    GST = "gst"
    IP_INDIA = "ip_india"
    COURT = "court"
    COMPANY_WEBSITE = "company_website"
    NEWS = "news"
    WEB_SEARCH = "web_search"
    FOUNDER_PROFILE = "founder_profile"
    AGGREGATOR = "aggregator"
    FOUNDER_REPLY = "founder_reply"
    COMPUTED = "computed"  # derived locally, e.g. a checksum validation


DEFAULT_RELIABILITY: dict[SourceType, Reliability] = {
    SourceType.MCA: Reliability.OFFICIAL,
    SourceType.GST: Reliability.OFFICIAL,
    SourceType.IP_INDIA: Reliability.OFFICIAL,
    SourceType.COURT: Reliability.OFFICIAL,
    SourceType.COMPANY_WEBSITE: Reliability.SELF_REPORTED,
    SourceType.NEWS: Reliability.SECONDARY,
    SourceType.WEB_SEARCH: Reliability.SECONDARY,
    SourceType.FOUNDER_PROFILE: Reliability.SECONDARY,
    SourceType.AGGREGATOR: Reliability.SECONDARY,
    SourceType.FOUNDER_REPLY: Reliability.SELF_REPORTED,
    SourceType.COMPUTED: Reliability.OFFICIAL,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    """One row of the evidence ledger: a claim, where it came from and when."""

    id: str
    claim: str
    source_type: SourceType
    url: str | None = None
    title: str | None = None
    excerpt: str | None = None  # quoted text that supports the claim
    fetched_at: datetime = Field(default_factory=utcnow)
    published_on: date | None = None
    reliability: Reliability | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.reliability is None:
            self.reliability = DEFAULT_RELIABILITY[self.source_type]

    @property
    def domain(self) -> str | None:
        if not self.url:
            return None
        host = urlparse(self.url).netloc.lower()
        return host.removeprefix("www.") or None


class Ledger:
    """Append-only store of evidence for one report. Ids are stable (E1, E2, ...)."""

    def __init__(self, entries: Iterable[Evidence] = ()) -> None:
        self._entries: dict[str, Evidence] = {}
        for entry in entries:
            self.add_entry(entry)

    def add(self, claim: str, source_type: SourceType, **kwargs: Any) -> Evidence:
        entry = Evidence(id=f"E{len(self._entries) + 1}", claim=claim, source_type=source_type, **kwargs)
        return self.add_entry(entry)

    def add_entry(self, entry: Evidence) -> Evidence:
        if entry.id in self._entries:
            raise ValueError(f"duplicate evidence id {entry.id}")
        self._entries[entry.id] = entry
        return entry

    def get(self, evidence_id: str) -> Evidence:
        return self._entries[evidence_id]

    def __contains__(self, evidence_id: object) -> bool:
        return evidence_id in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def ids(self) -> set[str]:
        return set(self._entries)


class Fact(BaseModel):
    """A structured fact extracted from one or more evidence entries.

    `key` is a dotted name from `truecap.facts.FactKey`. `value` is JSON-like.
    A fact with no evidence is never accepted (see `FactSet.add`).
    """

    key: str
    value: Any
    evidence_ids: list[str]
    subject: str | None = None  # e.g. a founder's name for per-person facts


class FactSet:
    """All facts known about one company, indexed by key."""

    def __init__(self, ledger: Ledger, facts: Iterable[Fact] = ()) -> None:
        self.ledger = ledger
        self._by_key: dict[str, list[Fact]] = defaultdict(list)
        for fact in facts:
            self.add(fact)

    def add(self, fact: Fact) -> Fact:
        if not fact.evidence_ids:
            raise ValueError(f"fact {fact.key!r} has no evidence")
        missing = [e for e in fact.evidence_ids if e not in self.ledger]
        if missing:
            raise ValueError(f"fact {fact.key!r} cites unknown evidence {missing}")
        self._by_key[fact.key].append(fact)
        return fact

    def put(self, key: str, value: Any, *evidence_ids: str, subject: str | None = None) -> Fact:
        return self.add(Fact(key=key, value=value, evidence_ids=list(evidence_ids), subject=subject))

    def all(self, key: str) -> list[Fact]:
        return list(self._by_key.get(key, []))

    def first(self, key: str) -> Fact | None:
        """Most reliable fact for a key (official beats secondary beats self-reported)."""
        facts = self.all(key)
        if not facts:
            return None
        return min(facts, key=lambda f: _reliability_rank(self.best_reliability(f)))

    def value(self, key: str, default: Any = None) -> Any:
        fact = self.first(key)
        return default if fact is None else fact.value

    def has(self, key: str) -> bool:
        return bool(self._by_key.get(key))

    def keys(self) -> set[str]:
        return {k for k, v in self._by_key.items() if v}

    def best_reliability(self, fact: Fact) -> Reliability:
        return min(
            (self.ledger.get(e).reliability for e in fact.evidence_ids),
            key=_reliability_rank,
        )

    def is_verified(self, fact: Fact) -> bool:
        """Verified = backed by an official source, or by 2+ independent secondary domains."""
        entries = [self.ledger.get(e) for e in fact.evidence_ids]
        if any(e.reliability == Reliability.OFFICIAL for e in entries):
            return True
        domains = {e.domain or e.id for e in entries if e.reliability == Reliability.SECONDARY}
        return len(domains) >= 2


_RANK = {Reliability.OFFICIAL: 0, Reliability.SECONDARY: 1, Reliability.SELF_REPORTED: 2}


def _reliability_rank(r: Reliability) -> int:
    return _RANK[r]


class Flag(BaseModel):
    severity: Severity
    title: str
    detail: str  # neutral, factual wording
    question: str | None = None  # suggested question for the founder
    evidence_ids: list[str]
    check_id: str
    category: Category


class CheckResult(BaseModel):
    check_id: str
    category: Category
    title: str
    outcome: Outcome
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)
    weight: float = 1.0
    flag: Flag | None = None
