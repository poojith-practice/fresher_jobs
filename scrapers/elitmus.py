"""
eLitmus Jobs Scraper
====================
Lane 1 Discovery adapter for eLitmus.
Extracts structured corporate fresher jobs, trainee roles, and salary benchmarks.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List
from urllib.parse import urljoin
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

logger = logging.getLogger("scrapers.elitmus")


def scrape_elitmus(limit: int = 20) -> List[Opportunity]:
    """Scrapes candidate listings from eLitmus jobs."""
    url = "https://www.elitmus.com/jobs"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[elitmus] Failed to fetch jobs index: status %d (%s)", status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    opportunities: List[Opportunity] = []
    seen_urls = set()

    # Find job rows/cards
    rows = soup.select(".job, tr.job-row, .card, div.list-group-item, table tbody tr")
    for r in rows:
        a_elem = r.find("a", href=re.compile(r"/jobs/\d+"))
        if not a_elem:
            continue
        href = a_elem["href"].strip()
        full_url = urljoin(url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = a_elem.get_text(strip=True)
        if not title or len(title) < 4:
            continue

        comp_elem = r.select_one(".company, .employer, td:nth-child(2)")
        company = comp_elem.get_text(strip=True) if comp_elem else "eLitmus Corporate Partner"

        loc_elem = r.select_one(".location, td:nth-child(3)")
        loc_str = loc_elem.get_text(strip=True) if loc_elem else "India"

        snippet = r.get_text(" | ", strip=True)
        opp_id = f"el_{re.sub(r'[^a-zA-Z0-9]', '_', href)[-20:]}"

        batches = []
        batch_matches = re.findall(r"\b202[4-8]\b", snippet)
        if batch_matches:
            batches = sorted(list(set(int(b) for b in batch_matches)))

        opp = Opportunity(
            opportunity_id=opp_id,
            title=title,
            company=company,
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            role_family="TECHNOLOGY",
            role=title,
            description=snippet[:1000],
            source_name="ELITMUS",
            source_listing_url=url,
            source_detail_url=full_url,
            apply_url=full_url,
            location=[loc_str],
            deadline_status=DeadlineStatus.OPEN,
            eligible_graduation_batches=batches or [2025, 2026],
            experience_min_years=0.0,
            experience_max_years=1.0,
            experience_status="FRESHER_ELIGIBLE",
            company_verification_status=CompanyVerificationStatus.PUBLIC_AGGREGATOR,
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )
        opp.raw_evidence.append(
            make_evidence("title", title, full_url, f"Listing title: {title}")
        )
        opportunities.append(opp)
        if len(opportunities) >= limit:
            break

    return opportunities
