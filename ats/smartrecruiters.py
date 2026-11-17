"""
Public SmartRecruiters Postings Adapter
=======================================
Endpoint: https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings
Retrieves live, unauthenticated job postings from SmartRecruiters and fetches
detailed requisition descriptions and qualifications.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from core.http_client import http_client

logger = logging.getLogger("ats.smartrecruiters")


def fetch_posting_detail(company_id: str, posting_id: str) -> Optional[str]:
    """Fetches full job description and qualifications for a SmartRecruiters posting."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{posting_id}"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        return None
    try:
        data = json.loads(body)
        sections = data.get("jobAd", {}).get("sections", {})
        texts = []
        for sec_name in ["jobDescription", "qualifications", "additionalInformation"]:
            sec_html = sections.get(sec_name, {}).get("text") or ""
            if sec_html:
                clean_sec = BeautifulSoup(sec_html, "html.parser").get_text("\n", strip=True)
                if clean_sec:
                    texts.append(clean_sec)
        return "\n\n".join(texts) if texts else None
    except Exception as exc:
        logger.debug("[smartrecruiters] Failed to parse detail for %s: %s", posting_id, exc)
        return None


def fetch_smartrecruiters_jobs(company_id: str, fetch_details: bool = True) -> List[Dict[str, Any]]:
    """Fetches public published postings for a SmartRecruiters company identifier."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.debug("[smartrecruiters] Failed to fetch company '%s': status %d (%s)", company_id, status, outcome)
        return []

    try:
        data = json.loads(body)
        raw_content = data.get("content", [])
        results = []
        for p in raw_content:
            posting_id = str(p.get("id") or "")
            title = p.get("name") or ""
            location_obj = p.get("location") or {}
            city = location_obj.get("city") or "India"
            country = location_obj.get("country") or ""
            loc_str = f"{city}, {country}".strip(" ,")
            apply_url = f"https://jobs.smartrecruiters.com/{company_id}/{posting_id}"

            desc = title
            is_candidate = any(k in title.lower() for k in ["engineer", "developer", "trainee", "graduate", "intern", "associate", "analyst"])
            if fetch_details and posting_id and is_candidate:
                full_desc = fetch_posting_detail(company_id, posting_id)
                if full_desc:
                    desc = f"{title}\n\n{full_desc}"

            results.append({
                "ats_platform": "SMARTRECRUITERS",
                "requisition_id": posting_id,
                "title": title,
                "location": loc_str,
                "description": desc,
                "job_url": apply_url,
                "apply_url": apply_url,
                "released_date": p.get("releasedDate"),
            })
        return results
    except Exception as exc:
        logger.warning("[smartrecruiters] Error parsing company '%s': %s", company_id, exc)
        return []
