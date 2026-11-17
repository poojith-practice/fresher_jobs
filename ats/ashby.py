"""
Public Ashby Job Board Adapter
==============================
Endpoint: https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true
Retrieves live, unauthenticated job postings directly from Ashby ATS.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from core.http_client import http_client

logger = logging.getLogger("ats.ashby")


def fetch_ashby_jobs(board_name: str) -> List[Dict[str, Any]]:
    """Fetches public published jobs for an Ashby job board name."""
    if not board_name or board_name == "None":
        return []
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.debug("[ashby] Failed to fetch board '%s': status %d (%s)", board_name, status, outcome)
        return []

    try:
        data = json.loads(body)
        raw_jobs = data.get("jobs", [])
        results = []
        for j in raw_jobs:
            job_id = str(j.get("id") or "")
            title = j.get("title") or ""
            location = j.get("location") or "India"
            desc = j.get("descriptionHtml") or j.get("descriptionPlain") or ""
            job_url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board_name}/{job_id}"
            apply_url = j.get("applyUrl") or job_url
            published_at = j.get("publishedAt")

            results.append({
                "ats_platform": "ASHBY",
                "requisition_id": job_id,
                "title": title,
                "location": location,
                "department": j.get("department"),
                "description": desc,
                "job_url": job_url,
                "apply_url": apply_url,
                "published_at": published_at,
            })
        return results
    except Exception as exc:
        logger.warning("[ashby] Error parsing board '%s': %s", board_name, exc)
        return []
