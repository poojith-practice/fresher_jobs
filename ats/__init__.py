"""
ATS Adapter Hub & Resolver
==========================
Unifies public ATS adapters for Greenhouse, Lever, Ashby, SmartRecruiters,
Teamtailor, Personio, and Recruitee.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from ats.greenhouse import fetch_greenhouse_jobs
from ats.lever import fetch_lever_jobs
from ats.ashby import fetch_ashby_jobs
from ats.smartrecruiters import fetch_smartrecruiters_jobs
from ats.xml_feeds import (
    fetch_teamtailor_rss_jobs,
    fetch_personio_xml_jobs,
    fetch_recruitee_xml_jobs,
)

__all__ = [
    "fetch_greenhouse_jobs",
    "fetch_lever_jobs",
    "fetch_ashby_jobs",
    "fetch_smartrecruiters_jobs",
    "fetch_teamtailor_rss_jobs",
    "fetch_personio_xml_jobs",
    "fetch_recruitee_xml_jobs",
    "resolve_ats_from_url",
]


def resolve_ats_from_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Detects ATS platform and identifier from a job/application URL.
    Returns (platform_name, identifier) or None.
    """
    clean_url = str(url or "").lower()

    # Greenhouse: boards.greenhouse.io/{board_token}/jobs/{id}
    gh_match = re.search(r"boards\.greenhouse\.io/([^/?#]+)", clean_url)
    if gh_match:
        return ("GREENHOUSE", gh_match.group(1))

    # Lever: jobs.lever.co/{company_slug}/{id}
    lever_match = re.search(r"jobs\.lever\.co/([^/?#]+)", clean_url)
    if lever_match:
        return ("LEVER", lever_match.group(1))

    # Ashby: jobs.ashbyhq.com/{board_name}/{id}
    ashby_match = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", clean_url)
    if ashby_match:
        return ("ASHBY", ashby_match.group(1))

    # SmartRecruiters: jobs.smartrecruiters.com/{company_id}/{id}
    sr_match = re.search(r"jobs\.smartrecruiters\.com/([^/?#]+)", clean_url)
    if sr_match:
        return ("SMARTRECRUITERS", sr_match.group(1))

    return None
