"""
Public Greenhouse Job Board Adapter
====================================
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Retrieves live, unauthenticated job listings directly from Greenhouse ATS.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from core.http_client import http_client

logger = logging.getLogger("ats.greenhouse")


def fetch_greenhouse_jobs(board_token: str) -> List[Dict[str, Any]]:
    """Fetches public published jobs for a Greenhouse board token."""
    if not board_token or board_token == "None":
        return []
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.debug("[greenhouse] Failed to fetch board '%s': status %d (%s)", board_token, status, outcome)
        return []

    try:
        data = json.loads(body)
        raw_jobs = data.get("jobs", [])
        results = []
        for j in raw_jobs:
            job_id = str(j.get("id") or "")
            title = j.get("title") or ""
            content = j.get("content") or ""
            location_obj = j.get("location") or {}
            location_name = location_obj.get("name") or "India"
            job_url = j.get("absolute_url") or f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"

            results.append({
                "ats_platform": "GREENHOUSE",
                "requisition_id": job_id,
                "title": title,
                "location": location_name,
                "description": content,
                "job_url": job_url,
                "apply_url": job_url,
                "departments": [d.get("name") for d in j.get("departments", []) if d.get("name")],
                "updated_at": j.get("updated_at"),
            })
        return results
    except Exception as exc:
        logger.warning("[greenhouse] Error parsing board '%s': %s", board_token, exc)
        return []
