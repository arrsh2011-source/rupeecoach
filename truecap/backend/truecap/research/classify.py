"""Classify a URL into a source type and reliability."""

from __future__ import annotations

from urllib.parse import urlparse

from truecap.domain import Reliability, SourceType

AGGREGATORS = (
    "tofler.in", "zaubacorp.com", "thecompanycheck.com", "tracxn.com", "crunchbase.com", "inc42.com/datalabs",
    "privatecircle.co", "falconebiz.com", "instafinancials.com", "cbinsights.com", "pitchbook.com",
)
PROFILE_SITES = ("linkedin.com", "angel.co", "wellfound.com", "github.com")
# Press-release wires carry the company's own words.
PRESS_WIRES = ("prnewswire.com", "businesswire.com", "globenewswire.com", "newswire.com", "aninews.in/news/business/")
COURT_SITES = ("indiankanoon.org", "casemine.com", "sci.gov.in", "ecourts.gov.in", "nclt.gov.in", "nclat.nic.in")
TRADEMARK_SITES = ("ipindia.gov.in", "quickcompany.in", "trademarking.in")


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _matches(url: str, patterns: tuple[str, ...]) -> bool:
    host = _host(url)
    full = host + urlparse(url).path.lower()
    return any(host == p or host.endswith("." + p) or full.startswith(p) for p in patterns)


def is_government(url: str) -> bool:
    host = _host(url)
    return host.endswith(".gov.in") or host.endswith(".nic.in")


def classify(url: str, company_domain: str | None = None) -> tuple[SourceType, Reliability]:
    host = _host(url)
    if company_domain and (host == company_domain or host.endswith("." + company_domain)):
        return SourceType.COMPANY_WEBSITE, Reliability.SELF_REPORTED
    if _matches(url, PRESS_WIRES):
        return SourceType.NEWS, Reliability.SELF_REPORTED
    if _matches(url, COURT_SITES):
        # Search results are not a structured official query, so even court sites count as secondary.
        return SourceType.COURT, Reliability.SECONDARY
    if _matches(url, TRADEMARK_SITES):
        return SourceType.IP_INDIA, Reliability.SECONDARY
    if _matches(url, AGGREGATORS):
        return SourceType.AGGREGATOR, Reliability.SECONDARY
    if _matches(url, PROFILE_SITES):
        return SourceType.FOUNDER_PROFILE, Reliability.SECONDARY
    return SourceType.NEWS, Reliability.SECONDARY


def domain_of(url: str | None) -> str | None:
    return _host(url) if url else None
