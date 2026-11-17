"""Source Research & Discovery Probe for Coverage Lab.

Systematically probes all requested and candidate job/drive sources
using realistic browser TLS fingerprinting (curl_cffi / primp / httpx)
and reports status, redirects, anti-bot gates, and content structure.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("source_research")

TARGETS = [
    # A. Mandatory requested sites
    {"id": "imsjobs_test", "name": "IMS Jobs (imsjobs.com)", "url": "https://www.imsjobs.com", "category": "aggregator"},
    {"id": "iimjobs_test", "name": "IIM Jobs (iimjobs.com)", "url": "https://www.iimjobs.com/fresher-jobs", "category": "job_board"},
    {"id": "campusdrive", "name": "CampusDrive.in", "url": "https://campusdrive.in/jobs", "category": "off_campus_aggregator"},
    {"id": "elitmus", "name": "eLitmus", "url": "https://www.elitmus.com/jobs", "category": "assessment_platform"},
    {"id": "saarthi_explore", "name": "JoinSaarthi Explore", "url": "https://joinsaarthi.com/explore", "category": "off_campus_aggregator"},
    {"id": "saarthi_drives", "name": "JoinSaarthi Drives", "url": "https://joinsaarthi.com/drives/off-campus", "category": "off_campus_aggregator"},
    {"id": "useastra", "name": "UseAstra", "url": "https://www.useastra.in/jobs/off-campus-drives", "category": "off_campus_aggregator"},
    {"id": "freshersdunia", "name": "FreshersDunia", "url": "https://freshersdunia.in", "category": "off_campus_blog"},
    {"id": "jobs4fresher", "name": "Jobs4Fresher", "url": "https://jobs4fresher.com", "category": "off_campus_blog"},
    # B. Candidate sites
    {"id": "hirastra", "name": "Hirastra", "url": "https://hirastra.com/off-campus-drives", "category": "off_campus_aggregator"},
    {"id": "freshersnow", "name": "FreshersNow", "url": "https://www.freshersnow.com/off-campus-drives/", "category": "off_campus_blog"},
    {"id": "prepinsta", "name": "PrepInsta", "url": "https://prepinsta.com/off-campus-drive/", "category": "off_campus_blog"},
    # C. Official career portals sample
    {"id": "tcs_careers", "name": "TCS Careers", "url": "https://www.tcs.com/careers/india", "category": "official_career_portal"},
    {"id": "infosys_careers", "name": "Infosys Careers", "url": "https://career.infosys.com/joblist", "category": "official_career_portal"},
    {"id": "wipro_careers", "name": "Wipro Careers", "url": "https://careers.wipro.com/careers-home/", "category": "official_career_portal"},
    {"id": "cognizant_careers", "name": "Cognizant Careers", "url": "https://careers.cognizant.com/global/en", "category": "official_career_portal"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}


def probe_target(target: Dict[str, str]) -> Dict[str, Any]:
    url = target["url"]
    tid = target["id"]
    name = target["name"]
    res = {
        "id": tid,
        "name": name,
        "url": url,
        "category": target["category"],
        "status_code": 0,
        "final_url": url,
        "content_length": 0,
        "has_anti_bot": False,
        "anti_bot_details": None,
        "title": None,
        "sample_links": [],
        "verdict": "UNKNOWN",
        "notes": "",
    }
    logger.info("Probing %s (%s)...", name, url)
    try:
        response = cffi_requests.get(
            url,
            headers=HEADERS,
            impersonate="chrome124",
            timeout=15,
            allow_redirects=True,
        )
        res["status_code"] = response.status_code
        res["final_url"] = str(response.url)
        content = response.text or ""
        res["content_length"] = len(content)

        soup = BeautifulSoup(content[:150000], "html.parser")
        if soup.title and soup.title.string:
            res["title"] = soup.title.string.strip()

        # Check for Cloudflare / Anti-bot challenges
        lower_content = content.lower()
        if "cf-browser-verification" in lower_content or "challenge-running" in lower_content or "just a moment..." in lower_content:
            res["has_anti_bot"] = True
            res["anti_bot_details"] = "Cloudflare Challenge Interstitial"
            res["verdict"] = "BLOCKED_BY_CF"
        elif response.status_code == 403:
            res["has_anti_bot"] = True
            res["anti_bot_details"] = "HTTP 403 Forbidden"
            res["verdict"] = "FORBIDDEN"
        elif response.status_code == 200:
            res["verdict"] = "ACCESSIBLE"
            # Extract sample links to inspect structure
            anchors = soup.find_all("a", href=True)
            sample_hrefs = []
            for a in anchors:
                href = a["href"].strip()
                if any(x in href.lower() for x in ["job", "drive", "career", "fresher", "apply"]):
                    sample_hrefs.append(href)
                if len(sample_hrefs) >= 10:
                    break
            res["sample_links"] = sample_hrefs[:10]
        else:
            res["verdict"] = f"HTTP_{response.status_code}"

    except Exception as exc:
        res["status_code"] = -1
        res["verdict"] = "ERROR"
        res["notes"] = str(exc)
        logger.warning("Probe error for %s: %s", name, exc)

    return res


def run_full_source_audit() -> str:
    """Executes full source audit across all target platforms and persists probe results."""
    results = []
    for target in TARGETS:
        results.append(probe_target(target))
        time.sleep(0.5)

    out_path = "fresher_job_scraper_coverage_lab/data/raw/source_probe_results.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not save raw probe results to %s: %s", out_path, exc)
    return out_path


def main():
    out_path = run_full_source_audit()


if __name__ == "__main__":
    main()
