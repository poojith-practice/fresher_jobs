"""
JoinSaarthi Scraper (Next.js __NEXT_DATA__ Extractor)
=====================================================
Lane 1 Discovery adapter for JoinSaarthi.
Directly parses structured Next.js JSON props for live campus drives,
filtering out ended drives and preserving structured metadata.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import List
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

logger = logging.getLogger("scrapers.joinsaarthi")


def scrape_joinsaarthi(limit: int = 25) -> List[Opportunity]:
    """Extracts structured off-campus drives directly from JoinSaarthi Next.js payload."""
    url = "https://joinsaarthi.com/drives/off-campus"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[joinsaarthi] Failed to fetch page: status %d (%s)", status, outcome)
        return []

    opportunities: List[Opportunity] = []
    try:
        soup = BeautifulSoup(body, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.warning("[joinsaarthi] Missing __NEXT_DATA__ payload")
            return []

        data = json.loads(script.string)
        page_props = data.get("props", {}).get("pageProps", {})
        initial_drives = page_props.get("initialDrives", [])
        if isinstance(initial_drives, dict):
            initial_drives = initial_drives.get("data", [])

        for d in initial_drives[:limit]:
            # Respect isDriveEnded flag
            if d.get("isDriveEnded") is True:
                continue

            drive_id = str(d.get("id") or "")
            title = str(d.get("drive_name") or "Off-Campus Drive").strip()
            comp_obj = d.get("company") or {}
            company = comp_obj.get("name") or d.get("college_controlled_drive_company_name") or "Corporate Employer"
            locations = d.get("locations") or ["Pan India"]
            desc = str(d.get("description") or d.get("eligibility_criteria") or "").strip()
            end_date = d.get("end_date")

            batches = []
            batch_matches = re.findall(r"\b202[4-8]\b", f"{title} {desc}")
            if batch_matches:
                batches = sorted(list(set(int(b) for b in batch_matches)))

            detail_url = f"https://joinsaarthi.com/drives/{drive_id}" if drive_id else url
            opp_id = f"js_{drive_id[-16:] if drive_id else 'drive'}"

            # Check deadline vs current clock
            deadline_status = DeadlineStatus.OPEN
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    if end_dt.date() < datetime.utcnow().date():
                        deadline_status = DeadlineStatus.EXPIRED
                except Exception:
                    pass

            opp = Opportunity(
                opportunity_id=opp_id,
                title=title,
                company=company,
                opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
                role_family="TECHNOLOGY",
                role=title,
                description=desc if desc else f"{title} - Recruitment drive by {company}",
                source_name="JOINSAARTHI",
                source_listing_url=url,
                source_detail_url=detail_url,
                apply_url=detail_url,
                location=locations if isinstance(locations, list) else [str(locations)],
                deadline=end_date,
                deadline_status=deadline_status,
                eligible_graduation_batches=batches or [2025, 2026],
                experience_min_years=0.0,
                experience_max_years=1.0,
                experience_status="FRESHER_ELIGIBLE",
                company_verification_status=CompanyVerificationStatus.PUBLIC_AGGREGATOR,
                retrieved_at=datetime.utcnow().isoformat() + "Z",
            )
            opp.raw_evidence.append(
                make_evidence("drive_payload", title, detail_url, f"JoinSaarthi drive: {title} by {company}")
            )
            opportunities.append(opp)

    except Exception as exc:
        logger.warning("[joinsaarthi] Parsing error: %s", exc)

    return opportunities
