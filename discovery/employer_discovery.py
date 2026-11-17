"""
Lane 3: Verified Employer Direct Feeds & ATS Discovery
======================================================
Polls verified employer careers APIs and unauthenticated ATS endpoints
(Amazon Jobs JSON, Greenhouse, Lever, Ashby, SmartRecruiters) directly.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.http_client import http_client
from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
)
from core.evidence import make_evidence
from ats.greenhouse import fetch_greenhouse_jobs
from ats.lever import fetch_lever_jobs
from ats.ashby import fetch_ashby_jobs
from ats.smartrecruiters import fetch_smartrecruiters_jobs

logger = logging.getLogger("discovery.employer_discovery")

FRESHER_TITLE_PATTERNS = [
    r"\bfreshers?\b",
    r"\bgraduates?\b",
    r"\btrainee\b",
    r"\bassociate\b",
    r"\bintern(?:ship)?\b",
    r"\bentry[\s-]?level\b",
    r"\bjunior\b",
    r"\bsde[\s-]?1\b",
    r"\bengineer[\s-]?1\b",
    r"\bqa[\s-]?1\b",
    r"\banalyst[\s-]?1\b",
]

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "employer_registry.json"


def load_employer_registry() -> List[Dict[str, Any]]:
    """Loads employer registry from json file."""
    if not REGISTRY_PATH.exists():
        logger.warning("[employer_discovery] Employer registry file not found: %s", REGISTRY_PATH)
        return []
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("[employer_discovery] Failed to parse employer registry: %s", exc)
        return []


def is_fresher_title_or_desc(title: str, desc: str) -> bool:
    """Checks whether the title or description suggests an entry-level or graduate opportunity."""
    t_lower = title.lower()
    for pat in FRESHER_TITLE_PATTERNS:
        if re.search(pat, t_lower):
            return True
    d_snippet = desc[:1000].lower()
    if any(k in d_snippet for k in ["0-1 year", "freshers welcome", "recent graduate", "college graduate"]):
        return True
    return False


def discover_amazon_jobs(max_items: int = 25) -> List[Opportunity]:
    """Polls public Amazon Careers JSON API for software engineering fresher opportunities in India."""
    urls = [
        "https://www.amazon.jobs/en/search.json?category%5B%5D=software-development&country=IND&base_query=Engineer+I",
        "https://www.amazon.jobs/en/search.json?category%5B%5D=software-development&country=IND&base_query=SDE+I",
    ]
    seen_ids = set()
    opportunities = []

    for url in urls:
        body, status, outcome = http_client.get(url)
        if status != 200 or not body:
            logger.warning("[employer_discovery] Amazon Jobs fetch failed: status %d (%s)", status, outcome)
            continue

        try:
            data = json.loads(body)
        except Exception as exc:
            logger.warning("[employer_discovery] Amazon JSON decode failed: %s", exc)
            continue

        jobs = data.get("jobs", [])
        for j in jobs:
            job_id = str(j.get("id_icims") or j.get("id") or "")
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = str(j.get("title") or "").strip()
            # Strictly exclude experienced / senior roles
            if re.search(r"\b(?:ii|iii|senior|lead|manager|principal|experienced)\b", title, re.I):
                continue

            job_path = str(j.get("job_path") or "")
            city = str(j.get("city") or "India")
            posted = str(j.get("posted_date") or "")
            desc = str(j.get("description") or "")
            basic_quals = str(j.get("basic_qualifications") or "")

            apply_url = f"https://www.amazon.jobs{job_path}" if job_path else "https://www.amazon.jobs"
            full_desc = f"{desc}\n\nBasic Qualifications:\n{basic_quals}".strip()

            # Extract batches from text only if authentic; never fabricate defaults
            batches = [int(b) for b in re.findall(r"\b202[4-8]\b", full_desc)]
            batches = sorted(list(set(batches)))

            opp_id = f"amazon_{job_id}"
            ev_title = make_evidence(
                field="title",
                value=title,
                source_url=apply_url,
                evidence_text=title,
                extraction_method="amazon_json_api",
                confidence=1.0,
            )

            opp = Opportunity(
                opportunity_id=opp_id,
                title=title,
                company="Amazon",
                opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
                role=title,
                description=full_desc,
                source_name="AMAZON_CAREERS_OFFICIAL",
                source_listing_url=url,
                source_detail_url=apply_url,
                employer_career_url="https://www.amazon.jobs",
                employer_job_url=apply_url,
                apply_url=apply_url,
                all_source_urls=[apply_url],
                location=[f"{city}, India"],
                work_mode="On-site",
                date_posted=posted,
                date_posted_basis="API posted_date field",
                deadline_status=DeadlineStatus.OPEN,
                application_status=ApplicationStatus.OPEN,
                application_status_evidence="Active official requisition on Amazon Jobs portal",
                eligible_graduation_batches=batches,
                company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
                employer_verification_url=apply_url,
                raw_evidence=[ev_title],
            )
            opportunities.append(opp)
            if len(opportunities) >= max_items:
                break
        if len(opportunities) >= max_items:
            break

    return opportunities


def discover_ats_jobs(max_per_employer: int = 15) -> List[Opportunity]:
    """Polls public ATS boards for employers registered in employer_registry.json."""
    registry = load_employer_registry()
    opportunities: List[Opportunity] = []

    for emp in registry:
        platform = emp.get("ats_platform")
        company_name = emp.get("name")
        company_id = emp.get("ats_identifier") or emp.get("company_id")
        if not platform or not company_id:
            continue

        raw_jobs = []
        if platform == "GREENHOUSE":
            raw_jobs = fetch_greenhouse_jobs(company_id)
        elif platform == "LEVER":
            raw_jobs = fetch_lever_jobs(company_id)
        elif platform == "ASHBY":
            raw_jobs = fetch_ashby_jobs(company_id)
        elif platform == "SMARTRECRUITERS":
            raw_jobs = fetch_smartrecruiters_jobs(company_id)
        else:
            continue

        for rj in raw_jobs[:max_per_employer]:
            title = rj.get("title") or ""
            desc = rj.get("description") or ""
            job_url = rj.get("job_url") or ""

            # Only accept fresher / junior / entry-level / trainee jobs
            if not is_fresher_title_or_desc(title, desc):
                continue

            req_id = rj.get("requisition_id") or str(abs(hash(job_url)))
            opp_id = f"{company_id}_{req_id}"

            ev_job = make_evidence(
                field="requisition",
                value=req_id,
                source_url=job_url,
                evidence_text=f"Direct ATS requisition {req_id} on {platform}",
                extraction_method=f"ats_{platform.lower()}",
                confidence=1.0,
            )

            opp = Opportunity(
                opportunity_id=opp_id,
                title=title,
                company=company_name,
                opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
                role=title,
                description=desc,
                source_name=f"{platform}_OFFICIAL_FEED",
                source_listing_url=job_url,
                source_detail_url=job_url,
                employer_job_url=job_url,
                apply_url=job_url,
                all_source_urls=[job_url],
                location=[rj.get("location") or "India"],
                deadline_status=DeadlineStatus.OPEN,
                application_status=ApplicationStatus.OPEN,
                application_status_evidence=f"Active public requisition on {platform}",
                company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
                employer_verification_url=job_url,
                raw_evidence=[ev_job],
            )
            opportunities.append(opp)

    return opportunities


def discover_employer_feeds() -> List[Opportunity]:
    """Runs all Lane 3 verified employer feeds."""
    all_opps = []
    # 1. Amazon Jobs
    amz_opps = discover_amazon_jobs(max_items=25)
    all_opps.extend(amz_opps)

    # 2. Public ATS adapters
    ats_opps = discover_ats_jobs(max_per_employer=10)
    all_opps.extend(ats_opps)

    logger.info("[employer_discovery] Discovered %d verified employer opportunities", len(all_opps))
    return all_opps
