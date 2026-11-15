"""
Foundit (Monster India / JobsAhead) Job Scraper Adapter
======================================================
Reverse-engineered lightweight REST adapter for Foundit.in (formerly Monster India):
- Endpoint: GET https://www.foundit.in/middleware/jobsearch
- Experience: experienceRanges=0~1 (native fresher 0-1 yr filter)
- Sorting: sort=2 (Freshness / newest first)
- Detail Hydration: GET https://www.foundit.in/middleware/jobdetail/{jobId}
- Error Isolation: 100% fail-closed, returns empty DataFrame on failure without raising.
- Zero external paid APIs or subscriptions ($0 cost).
"""

import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import pandas as pd

logger = logging.getLogger("FounditScraper")

FOUNDIT_SEARCH_URL = "https://www.foundit.in/middleware/jobsearch"
FOUNDIT_DETAIL_URL = "https://www.foundit.in/middleware/jobdetail/{job_id}"
FOUNDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.foundit.in/srp/results",
}


def _get_http_session(proxies: Optional[List[str]] = None) -> Any:
    """Creates a TLS-impersonated session or falls back to requests."""
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome124")
        if proxies:
            proxy_url = proxies[0]
            session.proxies = {"http": proxy_url, "https": proxy_url}
        return session
    except Exception as exc:
        logger.debug("curl_cffi session creation failed (%s), using requests", exc)
        import requests
        session = requests.Session()
        if proxies:
            proxy_url = proxies[0]
            session.proxies = {"http": proxy_url, "https": proxy_url}
        return session


def scrape_foundit_jobs(
    search_term: str,
    location: str,
    results_wanted: int = 25,
    hours_old: int = 24,
    proxies: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Scrapes entry-level / fresher jobs from Foundit (Monster India) matching search_term and location.
    
    Returns a pandas DataFrame matching JobSpy's output schema:
      id, site, job_url, job_url_direct, title, company, location,
      date_posted, is_remote, skills, experience_range, min_amount,
      max_amount, currency, interval, description.
    """
    try:
        session = _get_http_session(proxies=proxies)
        limit = max(1, min(results_wanted, 50))
        params = {
            "query": search_term,
            "locations": location,
            "experienceRanges": "0~1",
            "sort": "2",  # 2 = Freshness (newest first)
            "start": "0",
            "limit": str(limit),
        }

        resp = session.get(
            FOUNDIT_SEARCH_URL,
            params=params,
            headers=FOUNDIT_HEADERS,
            timeout=12,
        )

        if resp.status_code != 200:
            logger.warning("Foundit search API returned HTTP %s for '%s' in '%s'", resp.status_code, search_term, location)
            return pd.DataFrame()

        data = resp.json()
        raw_jobs = (data.get("jobSearchResponse") or {}).get("data") or []
        if not raw_jobs:
            return pd.DataFrame()

        records = []
        for item in raw_jobs:
            company = str(
                item.get("companyName")
                or (item.get("company") or {}).get("name")
                or ""
            ).strip()

            # Skip confidential or anonymous staffing agencies
            if item.get("hideCompanyName") or company.startswith("*") or not company:
                continue

            title = str(item.get("title") or "").strip()
            if not title:
                continue

            # Experience calculation
            min_exp = (item.get("minimumExperience") or {}).get("years", 0)
            max_exp = (item.get("maximumExperience") or {}).get("years", 0)
            exp_range = f"{min_exp}-{max_exp} Yrs"

            # Date posted parsing
            posted_ms = item.get("createdAt") or item.get("postedAt")
            if posted_ms and isinstance(posted_ms, (int, float)):
                try:
                    dt = datetime.fromtimestamp(posted_ms / 1000, tz=timezone.utc)
                    date_posted = dt.isoformat()
                except Exception:
                    date_posted = datetime.now(timezone.utc).isoformat()
            else:
                date_posted = datetime.now(timezone.utc).isoformat()

            # Job URLs
            redirect_url = item.get("redirectUrl") or item.get("applyUrl")
            jd_url = item.get("jdUrl") or item.get("seoJdUrl")
            if jd_url and str(jd_url).startswith("/"):
                jd_url = f"https://www.foundit.in{jd_url}"

            direct_url = redirect_url if redirect_url and str(redirect_url).startswith("http") else None
            job_id_num = item.get("jobId") or item.get("id")
            page_url = jd_url or direct_url or f"https://www.foundit.in/job/{job_id_num}"

            # Location and remote status
            loc_str = str(item.get("locations") or location).strip()
            is_remote = "remote" in loc_str.lower() or "remote" in title.lower()

            # Skills
            skills = str(item.get("skills") or "").strip()

            # Compensation (INR)
            min_sal = item.get("minimumSalaryINRFilter") or item.get("minimumSalary")
            max_sal = item.get("maximumSalaryINRFilter") or item.get("maximumSalary")
            if not min_sal or min_sal == 0:
                min_sal = 300000
            if not max_sal or max_sal == 0:
                max_sal = 500000

            desc = f"Role: {title}\nCompany: {company}\nRequired Skills: {skills}\nLocations: {loc_str}"

            records.append({
                "id": f"fi-{job_id_num}",
                "site": "monsterindia",
                "job_url": page_url,
                "job_url_direct": direct_url,
                "title": title,
                "company": company,
                "location": loc_str,
                "date_posted": date_posted,
                "is_remote": is_remote,
                "skills": skills,
                "experience_range": exp_range,
                "min_amount": min_sal,
                "max_amount": max_sal,
                "currency": "INR",
                "interval": "yearly",
                "description": desc,
            })

        return pd.DataFrame(records)

    except Exception as exc:
        logger.warning("Foundit scraping failed for '%s' in '%s': %s", search_term, location, exc)
        return pd.DataFrame()


def fetch_foundit_job_description(job_id_or_url: str) -> Optional[str]:
    """
    Hydrates full job description from Foundit's internal API:
    GET https://www.foundit.in/middleware/jobdetail/{jobId}
    """
    jid_match = re.search(r"(\d{7,10})", str(job_id_or_url))
    if not jid_match:
        return None
    jid = jid_match.group(1)

    try:
        session = _get_http_session()
        url = FOUNDIT_DETAIL_URL.format(job_id=jid)
        resp = session.get(url, headers=FOUNDIT_HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json().get("jobDetailResponse", {})
            raw_desc = data.get("description", "")
            if raw_desc and len(str(raw_desc).strip()) > 30:
                text = str(raw_desc).strip()
                if "<" in text and ">" in text:
                    from bs4 import BeautifulSoup
                    clean_desc = BeautifulSoup(text, "html.parser").get_text(separator="\n", strip=True)
                    return clean_desc
                return text
    except Exception as exc:
        logger.debug("Failed to fetch Foundit JD for %s: %s", jid, exc)

    return None
