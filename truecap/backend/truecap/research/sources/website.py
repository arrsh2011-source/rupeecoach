"""Fetch a company's public website (respecting robots.txt) and turn pages into text.

Only public pages on the company's own domain are fetched; nothing behind a login.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)
MAX_BYTES = 2_000_000
INTERESTING = re.compile(r"about|team|founder|leadership|company|story|contact|careers|investor|press", re.I)
LOGIN_HINT = re.compile(r"login|signin|sign-in|account|auth|cart|checkout", re.I)
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")


@dataclass
class Page:
    url: str
    title: str | None
    text: str
    last_modified: datetime | None = None


@dataclass
class SiteResult:
    live: bool
    pages: list[Page] = field(default_factory=list)
    error: str | None = None


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title: str | None = None
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data.strip()
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> tuple[str | None, str, list[str]]:
    p = _TextExtractor()
    p.feed(html)
    return p.title, p.text(), p.links


def normalise_site(url: str) -> str:
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class WebsiteFetcher:
    def __init__(self, http: httpx.Client, user_agent: str, max_pages: int = 4) -> None:
        self.http = http
        self.user_agent = user_agent
        self.max_pages = max_pages

    def _robots(self, base: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            resp = self.http.get(urljoin(base, "/robots.txt"))
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except httpx.HTTPError:
            rp.parse([])
        return rp

    def _get(self, url: str) -> Page | None:
        try:
            resp = self.http.get(url, follow_redirects=True)
        except httpx.HTTPError as e:
            log.info("fetch failed %s: %s", url, e)
            return None
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200 or "html" not in ctype or len(resp.content) > MAX_BYTES:
            return None
        title, text, links = html_to_text(resp.text)
        lm = resp.headers.get("last-modified")
        last_modified = None
        if lm:
            try:
                last_modified = parsedate_to_datetime(lm)
            except (TypeError, ValueError):
                pass
        page = Page(url=str(resp.url), title=title, text=text, last_modified=last_modified)
        page._links = links  # type: ignore[attr-defined]
        return page

    def fetch_site(self, website: str) -> SiteResult:
        base = normalise_site(website)
        robots = self._robots(base)
        if not robots.can_fetch(self.user_agent, base + "/"):
            return SiteResult(live=True, error="robots.txt disallows fetching this site")
        home = self._get(base + "/")
        if home is None:
            return SiteResult(live=False, error="homepage did not load")
        pages = [home]
        host = urlparse(home.url).netloc
        candidates: list[str] = []
        for href in getattr(home, "_links", []):
            full = urljoin(home.url, href).split("#")[0]
            u = urlparse(full)
            if u.netloc != host or not INTERESTING.search(u.path) or LOGIN_HINT.search(u.path):
                continue
            if full not in candidates and full.rstrip("/") != home.url.rstrip("/"):
                candidates.append(full)
        for url in candidates:
            if len(pages) >= self.max_pages:
                break
            if robots.can_fetch(self.user_agent, url) and (page := self._get(url)):
                pages.append(page)
        return SiteResult(live=True, pages=pages)


def find_gstins(text: str) -> list[str]:
    return list(dict.fromkeys(GSTIN_RE.findall(text.upper())))
