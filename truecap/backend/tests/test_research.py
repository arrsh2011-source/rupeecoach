import json
from datetime import date

import httpx
import pytest

from truecap.domain import FactSet, Ledger, Outcome, Reliability, Severity, SourceType
from truecap.facts import FactKey as K
from truecap.research import extract
from truecap.research.budget import Budget, BudgetExceeded
from truecap.research.classify import classify
from truecap.research.extract import Extraction, XFounderClaim, XFunding, XRevenue, apply_extraction, quote_supported
from truecap.research.llm import Citation, Finding, Usage
from truecap.research.narrate import Item, NarrativeOut
from truecap.research.pipeline import Deps, NeedsPick, ResearchQuery, research
from truecap.research.sources.registry import RegistryClient, add_registry_facts
from truecap.research.sources.website import WebsiteFetcher, find_gstins, html_to_text
from truecap.research.web_research import findings_to_evidence, resolve_via_web
from truecap.render import render_html

# --- fakes ----------------------------------------------------------------------

RID = "res-ka"
REGISTRY_ROW = {
    "CORPORATE_IDENTIFICATION_NUMBER": "U72900KA2020PTC130001",
    "COMPANY_NAME": "LEAFLY SOFTWARE PRIVATE LIMITED",
    "COMPANY_STATUS": "ACTV",
    "COMPANY_CLASS": "Private",
    "COMPANY_CATEGORY": "Company limited by Shares",
    "DATE_OF_REGISTRATION": "15-01-2020",
    "REGISTERED_STATE": "Karnataka",
    "PAIDUP_CAPITAL": "150000",
    "Registered_Office_Address": "Indiranagar, Bengaluru",
    "LATEST_YEAR_BS": "31-03-2025",
}

HOME = """<html><head><title>Leafly</title></head><body>
<a href="/about">About us</a> <a href="/team">Team</a> <a href="/login">Login</a> <a href="https://other.example/x">x</a>
<p>Leafly helps restaurants cut food waste. Trusted since 2016.</p><p>FY25 revenue of ₹12 crore.</p>
<footer>GSTIN 29AAGCB7383J1Z4</footer><script>var x = "hidden";</script></body></html>"""
ABOUT = "<html><title>About</title><body><p>Founded by Meera Iyer, an IIT Madras graduate.</p></body></html>"
TEAM = "<html><body><p>Team page</p></body></html>"


def http_client(registry_rows=(REGISTRY_ROW,), site_up=True, robots="User-agent: *\nDisallow: /team\n"):
    def handler(req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        if host == "api.data.gov.in":
            name = req.url.params.get("filters[COMPANY_NAME]")
            cin = req.url.params.get("filters[CORPORATE_IDENTIFICATION_NUMBER]")
            rows = [r for r in registry_rows if r["COMPANY_NAME"] == name or r["CORPORATE_IDENTIFICATION_NUMBER"] == cin]
            return httpx.Response(200, json={"records": rows})
        if host == "leafly.example":
            if not site_up:
                return httpx.Response(503)
            pages = {"/robots.txt": robots, "/": HOME, "/about": ABOUT, "/team": TEAM}
            if path in pages:
                ctype = "text/plain" if path == "/robots.txt" else "text/html; charset=utf-8"
                return httpx.Response(200, text=pages[path], headers={"content-type": ctype,
                                      "last-modified": "Mon, 01 Sep 2026 10:00:00 GMT"})
            return httpx.Response(404)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


NEWS_SNIPPET = "Leafly, founded by IIT Madras alumna Meera Iyer, raised $2 million led by Monsoon Ventures."
FILING_SNIPPET = "As per RoC filings, Leafly Software reported revenue of Rs 4.1 crore in FY25."


class FakeLLM:
    def __init__(self, extraction: Extraction | None = None):
        self.calls = []
        self.extraction = extraction

    def web_research(self, system, prompt, max_searches):
        self.calls.append("web")
        return [
            Finding("[WEBSITE] https://leafly.example", [Citation("https://leafly.example/", "Leafly", "Leafly")]),
            Finding("[FUNDING] Leafly raised $2 million in a seed round.",
                    [Citation("https://news.example/leafly-seed", "Leafly raises seed", NEWS_SNIPPET)]),
            Finding("[FINANCIALS] Filings show FY25 revenue of Rs 4.1 crore.",
                    [Citation("https://tofler.in/leafly", "Leafly financials", FILING_SNIPPET)]),
            Finding("[LEGAL] The company has many disputes.", []),  # uncited -> dropped
            Finding("[MARKET] Not found."),
        ], Usage("claude-sonnet-5-5", 40_000, 2_000, 6)

    def structured(self, system, prompt, schema, model):
        self.calls.append(schema.__name__)
        if schema is Extraction:
            return self.extraction or default_extraction(prompt), Usage(model, 20_000, 1_500)
        if schema is NarrativeOut:
            return NarrativeOut(pros=[Item(check_id="legal.company_active", text="The registry lists it as Active [E1].")],
                                cons=[Item(check_id="traction.revenue_claim_matches_filings",
                                           text="Leafly is a scam [E3].")]), Usage(model, 3_000, 400)
        raise AssertionError(schema)


def _eid(prompt: str, url_part: str) -> str:
    for block in prompt.split("\n["):
        if url_part in block.split("\n")[0]:
            return block.split("]")[0].lstrip("[")
    raise AssertionError(url_part)


def default_extraction(prompt: str) -> Extraction:
    news, filing = _eid(prompt, "news.example"), _eid(prompt, "tofler.in")
    home = next(b for b in prompt.split("\n[") if "Leafly helps" in b).split("]")[0]  # fetched homepage
    return Extraction(
        founders=[], founder_claims=[], founder_experience=[], directors=[],
        funding_rounds=[XFunding(evidence_ids=[news], quote="raised $2 million led by Monsoon Ventures",
                                 round="Seed", date="2026-03", amount_usd=2e6, investors=["Monsoon Ventures"])],
        revenue_claims=[XRevenue(evidence_ids=[home], quote="FY25 revenue of ₹12 crore.", fy="FY25",
                                 amount_inr=120_000_000)],
        revenue_filed=[XRevenue(evidence_ids=[filing], quote="reported revenue of Rs 4.1 crore in FY25", fy="FY25",
                                amount_inr=41_000_000),
                       XRevenue(evidence_ids=[filing], quote="revenue of Rs 9 crore", fy="FY24",  # not in source
                                amount_inr=90_000_000)],
        market_size_claims=[], competitors=[], coverage=[], licence_need=None, licences_held=[],
        top_customer_share=None, vague_claims=[], headcount=[], court_cases=[], trademarks=[],
        claimed_founding_year=extract.XYear(evidence_ids=[home], quote="Trusted since 2016", year=2016),
        social_profiles=[],
    )


def make_deps(http, llm=None, cap=800.0, **kw):
    return Deps(
        llm=llm,
        registry=RegistryClient("key", [RID], http),
        website=WebsiteFetcher(http, "TrueCapBot/test", max_pages=4),
        budget=Budget(cap_inr=cap, usd_to_inr=88.0),
        extraction_model="claude-haiku-5-5",
        writing_model="claude-sonnet-5-5",
        established_investors=frozenset({"Monsoon Ventures"}),
        today=lambda: date(2026, 10, 27),
        **kw,
    )


# --- units ------------------------------------------------------------------------


@pytest.mark.parametrize("url, stype, rel", [
    ("https://www.tofler.in/x", SourceType.AGGREGATOR, Reliability.SECONDARY),
    ("https://in.linkedin.com/in/someone", SourceType.FOUNDER_PROFILE, Reliability.SECONDARY),
    ("https://www.prnewswire.com/in/news-releases/x", SourceType.NEWS, Reliability.SELF_REPORTED),
    ("https://indiankanoon.org/doc/1/", SourceType.COURT, Reliability.SECONDARY),
    ("https://economictimes.indiatimes.com/x", SourceType.NEWS, Reliability.SECONDARY),
    ("https://blog.leafly.example/post", SourceType.COMPANY_WEBSITE, Reliability.SELF_REPORTED),
])
def test_classify(url, stype, rel):
    assert classify(url, "leafly.example") == (stype, rel)


def test_registry_mapping_and_status_codes():
    reg = RegistryClient("key", [RID], http_client())
    recs = reg.search("Leafly Software")  # suffix variant "... PRIVATE LIMITED" finds it
    assert [r.cin for r in recs] == ["U72900KA2020PTC130001"]
    L = Ledger()
    F = FactSet(L)
    add_registry_facts(recs[0], L, F)
    assert F.value(K.STATUS) == "Active"
    assert F.value(K.INCORPORATION_DATE) == "2020-01-15"
    assert F.value(K.PAID_UP_CAPITAL) == 150000
    assert F.value(K.LAST_FILING_DATE) == "2025-03-31"
    assert F.value(K.REGISTERED_OFFICE) == "Indiranagar, Bengaluru"
    assert L.get("E1").reliability == Reliability.OFFICIAL


def test_registry_disabled_without_key():
    assert RegistryClient(None, [RID], http_client()).search("x") == []


def test_website_respects_robots_and_skips_login():
    site = WebsiteFetcher(http_client(), "TrueCapBot/test").fetch_site("leafly.example")
    urls = [p.url for p in site.pages]
    assert urls == ["https://leafly.example/", "https://leafly.example/about"]  # /team disallowed, /login skipped
    assert "hidden" not in site.pages[0].text
    assert find_gstins(site.pages[0].text) == ["29AAGCB7383J1Z4"]


def test_website_down():
    site = WebsiteFetcher(http_client(site_up=False), "ua").fetch_site("https://leafly.example/some/page")
    assert not site.live


def test_html_to_text():
    title, text, links = html_to_text("<title>T</title><p>a&amp;b</p><style>x{}</style><a href='/x'>y</a>")
    assert (title, links) == ("T", ["/x"])
    assert "a&b" in text and "x{}" not in text


def test_findings_to_evidence():
    llm = FakeLLM()
    findings, _ = llm.web_research("", "", 1)
    L = Ledger()
    res = findings_to_evidence(findings, L, None)
    assert res.website == "https://leafly.example"
    assert len(res.uncited) == 1
    tofler = next(e for e in L if "tofler" in e.url)
    assert tofler.source_type == SourceType.AGGREGATOR and res.source_text[tofler.id] == FILING_SNIPPET


@pytest.mark.parametrize("quote, ok", [
    ("raised $2 million led by Monsoon Ventures", True),
    ("Raised  $2 million   LED by monsoon ventures", True),
    ("founded by IIT Madras alumna … raised $2 million", True),
    ("raised $20 million", False),
    ("ab", False),
])
def test_quote_supported(quote, ok):
    assert quote_supported(quote, [NEWS_SNIPPET]) is ok


def test_quote_supported_rupee_and_curly_quotes():
    assert quote_supported("“₹4.1 crore”", ['He said "Rs. 4.1 crore" last year'])


def test_apply_extraction_rules():
    L = Ledger()
    site = L.add("site", SourceType.COMPANY_WEBSITE, url="https://leafly.example")
    news = L.add("news", SourceType.NEWS, url="https://news.example/a")
    F = FactSet(L)
    text = {site.id: "Our FY25 revenue was Rs 12 crore. Meera is an IIT Madras graduate.", news.id: NEWS_SNIPPET}
    ext = Extraction.model_validate({**{k: [] for k in Extraction.model_fields},
                                     "licence_need": None, "top_customer_share": None, "claimed_founding_year": None})
    ext.revenue_filed = [XRevenue(evidence_ids=[site.id], quote="FY25 revenue was Rs 12 crore", fy="FY25",
                                  amount_inr=120_000_000)]
    ext.founder_claims = [XFounderClaim(evidence_ids=[site.id], quote="Meera is an IIT Madras graduate",
                                        name="Meera", claim="IIT Madras graduate", status="corroborated", finding=None)]
    ext.funding_rounds = [XFunding(evidence_ids=[site.id], quote="FY25 revenue", round="Seed", date=None,
                                   amount_usd=None, investors=[]),
                          XFunding(evidence_ids=["E99"], quote="x", round="A", date=None, amount_usd=None,
                                   investors=[])]
    log = apply_extraction(ext, F, text)
    assert not F.has(K.REVENUE_FILED) and F.value(K.REVENUE_CLAIM)["amount_inr"] == 120_000_000
    assert F.value(K.FOUNDER_CLAIM)["status"] == "unverified"  # only the company says so
    assert F.value(K.FUNDING_ROUND)["independently_reported"] is False
    assert any("cites no known source" in line for line in log)


def test_resolve_via_web_parses_candidates():
    class L:
        def web_research(self, system, prompt, max_searches):
            return [Finding("CANDIDATE | LEAFLY SOFTWARE PRIVATE LIMITED | U72900KA2020PTC130001 | Bengaluru\n"
                            "CANDIDATE | LEAFLY FOODS LLP | AAA-1234 | Pune\n"
                            "CANDIDATE | LEAFLY TECH PRIVATE LIMITED | U72900MH2021PTC350002 | Mumbai")], Usage("m")
    cands, _ = resolve_via_web(L(), "Leafly", None, None)
    assert [c.cin for c in cands] == ["U72900KA2020PTC130001", "U72900MH2021PTC350002"]


def test_budget():
    b = Budget(cap_inr=100, usd_to_inr=88, spent_fn=lambda: 90)
    with pytest.raises(BudgetExceeded):
        b.ensure_room(25)
    b2 = Budget(cap_inr=100, usd_to_inr=88)
    b2.record(Usage("claude-sonnet-5-5", 1_000_000, 0, 0))  # $2 -> ₹176
    assert b2.run_cost_inr() == pytest.approx(176)


def test_usage_cost_includes_searches():
    assert Usage("claude-haiku-5-5", 1_000_000, 1_000_000, 10).cost_usd() == pytest.approx(0.1 + 0.5 + 0.1)


# --- end to end -------------------------------------------------------------------


def test_pipeline_end_to_end():
    llm = FakeLLM()
    steps = []
    out = research(ResearchQuery(name="Leafly Software"), make_deps(http_client(), llm),
                   progress=lambda s, p, m: steps.append(s))
    r = out.report
    assert steps[0] == "resolve" and steps[-1] == "done"
    assert llm.calls == ["web", "Extraction", "NarrativeOut"]
    assert out.cin == "U72900KA2020PTC130001"

    checks = {c.check_id: c for cat in r.scorecard.categories for c in cat.checks}
    assert checks["legal.company_active"].outcome == Outcome.PASS
    assert checks["traction.revenue_claim_matches_filings"].outcome == Outcome.FAIL
    assert checks["legal.incorporation_claim"].outcome == Outcome.FAIL  # 2016 claim vs 2020 incorporation
    assert checks["financials.institutional_investors"].outcome == Outcome.PASS
    assert checks["traction.web_presence"].outcome == Outcome.PASS
    assert checks["legal.gst_registration"].outcome == Outcome.UNKNOWN  # valid format, live status needs portal
    assert any(f.severity == Severity.RED for f in r.flags)

    # The research page's own site results got reclassified as self-reported.
    own = [e for e in r.evidence if e.url and e.url.startswith("https://leafly.example")
           and e.source_type != SourceType.COMPUTED]
    assert own and all(e.reliability == Reliability.SELF_REPORTED for e in own)

    # Guards: the hallucinated FY24 figure and the uncited sentence are logged; the accusatory con is replaced.
    assert any("quote not found" in line for line in out.log)
    assert any("cited no source" in line for line in out.log)
    con = next(c for c in r.cons if c.check_id == "traction.revenue_claim_matches_filings")
    assert "scam" not in con.text
    assert next(p for p in r.pros if p.check_id == "legal.company_active").text.endswith("[E1].")
    assert out.cost_inr > 0


def test_pipeline_without_llm_uses_registry_only():
    out = research(ResearchQuery(name="Leafly Software", website="leafly.example"), make_deps(http_client()))
    r = out.report
    assert r.scorecard.category("legal").score is not None
    assert out.cost_inr == 0
    assert r.scorecard.confidence.value == "low"


def test_pipeline_needs_pick_on_multiple_matches():
    other = {**REGISTRY_ROW, "CORPORATE_IDENTIFICATION_NUMBER": "U72900MH2021PTC350002", "REGISTERED_STATE": "Maharashtra",
             "Registered_Office_Address": "Andheri, Mumbai"}
    rows = (REGISTRY_ROW, other)
    with pytest.raises(NeedsPick) as e:
        research(ResearchQuery(name="Leafly Software"), make_deps(http_client(rows)))
    assert len(e.value.candidates) == 2
    # A city narrows it to one.
    out = research(ResearchQuery(name="Leafly Software", city="Mumbai"), make_deps(http_client(rows)))
    assert out.cin == "U72900MH2021PTC350002"


def test_pipeline_stops_when_budget_is_spent():
    deps = make_deps(http_client(), FakeLLM())
    deps.budget.spent_fn = lambda: 799.0
    with pytest.raises(BudgetExceeded):
        research(ResearchQuery(name="Leafly Software"), deps)


def test_render_html_embeds_report():
    out = research(ResearchQuery(name="Leafly Software"), make_deps(http_client(), FakeLLM()))
    html = render_html({"leafly": (out.company_name, {"auto": out.report.model_dump(mode="json")})})
    assert html.startswith("<!doctype html>") and "LEAFLY SOFTWARE PRIVATE LIMITED" in html
    data = html.split("const DATA = ", 1)[1].split(";\nconst CAT", 1)[0]
    assert json.loads(data.replace("<\\/", "</"))["companies"]["leafly"]["label"]
