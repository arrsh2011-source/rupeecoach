"""Stage-dependent category weights. Shown verbatim in every report.

Bump WEIGHTS_VERSION whenever these change, so stored reports stay explainable.
"""

from __future__ import annotations

from truecap.domain import Category, Stage

WEIGHTS_VERSION = "2026-10-v1"

STAGE_WEIGHTS: dict[Stage, dict[Category, float]] = {
    # Pre-seed: little traction or financial history exists, so the team carries the most weight.
    Stage.PRE_SEED: {
        Category.TEAM: 0.40,
        Category.MARKET: 0.25,
        Category.TRACTION: 0.10,
        Category.FINANCIALS: 0.05,
        Category.LEGAL: 0.20,
    },
    Stage.SEED: {
        Category.TEAM: 0.30,
        Category.MARKET: 0.20,
        Category.TRACTION: 0.20,
        Category.FINANCIALS: 0.10,
        Category.LEGAL: 0.20,
    },
    # Series A: claims about traction and financials should now be verifiable.
    Stage.SERIES_A: {
        Category.TEAM: 0.20,
        Category.MARKET: 0.15,
        Category.TRACTION: 0.25,
        Category.FINANCIALS: 0.20,
        Category.LEGAL: 0.20,
    },
    Stage.GROWTH: {
        Category.TEAM: 0.15,
        Category.MARKET: 0.10,
        Category.TRACTION: 0.25,
        Category.FINANCIALS: 0.30,
        Category.LEGAL: 0.20,
    },
}

for _stage, _w in STAGE_WEIGHTS.items():
    assert abs(sum(_w.values()) - 1.0) < 1e-9, f"weights for {_stage} must sum to 1"
    assert set(_w) == set(Category), f"weights for {_stage} must cover every category"
