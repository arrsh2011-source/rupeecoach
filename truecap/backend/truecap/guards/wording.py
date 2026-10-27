"""Wording guard: reports state facts neutrally and never give investment advice.

Two rule sets:
- ADVICE: anything that reads as a recommendation ("invest", "buy", "avoid", ...).
- ACCUSATION: words that characterise conduct rather than state facts ("fraud", "fake", ...).

Text inside double quotes is a quotation from a source (a court case type, a company
name, a sentence from the company's website). By default it is exempt from both rule
sets, since quoting a record is attribution. LLM-written text is checked with
`strict=True`, where quotes give no exemption.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ADVICE_PATTERNS = [
    r"\binvest\b",
    r"\b(?:buy|buying|sell|selling)\b",
    r"\bavoid(?:ed|ing)?\b",
    r"\brecommend(?:s|ed|ing|ation|ations)?\b",
    r"\b(?:you|investors?|we)\s+(?:should|must|ought to)\b",
    r"\b(?:good|great|bad|safe|risky|smart|solid|poor)\s+(?:investment|bet|opportunity|pick)\b",
    r"\bworth\s+(?:investing|backing|it)\b",
    r"\b(?:stay|keep)\s+away\b",
    r"\bsteer\s+clear\b",
    r"\b(?:undervalued|overvalued|multibagger|no[- ]brainer)\b",
    r"\bguaranteed?\s+returns?\b",
    r"\b(?:green|red)[- ]light\b",
]

ACCUSATION_PATTERNS = [
    r"\bfraud(?:s|ulent|ster|sters)?\b",
    r"\bscam(?:s|mer|mers|my)?\b",
    r"\bfake(?:d|s)?\b",
    r"\b(?:lied|liar|liars|lying)\b",
    r"\bcheat(?:s|ed|er|ers|ing)?\b",
    r"\bdishonest(?:y|ly)?\b",
    r"\b(?:shady|dodgy|crooked|crook|crooks)\b",
    r"\bmislead(?:s|ing)?\b|\bmisled\b",
    r"\bponzi\b",
    r"\bswindl\w*\b",
    r"\bembezzl\w*\b",
    r"\bcooked\s+(?:the\s+)?books\b",
    r"\bcon\s+(?:artist|man|job)\b",
    r"\bfabricat(?:ed|es|ing|ion)\b",
    r"\binflated\b",
]

_ADVICE = [re.compile(p, re.I) for p in ADVICE_PATTERNS]
_ACCUSE = [re.compile(p, re.I) for p in ACCUSATION_PATTERNS]
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")


@dataclass(frozen=True)
class Violation:
    rule: str  # "advice" | "accusation"
    term: str
    text: str


def find_violations(text: str, strict: bool = False) -> list[Violation]:
    if not text:
        return []
    scanned = text if strict else _QUOTED.sub(" ", text)
    out = [Violation("advice", m.group(0), text) for p in _ADVICE for m in p.finditer(scanned)]
    out += [Violation("accusation", m.group(0), text) for p in _ACCUSE for m in p.finditer(scanned)]
    return out


def is_neutral(text: str, strict: bool = False) -> bool:
    return not find_violations(text, strict)


def neutral_contrast(claim_source: str, claim: str, record_source: str, record: str) -> str:
    """The house style for a discrepancy: 'Deck claims X; filings show Y.'"""
    return f"{claim_source} states {claim}; {record_source} show {record}."
