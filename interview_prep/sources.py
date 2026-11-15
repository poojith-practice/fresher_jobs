"""Public-web question sourcing for interview prep documents.

Finds real interview questions for a company/role/skill combination using
DuckDuckGo search (via ``ddgs``) and a polite, robots.txt-respecting HTML
fetcher. Only well-known, publicly scrapeable sites that need no API keys
and no logins are allowed, so this works identically on a laptop and in
GitHub Actions.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger("interview_prep.sources")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15.0
PACING_DELAY = 0.8
MAX_PAGE_CHARS = 800_000

# Sites that publish interview questions/experiences publicly, need no API
# key or login, and are generally fine to fetch politely.
APPROVED_DOMAINS = [
    "geeksforgeeks.org",
    "prepinsta.com",
    "ambitionbox.com",
    "interviewexperiences.in",
    "javatpoint.com",
    "sanfoundry.com",
    "interviewbit.com",
    "guru99.com",
    "tutorialspoint.com",
]

BLOCKED_HOST_MARKERS = ("youtube.com", "facebook.com", "twitter.com", "instagram.com", "x.com")

QUESTION_CUE = re.compile(
    r"\?|questions? (?:asked|were)|interview experience|technical round|hr round|"
    r"coding round|online assessment|describe|explain|tell (?:me|us) about|"
    r"how (?:would|do) you|what (?:is|are)|write a (?:program|query|function)",
    re.I,
)


def clean_text(text: Any, limit: int = 2000) -> str:
    """Normalize whitespace and truncate."""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def is_approved_host(url: str) -> bool:
    """True when the URL host (or a parent domain) is on the approved list."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host or any(host == marker or host.endswith("." + marker) for marker in BLOCKED_HOST_MARKERS):
        return False
    return any(host == d or host.endswith("." + d) for d in APPROVED_DOMAINS)


@dataclass
class SourceHit:
    query: str
    title: str
    url: str
    snippet: str


class PoliteFetcher:
    """Minimal HTTP client that obeys robots.txt, redirects and pacing."""

    def __init__(self, user_agent: str = DEFAULT_UA) -> None:
        self.ua = user_agent
        self.client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
            headers={
                "User-Agent": self.ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self.robots_cache: dict[str, Optional[RobotFileParser]] = {}
        self._last_request = 0.0

    def _robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots_cache:
            parser: Optional[RobotFileParser] = None
            try:
                res = self.client.get(f"{origin}/robots.txt")
                if res.status_code == 200:
                    parser = RobotFileParser(f"{origin}/robots.txt")
                    parser.parse(res.text.splitlines())
            except Exception as exc:  # noqa: BLE001 - network is best effort
                logger.debug("robots.txt fetch failed for %s: %s", origin, exc)
            self.robots_cache[origin] = parser
        parser = self.robots_cache[origin]
        if parser is None:
            # No usable robots.txt (404 or unreachable): be conservative but
            # still allow the fetch; disallow only when robots explicitly says no.
            return True
        try:
            return parser.can_fetch(self.ua, url)
        except Exception:  # noqa: BLE001
            return True

    def fetch_html(self, url: str) -> str:
        """Fetch an HTML page following same-host redirects. Empty string on failure."""
        current = url
        for _ in range(4):
            if not is_approved_host(current):
                logger.debug("Skipped non-approved host: %s", current)
                return ""
            if not self._robots_allowed(current):
                logger.debug("Skipped by robots.txt: %s", current)
                return ""
            delay = PACING_DELAY - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                res = self.client.get(current)
                self._last_request = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Fetch error %s: %s", current, exc)
                return ""
            if res.status_code in {301, 302, 303, 307, 308}:
                location = res.headers.get("location")
                if not location:
                    return ""
                if location.startswith("/"):
                    parts = urlsplit(current)
                    location = f"{parts.scheme}://{parts.netloc}{location}"
                current = location
                continue
            if res.status_code >= 400:
                logger.debug("HTTP %s for %s", res.status_code, current)
                return ""
            if "html" not in res.headers.get("content-type", "").lower():
                return ""
            return res.text[:MAX_PAGE_CHARS]
        return ""

    def close(self) -> None:
        self.client.close()


def search_hits(query: str, max_results: int = 5) -> list[SourceHit]:
    """One DDG web search, filtered to approved public domains."""
    hits: list[SourceHit] = []
    try:
        raw = list(DDGS().text(query, max_results=max_results * 3))
    except Exception as exc:  # noqa: BLE001
        logger.warning("DDG search failed for '%s': %s", query, exc)
        return hits
    for item in raw:
        url = str(item.get("href") or item.get("url") or "").strip()
        title = clean_text(item.get("title", ""), 200)
        if not url or not title:
            continue
        if not is_approved_host(url):
            continue
        hits.append(
            SourceHit(
                query=query,
                title=title,
                url=url,
                snippet=clean_text(item.get("body") or item.get("snippet") or "", 400),
            )
        )
        if len(hits) >= max_results:
            break
    return hits


def extract_question_lines(html: str) -> list[str]:
    """Pull question-like, de-duplicated lines from a fetched page."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, noscript, svg, header, footer, nav, form, iframe, button"):
        tag.decompose()
    nodes = soup.select("article p, article li, main p, main li, p, li, td")
    lines: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        line = clean_text(node.get_text(" ", strip=True), 400)
        if not (25 <= len(line) <= 400):
            continue
        if not QUESTION_CUE.search(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= 40:
            break
    return lines


def gather_question_context(
    company: str,
    role: str,
    skills: list[str],
    max_pages: int = 6,
) -> dict[str, Any]:
    """Search and scrape question evidence for a job.

    Returns a dict with ``company_excerpts``, ``role_excerpts``,
    ``skill_excerpts`` (list of strings) and ``sources`` (title + url lines).
    Everything degrades gracefully: any network/search failure simply yields
    fewer excerpts, never an exception.
    """
    company = clean_text(company, 100)
    role = clean_text(role, 100)
    skills = [clean_text(s, 60) for s in skills if clean_text(s, 60)][:3]

    queries: list[tuple[str, str]] = []
    if company:
        queries.append(("company", f'"{company}" interview questions'))
        if role:
            queries.append(("company", f'"{company}" "{role}" interview experience fresher'))
    if role:
        queries.append(("role", f'"{role}" interview questions and answers for freshers'))
    for skill in skills:
        queries.append(("skill", f'"{skill}" interview questions and answers'))
    if skills:
        queries.append(("skill", f'"{skills[0]}" coding questions for freshers with answers'))

    company_excerpts: list[str] = []
    role_excerpts: list[str] = []
    skill_excerpts: list[str] = []
    source_lines: list[str] = []
    seen_urls: set[str] = set()

    fetcher = PoliteFetcher()
    try:
        for kind, query in queries:
            if len(seen_urls) >= max_pages:
                break
            for hit in search_hits(query, max_results=2):
                if hit.url in seen_urls or len(seen_urls) >= max_pages:
                    continue
                seen_urls.add(hit.url)
                html = fetcher.fetch_html(hit.url)
                lines = extract_question_lines(html)
                if not lines:
                    continue
                target = (
                    company_excerpts if kind == "company"
                    else role_excerpts if kind == "role"
                    else skill_excerpts
                )
                target.extend(lines)
                source_lines.append(f"- {hit.title} ({hit.url})")
                time.sleep(0.3)
    finally:
        fetcher.close()

    context = {
        "company_excerpts": company_excerpts[:35],
        "role_excerpts": role_excerpts[:30],
        "skill_excerpts": skill_excerpts[:45],
        "sources": source_lines[:10],
    }
    total = sum(len(v) for v in (company_excerpts, role_excerpts, skill_excerpts))
    logger.info(
        "Question context for %s/%s: %d excerpts from %d pages",
        company or "?", role or "?", total, len(source_lines),
    )
    return context
