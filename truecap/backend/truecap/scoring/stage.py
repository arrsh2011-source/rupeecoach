"""Infer a company's funding stage from funding-round facts, with user override."""

from __future__ import annotations

import re

from pydantic import BaseModel

from truecap.checks.base import ev
from truecap.domain import FactSet, Stage
from truecap.facts import FactKey

_ROUND_PATTERNS: list[tuple[re.Pattern[str], Stage]] = [
    (re.compile(r"series\s*[b-z]\b|pre[- ]?ipo|growth|late", re.I), Stage.GROWTH),
    (re.compile(r"pre[- ]?series\s*a|bridge", re.I), Stage.SEED),
    (re.compile(r"series\s*a\b", re.I), Stage.SERIES_A),
    (re.compile(r"pre[- ]?seed|angel|friends", re.I), Stage.PRE_SEED),
    (re.compile(r"seed", re.I), Stage.SEED),
]
_ORDER = [Stage.PRE_SEED, Stage.SEED, Stage.SERIES_A, Stage.GROWTH]


class StageDecision(BaseModel):
    stage: Stage  # the stage used for weighting
    inferred: Stage
    overridden: bool
    reason: str
    evidence_ids: list[str]


def classify_round(name: str) -> Stage | None:
    for pattern, stage in _ROUND_PATTERNS:
        if pattern.search(name):
            return stage
    return None


def infer_stage(facts: FactSet, override: Stage | None = None) -> StageDecision:
    rounds = facts.all(FactKey.FUNDING_ROUND)
    classified = [(r, s) for r in rounds if (s := classify_round(r.value.get("round", ""))) is not None]
    if classified:
        latest, stage = max(classified, key=lambda rs: _ORDER.index(rs[1]))
        inferred = stage
        reason = f"Latest funding round found: {latest.value['round']}."
        evidence = ev(latest)
    else:
        inferred = Stage.PRE_SEED
        reason = "No priced funding rounds were found, so pre-seed weights are used."
        evidence = []
    if override is not None and override != inferred:
        return StageDecision(
            stage=override,
            inferred=inferred,
            overridden=True,
            reason=f"Stage set by you. Inferred stage was {inferred.value}: {reason}",
            evidence_ids=evidence,
        )
    return StageDecision(stage=inferred, inferred=inferred, overridden=False, reason=reason, evidence_ids=evidence)
