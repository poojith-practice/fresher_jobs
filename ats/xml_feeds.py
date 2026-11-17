"""
Public Teamtailor, Personio & Recruitee Feed Adapters
====================================================
Retrieves public XML / RSS job feeds from Teamtailor, Personio, and Recruitee.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from core.http_client import http_client

logger = logging.getLogger("ats.xml_feeds")


def fetch_teamtailor_rss_jobs(company_slug: str) -> List[Dict[str, Any]]:
    """Fetches public RSS feed for a Teamtailor company: https://{company}.teamtailor.com/jobs.rss"""
    url = f"https://{company_slug}.teamtailor.com/jobs.rss"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        return []

    results = []
    try:
        root = ET.fromstring(body)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            pub_date = item.findtext("pubDate")

            results.append({
                "ats_platform": "TEAMTAILOR",
                "title": title,
                "location": "India",
                "description": description,
                "job_url": link,
                "apply_url": link,
                "published_at": pub_date,
            })
    except Exception as exc:
        logger.debug("[teamtailor] XML parse error for '%s': %s", company_slug, exc)
    return results


def fetch_personio_xml_jobs(company_slug: str) -> List[Dict[str, Any]]:
    """Fetches public XML feed for Personio: https://{company}.jobs.personio.de/xml?language=en"""
    url = f"https://{company_slug}.jobs.personio.de/xml?language=en"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        return []

    results = []
    try:
        root = ET.fromstring(body)
        for position in root.findall("position"):
            job_id = position.findtext("id") or ""
            name = position.findtext("name") or ""
            office = position.findtext("office") or "India"
            schedule = position.findtext("schedule") or ""
            job_descriptions = position.find("jobDescriptions")
            desc_text = ""
            if job_descriptions is not None:
                for jd in job_descriptions.findall("jobDescription"):
                    desc_text += " " + (jd.findtext("value") or "")

            results.append({
                "ats_platform": "PERSONIO",
                "requisition_id": job_id,
                "title": name,
                "location": office,
                "employment_type": schedule,
                "description": desc_text.strip(),
                "job_url": f"https://{company_slug}.jobs.personio.de/job/{job_id}",
                "apply_url": f"https://{company_slug}.jobs.personio.de/job/{job_id}",
            })
    except Exception as exc:
        logger.debug("[personio] XML parse error for '%s': %s", company_slug, exc)
    return results


def fetch_recruitee_xml_jobs(company_slug: str) -> List[Dict[str, Any]]:
    """Fetches public XML offers from Recruitee: https://{company}.recruitee.com/api/offers.xml"""
    url = f"https://{company_slug}.recruitee.com/api/offers.xml"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        return []

    results = []
    try:
        root = ET.fromstring(body)
        for offer in root.findall("offer"):
            offer_id = offer.findtext("id") or ""
            title = offer.findtext("title") or ""
            location = offer.findtext("location") or "India"
            desc = offer.findtext("description") or ""
            careers_url = offer.findtext("careers_url") or f"https://{company_slug}.recruitee.com/o/{offer_id}"

            results.append({
                "ats_platform": "RECRUITEE",
                "requisition_id": offer_id,
                "title": title,
                "location": location,
                "description": desc,
                "job_url": careers_url,
                "apply_url": careers_url,
            })
    except Exception as exc:
        logger.debug("[recruitee] XML parse error for '%s': %s", company_slug, exc)
    return results
