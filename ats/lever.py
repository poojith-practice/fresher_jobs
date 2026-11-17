"""
Public Lever Postings Adapter
=============================
Endpoint: https://api.lever.co/v0/postings/{company_slug}?mode=json
Retrieves live, unauthenticated job postings directly from Lever ATS.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from core.http_client import http_client

logger = logging.getLogger("ats.lever")


def fetch_lever_jobs(company_slug: str) -> List[Dict[str, Any]]:
    """Fetches public published jobs for a Lever company slug."""
    if not company_slug or company_slug == "None":
        return []
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        # Try EU endpoint fallback
        eu_url = f"https://api.eu.lever.co/v0/postings/{company_slug}?mode=json"
        body, status, outcome = http_client.get(eu_url)
        if status != 200 or not body:
            logger.debug("[lever] Failed to fetch slug '%s': status %d (%s)", company_slug, status, outcome)
            return []

    try:
        raw_postings = json.loads(body)
        if not isinstance(raw_postings, list):
            return []

        results = []
        for p in raw_postings:
            posting_id = str(p.get("id") or "")
            title = p.get("text") or ""
            categories = p.get("categories") or {}
            location = categories.get("location") or "India"
            team = categories.get("team") or ""
            commitment = categories.get("commitment") or ""
            hosted_url = p.get("hostedUrl") or f"https://jobs.lever.co/{company_slug}/{posting_id}"
            apply_url = p.get("applyUrl") or hosted_url
            desc = p.get("descriptionPlain") or p.get("description") or ""

            results.append({
                "ats_platform": "LEVER",
                "requisition_id": posting_id,
                "title": title,
                "location": location,
                "team": team,
                "employment_type": commitment,
                "description": desc,
                "job_url": hosted_url,
                "apply_url": apply_url,
                "created_at": p.get("createdAt"),
            })
        return results
    except Exception as exc:
        logger.warning("[lever] Error parsing postings for '%s': %s", company_slug, exc)
        return []
