"""
Public Search-Engine Discovery Layer (Lane 2)
==============================================
Discovers fresh graduate hiring campaigns and off-campus recruitment drives across India
via public, unauthenticated search endpoints (DuckDuckGo Lite / Bing HTML) without browser automation.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse
from bs4 import BeautifulSoup

from core.http_client import http_client
from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
)
from core.evidence import make_evidence

logger = logging.getLogger("discovery.search_engine")

SEARCH_QUERY_TEMPLATES = [
    "software engineer fresher apply online 2026 India",
    "graduate engineer trainee 2026 India careers",
    "off campus recruitment drive 2026 registration open India",
    "fresher technical associate 2026 batch India",
]

COMPANY_QUERY_TEMPLATES = [
    "{company} fresher careers 2026 India",
    "{company} graduate hiring 2026 India apply",
]


def _clean_ddg_url(raw_url: str) -> str:
    """Extracts actual destination URL from DuckDuckGo redirect wrapper."""
    if "duckduckgo.com/l/?" in raw_url:
        parsed = urlparse(raw_url)
        params = parse_qs(parsed.query)
        uddg = params.get("uddg")
        if uddg:
            return unquote(uddg[0])
    return raw_url


def search_duckduckgo_lite(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Performs public search on DuckDuckGo Lite endpoint without credentials."""
    url = "https://lite.duckduckgo.com/lite/"
    data = {"q": query}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://lite.duckduckgo.com/",
    }

    body, status, outcome = http_client.post(url, data=data, headers=headers)
    if status != 200 or not body:
        logger.warning("[search_engine] DuckDuckGo Lite failed for '%s': status %d (%s)", query, status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    results = []

    # DDG Lite uses table rows for results
    rows = soup.find_all("tr")
    current_title = ""
    current_link = ""

    for tr in rows:
        link_tag = tr.find("a", class_="result-link")
        if link_tag:
            current_title = link_tag.get_text(" ", strip=True)
            raw_href = link_tag.get("href", "")
            current_link = _clean_ddg_url(raw_href)
            continue

        snippet_td = tr.find("td", class_="result-snippet")
        if snippet_td and current_link:
            snippet = snippet_td.get_text(" ", strip=True)
            results.append({
                "title": current_title,
                "url": current_link,
                "snippet": snippet,
                "query": query,
                "source": "duckduckgo_lite",
            })
            current_title = ""
            current_link = ""
            if len(results) >= max_results:
                break

    return results


def discover_via_search(
    queries: Optional[List[str]] = None,
    max_results_per_query: int = 5,
) -> List[Opportunity]:
    """Runs Lane 2 public search discovery and yields candidate Opportunity objects."""
    active_queries = queries or SEARCH_QUERY_TEMPLATES
    opportunities: List[Opportunity] = []

    for query in active_queries:
        raw_items = search_duckduckgo_lite(query, max_results=max_results_per_query)
        for item in raw_items:
            target_url = item.get("url") or ""
            if not target_url or not target_url.startswith("http"):
                continue

            # Skip irrelevant domains or search engine wrappers
            domain = urlparse(target_url).netloc.lower()
            if any(block in domain for block in ["youtube.com", "facebook.com", "instagram.com", "reddit.com", "quora.com"]):
                continue

            title = item.get("title") or "Fresher Opportunity"
            snippet = item.get("snippet") or ""

            # Attempt simple company extraction from title (e.g. "Company - Title" or "Title at Company")
            company = "Identified via Search"
            at_match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&.\s]{2,25})\b", title)
            dash_match = re.search(r"^([A-Z][A-Za-z0-9&.\s]{2,25})\s*[-|:]", title)
            if at_match:
                company = at_match.group(1).strip()
            elif dash_match:
                company = dash_match.group(1).strip()

            opp_id = f"search_{abs(hash(target_url)) % 100000000}"
            ev_snippet = make_evidence(
                field="snippet",
                value=snippet,
                source_url=target_url,
                evidence_text=snippet,
                extraction_method="search_engine_discovery",
                confidence=0.8,
            )

            opp = Opportunity(
                opportunity_id=opp_id,
                title=title,
                company=company,
                opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB if "drive" not in title.lower() else OpportunityType.OFF_CAMPUS_DRIVE,
                role=title,
                description=snippet,
                source_name="SEARCH_ENGINE_DISCOVERY",
                source_listing_url=f"https://lite.duckduckgo.com/lite/?q={query}",
                source_detail_url=target_url,
                apply_url=target_url,
                all_source_urls=[target_url],
                raw_evidence=[ev_snippet],
                deadline_status=DeadlineStatus.UNKNOWN,
                application_status=ApplicationStatus.UNKNOWN,
                company_verification_status=CompanyVerificationStatus.UNVERIFIED,
            )
            opportunities.append(opp)

    return opportunities
