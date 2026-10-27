import pytest

from truecap.domain import Fact, FactSet, Ledger, Reliability, SourceType


def test_ledger_assigns_sequential_ids_and_default_reliability():
    L = Ledger()
    a = L.add("registry", SourceType.MCA)
    b = L.add("website", SourceType.COMPANY_WEBSITE, url="https://www.acme.example/about")
    assert (a.id, b.id) == ("E1", "E2")
    assert a.reliability == Reliability.OFFICIAL
    assert b.reliability == Reliability.SELF_REPORTED
    assert b.domain == "acme.example"


def test_fact_without_evidence_is_rejected():
    F = FactSet(Ledger())
    with pytest.raises(ValueError, match="no evidence"):
        F.add(Fact(key="company.status", value="Active", evidence_ids=[]))


def test_fact_citing_unknown_evidence_is_rejected():
    F = FactSet(Ledger())
    with pytest.raises(ValueError, match="unknown evidence"):
        F.put("company.status", "Active", "E99")


def test_first_prefers_most_reliable_source():
    L = Ledger()
    web = L.add("site", SourceType.COMPANY_WEBSITE)
    mca = L.add("mca", SourceType.MCA)
    F = FactSet(L)
    F.put("company.incorporation_date", "2018-01-01", web.id)
    F.put("company.incorporation_date", "2021-06-14", mca.id)
    assert F.value("company.incorporation_date") == "2021-06-14"


def test_verified_needs_official_or_two_independent_domains():
    L = Ledger()
    site = L.add("site", SourceType.COMPANY_WEBSITE, url="https://acme.example")
    n1 = L.add("news 1", SourceType.NEWS, url="https://news-a.example/x")
    n1b = L.add("news 1 again", SourceType.NEWS, url="https://news-a.example/y")
    n2 = L.add("news 2", SourceType.NEWS, url="https://news-b.example/z")
    mca = L.add("mca", SourceType.MCA)
    F = FactSet(L)
    assert not F.is_verified(F.put("k", 1, site.id))
    assert not F.is_verified(F.put("k", 1, n1.id, n1b.id))  # same domain twice
    assert F.is_verified(F.put("k", 1, n1.id, n2.id))
    assert F.is_verified(F.put("k", 1, site.id, mca.id))
