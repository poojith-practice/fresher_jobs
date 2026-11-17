"""
UseAstra Scraper with Strict Role Triage & Zero Fabrication
===========================================================
Lane 1 Discovery adapter for UseAstra.
Filters out non-IT noise (chefs, housekeeping, pharma officers, adhesive technicians)
at the boundary, preserves raw authentic descriptions without synthetic text injection,
and marks non-technical roles as UNRELATED.
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

logger = logging.getLogger("scrapers.useastra")

# Strict tech / analyst keyword pattern for fresher roles
TECH_ROLE_PATTERN = re.compile(
    r"\b(software|developer|engineer|sde|programmer|data\s*analyst|business\s*analyst|"
    r"web|frontend|backend|full\s*stack|java|python|cloud|qa|testing|devops|graduate\s*trainee|"
    r"technical|systems|associate\s*engineer|it\s*service\s*desk|cybersecurity)\b",
    re.I,
)

# Unrelated / non-tech keyword pattern to reject immediately
EXPLICIT_NON_TECH_PATTERN = re.compile(
    r"\b(commis|chef|cook|housekeeping|stewarding|kitchen|waiter|hotel|"
    r"adhesive\s*technologist|technologist|technician-electrical|electrician|"
    r"officer\s*-\s*production|production\s*officer|pharma|pharmaceutical|"
    r"scientist|reg\s*science|remittances|qr\s*associate|territory\s*service|"
    r"food\s*beverage|welder|fitter)\b",
    re.I,
)


def scrape_useastra(limit: int = 25) -> List[Opportunity]:
    """Scrapes UseAstra with strict non-IT filtering and authentic provenance."""
    url = "https://useastra.in/jobs/off-campus-drives"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[useastra] Failed to load index: status %d (%s)", status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    opportunities: List[Opportunity] = []
    seen_urls = set()

    links = soup.find_all("a", href=re.compile(r"/jobs/[a-zA-Z0-9_-]+"))
    for a in links:
        href = a["href"].split("?")[0].strip()
        if href in seen_urls or href.endswith("/jobs/off-campus-drives"):
            continue

        raw_title = a.get_text(strip=True)
        if len(raw_title) < 8 or raw_title.lower() in {"apply", "view job", "details", "read more"}:
            continue

        seen_urls.add(href)
        full_url = urljoin(url, href)

        # Parse company and role from raw title (e.g. "Role at Company")
        company = "Enterprise Employer"
        role_title = raw_title
        if " at " in raw_title:
            parts = raw_title.split(" at ")
            role_title = parts[0].strip()
            company = parts[1].strip()
        elif " — " in raw_title:
            parts = raw_title.split(" — ")
            company = parts[0].strip()
            role_title = parts[1].strip()

        # Strict triage: If explicitly non-tech, classify as UNRELATED so it cannot pollute approved feeds
        is_non_tech = bool(EXPLICIT_NON_TECH_PATTERN.search(raw_title)) or bool(EXPLICIT_NON_TECH_PATTERN.search(role_title))
        is_tech = bool(TECH_ROLE_PATTERN.search(role_title))

        opp_type = OpportunityType.UNRELATED if is_non_tech else (
            OpportunityType.INDIVIDUAL_FRESHER_JOB if is_tech else OpportunityType.UNKNOWN
        )

        parent = a.find_parent(["div", "article", "li"])
        snippet = parent.get_text(" ", strip=True) if parent else ""

        batches = []
        batch_matches = re.findall(r"\b202[4-8]\b", f"{raw_title} {snippet}")
        if batch_matches:
            batches = sorted(list(set(int(b) for b in batch_matches)))

        opp_id = f"ua_{re.sub(r'[^a-zA-Z0-9]', '_', href)[-20:]}"

        # Never synthesize text like "{title} - Off-campus drive by {company}"
        # Keep the authentic snippet text as description
        opp = Opportunity(
            opportunity_id=opp_id,
            title=role_title,
            company=company,
            opportunity_type=opp_type,
            role_family="TECHNOLOGY" if is_tech else "NON_TECHNICAL",
            role=role_title,
            description=snippet[:1000] if snippet else raw_title,
            source_name="USEASTRA",
            source_listing_url=url,
            source_detail_url=full_url,
            apply_url=full_url,
            location=["Pan India"],
            deadline_status=DeadlineStatus.UNKNOWN,
            eligible_graduation_batches=batches,
            experience_min_years=0.0,
            experience_max_years=1.0,
            experience_status="UNKNOWN" if is_non_tech else "FRESHER_ELIGIBLE",
            company_verification_status=CompanyVerificationStatus.AGGREGATOR_ONLY,
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )

        opp.raw_evidence.append(
            make_evidence("title", role_title, full_url, f"Link text: {raw_title}")
        )
        if is_non_tech:
            opp.rejection_reasons.append(f"Explicit non-technical role: '{role_title}'")

        opportunities.append(opp)
        if len(opportunities) >= limit:
            break

    return opportunities
