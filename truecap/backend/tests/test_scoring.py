import pytest

from truecap.checks import run_all
from truecap.domain import Category, CheckResult, Outcome, Stage
from truecap.domain import SourceType as S
from truecap.facts import FactKey as K
from truecap.sample_data import kisankart, sparse
from truecap.scoring import STAGE_WEIGHTS, Confidence, fail_impact, infer_stage, score


def res(cat, outcome, weight=1.0, cid=None):
    return CheckResult(check_id=cid or f"{cat}.{outcome}.{weight}", category=cat, title="t", outcome=outcome,
                       detail="d", evidence_ids=[] if outcome == Outcome.UNKNOWN else ["E1"], weight=weight)


def test_category_score_is_weighted_pass_share_and_ignores_unknown():
    card = score([res(Category.TEAM, Outcome.PASS, 2), res(Category.TEAM, Outcome.FAIL, 1),
                  res(Category.TEAM, Outcome.UNKNOWN, 5)], Stage.SEED)
    team = card.category(Category.TEAM)
    assert team.score == pytest.approx(6.7)
    assert team.coverage == pytest.approx(3 / 8)


def test_missing_data_lowers_confidence_not_score():
    base = [res(c, Outcome.PASS, cid=f"{c}.p") for c in Category]
    more_unknown = base + [res(c, Outcome.UNKNOWN, 3, cid=f"{c}.u") for c in Category]
    full, partial = score(base, Stage.SEED), score(more_unknown, Stage.SEED)
    assert full.overall == partial.overall == 10.0
    assert full.confidence == Confidence.HIGH
    assert partial.confidence == Confidence.LOW


def test_all_unknown_category_is_excluded_and_weights_renormalised():
    results = [res(Category.TEAM, Outcome.PASS), res(Category.LEGAL, Outcome.FAIL)]
    card = score(results, Stage.PRE_SEED)
    assert card.category(Category.MARKET).score is None
    w = STAGE_WEIGHTS[Stage.PRE_SEED]
    expected = 10 * w[Category.TEAM] / (w[Category.TEAM] + w[Category.LEGAL])
    assert card.overall == pytest.approx(round(expected, 1))


def test_no_data_at_all():
    card = score([res(c, Outcome.UNKNOWN) for c in Category], Stage.SEED)
    assert card.overall is None and card.confidence == Confidence.LOW


def test_stage_changes_weights_and_score():
    results = [res(Category.TEAM, Outcome.PASS), res(Category.TRACTION, Outcome.FAIL)]
    assert score(results, Stage.PRE_SEED).overall > score(results, Stage.SERIES_A).overall


def test_weights_published_in_scorecard():
    card = score([], Stage.SERIES_A)
    assert card.weights == STAGE_WEIGHTS[Stage.SERIES_A]
    assert card.weights_version


def test_fail_impact_matches_flipping_the_check(ctx):
    _, facts = kisankart()
    results = run_all(facts, ctx)
    card = score(results, Stage.SEED)
    impact = fail_impact(card, "traction.revenue_claim_matches_filings")
    flipped = [r.model_copy(update={"outcome": Outcome.PASS}) if r.check_id == "traction.revenue_claim_matches_filings"
               else r for r in results]
    assert impact.category_points == pytest.approx(
        score(flipped, Stage.SEED).category(Category.TRACTION).score - card.category(Category.TRACTION).score, abs=0.11)
    assert impact.overall_points > 0
    assert fail_impact(card, "legal.company_active").category_points == 0  # passed check costs nothing


def test_sparse_company_low_confidence(ctx):
    _, facts = sparse()
    card = score(run_all(facts, ctx), Stage.PRE_SEED)
    assert card.confidence == Confidence.LOW
    assert card.overall == 10.0  # what was found is fine; we just know little


@pytest.mark.parametrize(
    "rounds, expected",
    [([], Stage.PRE_SEED), (["Angel"], Stage.PRE_SEED), (["Pre-seed", "Seed"], Stage.SEED),
     (["Seed", "Pre-Series A"], Stage.SEED), (["Seed", "Series A"], Stage.SERIES_A),
     (["Series A", "Series C"], Stage.GROWTH)],
)
def test_infer_stage(b, rounds, expected):
    for r in rounds:
        b.put(K.FUNDING_ROUND, {"round": r, "independently_reported": True}, S.NEWS)
    d = infer_stage(b.facts)
    assert d.stage == expected and not d.overridden
    assert bool(d.evidence_ids) == bool(rounds)


def test_stage_override(b):
    b.put(K.FUNDING_ROUND, {"round": "Seed"}, S.NEWS)
    d = infer_stage(b.facts, Stage.SERIES_A)
    assert d.stage == Stage.SERIES_A and d.inferred == Stage.SEED and d.overridden
    assert not infer_stage(b.facts, Stage.SEED).overridden
