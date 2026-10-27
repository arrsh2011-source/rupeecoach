"""Deterministic scoring. No LLM is involved in any number produced here.

- Category score = 10 x (weight of passed checks) / (weight of passed + failed checks).
  UNKNOWN checks are excluded from the score.
- Overall score = stage-weighted mean of the categories that have a score
  (weights re-normalised over those categories).
- Confidence reflects how much of the weighted check universe was actually decided.
  Missing data lowers confidence, never the score.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from truecap.domain import Category, CheckResult, Outcome, Stage
from truecap.scoring.weights import STAGE_WEIGHTS, WEIGHTS_VERSION

HIGH_COVERAGE = 0.65
MEDIUM_COVERAGE = 0.35
MIN_SCORED_CATEGORIES_FOR_HIGH = 4


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CategoryScore(BaseModel):
    category: Category
    score: float | None  # None when every check is unknown
    weight: float  # stage weight of this category
    passed: int
    failed: int
    unknown: int
    coverage: float  # share of this category's check weight that was decided
    checks: list[CheckResult]


class ScoreCard(BaseModel):
    stage: Stage
    weights_version: str
    weights: dict[Category, float]
    overall: float | None
    confidence: Confidence
    coverage: float
    categories: list[CategoryScore]

    def category(self, category: Category) -> CategoryScore:
        return next(c for c in self.categories if c.category == category)


def _raw_category_score(results: list[CheckResult]) -> float | None:
    passed = sum(r.weight for r in results if r.outcome == Outcome.PASS)
    failed = sum(r.weight for r in results if r.outcome == Outcome.FAIL)
    if passed + failed == 0:
        return None
    return 10 * passed / (passed + failed)


def score_category(category: Category, results: list[CheckResult], weight: float) -> CategoryScore:
    total = sum(r.weight for r in results)
    decided = sum(r.weight for r in results if r.outcome != Outcome.UNKNOWN)
    raw = _raw_category_score(results)
    return CategoryScore(
        category=category,
        score=None if raw is None else round(raw, 1),
        weight=weight,
        passed=sum(r.outcome == Outcome.PASS for r in results),
        failed=sum(r.outcome == Outcome.FAIL for r in results),
        unknown=sum(r.outcome == Outcome.UNKNOWN for r in results),
        coverage=0.0 if total == 0 else decided / total,
        checks=results,
    )


def _overall(categories: list[CategoryScore], use_raw: dict[Category, float] | None = None) -> float | None:
    scored = [(c, (use_raw or {}).get(c.category, c.score)) for c in categories]
    scored = [(c, s) for c, s in scored if s is not None]
    if not scored:
        return None
    total_w = sum(c.weight for c, _ in scored)
    return sum(c.weight * s for c, s in scored) / total_w


def confidence_for(categories: list[CategoryScore]) -> tuple[Confidence, float]:
    coverage = sum(c.weight * c.coverage for c in categories)
    scored = sum(c.score is not None for c in categories)
    if coverage >= HIGH_COVERAGE and scored >= MIN_SCORED_CATEGORIES_FOR_HIGH:
        return Confidence.HIGH, coverage
    if coverage >= MEDIUM_COVERAGE and scored >= 2:
        return Confidence.MEDIUM, coverage
    return Confidence.LOW, coverage


def score(results: list[CheckResult], stage: Stage) -> ScoreCard:
    weights = STAGE_WEIGHTS[stage]
    categories = [
        score_category(cat, [r for r in results if r.category == cat], weights[cat]) for cat in Category
    ]
    overall = _overall(categories)
    confidence, coverage = confidence_for(categories)
    return ScoreCard(
        stage=stage,
        weights_version=WEIGHTS_VERSION,
        weights=dict(weights),
        overall=None if overall is None else round(overall, 1),
        confidence=confidence,
        coverage=round(coverage, 3),
        categories=categories,
    )


class Impact(BaseModel):
    category_points: float  # how many category points this failed check costs
    overall_points: float


def fail_impact(card: ScoreCard, check_id: str) -> Impact:
    """Points a failed check costs: score if it had passed minus the actual score."""
    cat = next(c for c in card.categories if any(r.check_id == check_id for r in c.checks))
    target = next(r for r in cat.checks if r.check_id == check_id)
    if target.outcome != Outcome.FAIL:
        return Impact(category_points=0.0, overall_points=0.0)
    flipped = [r.model_copy(update={"outcome": Outcome.PASS}) if r.check_id == check_id else r for r in cat.checks]
    raw_actual = _raw_category_score(cat.checks)
    raw_flipped = _raw_category_score(flipped)
    overall_actual = _overall(card.categories, {cat.category: raw_actual})
    overall_flipped = _overall(card.categories, {cat.category: raw_flipped})
    return Impact(
        category_points=round(raw_flipped - raw_actual, 1),
        overall_points=round(overall_flipped - overall_actual, 1),
    )
