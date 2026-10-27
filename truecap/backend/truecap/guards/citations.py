"""Anti-hallucination guard.

Every statement shown in a report must cite at least one evidence id that exists in
the ledger. LLM-written prose marks citations inline as [E12]; sentences without a
valid marker are removed. Numbers in an LLM sentence must also appear in the text
of the evidence it cites, otherwise the sentence is removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from truecap.domain import Ledger

CITATION_RE = re.compile(r"\[(E\d+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“₹\d])")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Dropped:
    text: str
    reason: str


@dataclass
class GuardResult:
    kept: list = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)


def validate_ids(evidence_ids: list[str], ledger: Ledger) -> str | None:
    """Return a reason string if the ids are not a valid citation, else None."""
    if not evidence_ids:
        return "no source cited"
    missing = [e for e in evidence_ids if e not in ledger]
    if missing:
        return f"cites unknown evidence {', '.join(missing)}"
    return None


def enforce_citations(items: list, ledger: Ledger, text_attr: str = "text") -> GuardResult:
    """Filter structured items that carry `evidence_ids`; drop those without valid sources."""
    result = GuardResult()
    for item in items:
        reason = validate_ids(list(getattr(item, "evidence_ids", []) or []), ledger)
        if reason:
            result.dropped.append(Dropped(getattr(item, text_attr, str(item)), reason))
        else:
            result.kept.append(item)
    return result


def _normalise_number(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _numbers(text: str) -> set[str]:
    return {_normalise_number(n) for n in _NUMBER_RE.findall(CITATION_RE.sub("", text))}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def strip_uncited_sentences(text: str, ledger: Ledger, check_numbers: bool = True) -> tuple[str, list[str], list[Dropped]]:
    """Keep only sentences that cite valid evidence. Returns (clean_text, cited_ids, dropped)."""
    kept: list[str] = []
    cited: dict[str, None] = {}
    dropped: list[Dropped] = []
    for sentence in split_sentences(text):
        ids = CITATION_RE.findall(sentence)
        reason = validate_ids(ids, ledger)
        if reason is None and check_numbers:
            source_text = " ".join(
                f"{ledger.get(i).claim} {ledger.get(i).excerpt or ''} {ledger.get(i).title or ''}" for i in ids
            )
            unsupported = _numbers(sentence) - _numbers(source_text)
            if unsupported:
                reason = f"numbers not found in cited sources: {', '.join(sorted(unsupported))}"
        if reason:
            dropped.append(Dropped(sentence, reason))
            continue
        kept.append(sentence)
        for i in ids:
            cited.setdefault(i, None)
    return " ".join(kept), list(cited), dropped
