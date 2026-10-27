import pytest

from truecap.domain import Ledger, SourceType
from truecap.guards import enforce_citations, find_violations, is_neutral, neutral_contrast, strip_uncited_sentences
from truecap.report.models import Pro


@pytest.mark.parametrize(
    "text",
    [
        "You should invest before the next round.",
        "We recommend this company.",
        "Investors should steer clear.",
        "This looks like a great investment.",
        "Avoid this one.",
        "A strong buy.",
        "The company appears undervalued.",
    ],
)
def test_advice_is_blocked(text):
    assert any(v.rule == "advice" for v in find_violations(text))


@pytest.mark.parametrize(
    "text",
    ["The founder lied about revenue.", "This is a scam.", "Fake traction numbers.", "The deck is misleading.",
     "Revenue figures were fabricated.", "Fraudulent filings."],
)
def test_accusations_are_blocked(text):
    assert any(v.rule == "accusation" for v in find_violations(text))


@pytest.mark.parametrize(
    "text",
    [
        "Investors include Monsoon Ventures.",
        "The company raised a seed round from three investors.",
        "Company materials state FY25 revenue of ₹4.50 crore; filed financials show ₹2.10 crore.",
        "The company sells farm inputs to retailers.",
        "Inflation in input costs affects margins.",
    ],
)
def test_neutral_facts_pass(text):
    assert is_neutral(text), find_violations(text)


def test_quotes_exempt_by_default_but_not_in_strict_mode():
    text = 'Court records show a pending "Cheating and fraud (IPC 420)" matter.'
    assert is_neutral(text)
    assert not is_neutral(text, strict=True)


def test_neutral_contrast_style():
    s = neutral_contrast("The deck", "₹10 crore ARR", "MCA filings", "₹2 crore revenue")
    assert s == "The deck states ₹10 crore ARR; MCA filings show ₹2 crore revenue."
    assert is_neutral(s)


@pytest.fixture
def ledger():
    L = Ledger()
    L.add("Filed revenue FY25 ₹2.10 crore", SourceType.MCA, excerpt="Revenue from operations 21,000,000")
    L.add("Seed round", SourceType.NEWS, excerpt="raised $1.5 million led by Monsoon Ventures")
    return L


def test_strip_uncited_sentences(ledger):
    text = ("Filed FY25 revenue was ₹2.10 crore [E1]. The team is world-class. "
            "It raised $1.5 million [E2]. Revenue will triple next year [E7].")
    clean, ids, dropped = strip_uncited_sentences(text, ledger)
    assert clean == "Filed FY25 revenue was ₹2.10 crore [E1]. It raised $1.5 million [E2]."
    assert ids == ["E1", "E2"]
    assert [d.reason for d in dropped] == ["no source cited", "cites unknown evidence E7"]


def test_numbers_must_appear_in_cited_source(ledger):
    clean, _, dropped = strip_uncited_sentences("It raised $4 million [E2].", ledger)
    assert clean == ""
    assert "numbers not found" in dropped[0].reason


def test_numbers_with_commas_match(ledger):
    clean, _, _ = strip_uncited_sentences("Revenue from operations was 21,000,000 in FY25 [E1].", ledger)
    assert clean


def test_enforce_citations_on_structured_items(ledger):
    items = [Pro(text="ok", category="team", evidence_ids=["E1"], check_id="x"),
             Pro(text="no source", category="team", evidence_ids=[], check_id="y"),
             Pro(text="bad source", category="team", evidence_ids=["E9"], check_id="z")]
    r = enforce_citations(items, ledger)
    assert [p.text for p in r.kept] == ["ok"]
    assert len(r.dropped) == 2
