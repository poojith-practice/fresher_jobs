"""
Off-Campus Recruitment Drives & Fresher Job Scrapers
===================================================
Production adapters for high-yield Indian fresher and off-campus recruitment platforms:
1. JoinSaarthi (joinsaarthi.com/drives/off-campus) - Next.js __NEXT_DATA__ JSON
2. CampusDrive.in (campusdrive.in/jobs) - Structured WhatsApp Card Extraction
3. eLitmus (elitmus.com/jobs) - Corporate Trainee & Graduate Assessment
4. UseAstra (useastra.in/jobs/off-campus-drives) - Structured Off-Campus Cards
5. Jobs4Fresher (jobs4fresher.com) - Daily Curated Corporate Fresher Roles
6. Hirastra (hirastra.com/category/off-campus-drive) - Recruitment Drive Cards
7. Amazon Careers (amazon.jobs) - Official Public Unauthenticated JSON API
"""

import json
import logging
import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as curl_requests
    HAS_CURL_CFFI = False

logger = logging.getLogger("OffCampusScrapers")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _safe_fetch(url: str, timeout: int = 12) -> Optional[str]:
    """Fetches HTML with TLS impersonation or fallback requests."""
    try:
        if HAS_CURL_CFFI:
            resp = curl_requests.get(url, headers=HEADERS, timeout=timeout, impersonate="chrome120")
        else:
            resp = curl_requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        logger.warning("Fetch returned status %s for %s", resp.status_code, url)
    except Exception as exc:
        logger.warning("Fetch error for %s: %s", url, exc)
    return None


# ==============================================================================
# 1. JoinSaarthi Scraper (Next.js __NEXT_DATA__ JSON)
# ==============================================================================
def scrape_saarthi_drives(limit: int = 25) -> List[Dict[str, Any]]:
    """Extracts structured off-campus drives directly from JoinSaarthi Next.js payload."""
    url = "https://joinsaarthi.com/drives/off-campus"
    html = _safe_fetch(url)
    if not html:
        return []

    results = []
    try:
        soup = BeautifulSoup(html, "lxml")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag or not script_tag.string:
            return []

        data = json.loads(script_tag.string)
        initial = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialDrives", [])
        )
        drives = initial.get("data", []) if isinstance(initial, dict) else initial

        for d in drives[:limit]:
            if d.get("isDriveEnded") is True:
                continue

            drive_id = d.get("id", "")
            title = d.get("drive_name") or "Off-Campus Drive"
            comp_obj = d.get("company") or {}
            company = comp_obj.get("name") or d.get("college_controlled_drive_company_name") or "Top IT Employer"
            locations = d.get("locations") or []
            loc_str = ", ".join(locations) if locations else "Pan India"
            desc = d.get("description") or d.get("eligibility_criteria") or ""

            # Check batches
            batches = re.findall(r"\b202\d\b", f"{title} {desc}")
            batches = list(dict.fromkeys(batches))

            apply_url = f"https://joinsaarthi.com/drives/{drive_id}" if drive_id else url

            results.append({
                "title": title,
                "company": company,
                "location": loc_str,
                "site": "SAARTHI_DRIVES",
                "date_posted": d.get("created_at") or d.get("start_date") or datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": desc,
                "opportunity_type": "OFF_CAMPUS_DRIVE",
                "eligible_batches": batches or ["2025", "2026"],
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": d.get("ctc_min") or "Best in Industry",
                "max_amount": d.get("ctc_max") or "Best in Industry",
                "deadline": d.get("end_date"),
                "deadline_status": "OPEN",
                "raw_metadata": d,
            })
    except Exception as exc:
        logger.warning("[saarthi_drives] Parsing error: %s", exc)

    return results


# ==============================================================================
# 2. CampusDrive.in Scraper (Structured WhatsApp Cards)
# ==============================================================================
def scrape_campusdrive_jobs(limit: int = 25) -> List[Dict[str, Any]]:
    """Extracts high-fidelity off-campus cards from CampusDrive.in."""
    url = "https://campusdrive.in/jobs"
    html = _safe_fetch(url)
    if not html:
        return []

    results = []
    try:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".card, article, .job-item, .post")
        if not cards:
            cards = soup.select("div.col-md-4, div.col-lg-4, div.p-4")

        for card in cards[:limit]:
            title_elem = card.select_one("h2, h3, h4, .card-title")
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                continue

            link_elem = card.find("a", href=True)
            apply_url = link_elem["href"] if link_elem else url
            if apply_url.startswith("/"):
                apply_url = f"https://campusdrive.in{apply_url}"

            # Parse structured WhatsApp share parameters if present
            company = title.split()[0] if title.split() else "Campus Hiring"
            location = "Pan India"
            salary = "Best in Industry"
            batches = ["2025", "2026"]

            wa_link = card.find("a", href=re.compile(r"whatsapp://|api\.whatsapp\.com"))
            if wa_link and wa_link.has_attr("href"):
                parsed = urllib.parse.urlparse(wa_link["href"])
                qs = urllib.parse.parse_qs(parsed.query)
                wa_text = qs.get("text", [""])[0] or urllib.parse.unquote(wa_link["href"])

                m_comp = re.search(r"Company\s*:\s*([^\n\r]+)", wa_text, re.I)
                if m_comp:
                    company = m_comp.group(1).strip()
                m_loc = re.search(r"Location\s*:\s*([^\n\r]+)", wa_text, re.I)
                if m_loc:
                    location = m_loc.group(1).strip()
                m_pkg = re.search(r"Package\s*:\s*([^\n\r]+)", wa_text, re.I)
                if m_pkg:
                    salary = m_pkg.group(1).strip()
                m_batch = re.findall(r"\b202\d\b", wa_text)
                if m_batch:
                    batches = list(dict.fromkeys(m_batch))

            results.append({
                "title": title,
                "company": company,
                "location": location,
                "site": "CAMPUSDRIVE",
                "date_posted": datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": f"{title} | Location: {location} | Batch: {', '.join(batches)} | Package: {salary}",
                "opportunity_type": "OFF_CAMPUS_DRIVE",
                "eligible_batches": batches,
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": salary,
                "max_amount": salary,
                "deadline_status": "OPEN",
            })
    except Exception as exc:
        logger.warning("[campusdrive] Parsing error: %s", exc)

    return results


# ==============================================================================
# 3. eLitmus Scraper (Corporate Assessment & Trainee Hiring)
# ==============================================================================
def scrape_elitmus_jobs(limit: int = 25) -> List[Dict[str, Any]]:
    """Scrapes curated entry-level trainee and fresher openings from eLitmus."""
    url = "https://www.elitmus.com/jobs"
    html = _safe_fetch(url)
    if not html:
        return []

    results = []
    try:
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select(".job-list-item, .table tbody tr, article.job, .card")
        if not rows:
            rows = soup.select("div[id^='job_'], tr[id^='job_']")

        for r in rows[:limit]:
            title_elem = r.select_one("a.title, h3 a, h2 a, a[href*='/jobs/']")
            if not title_elem:
                title_elem = r.find("a", href=True)
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            href = title_elem.get("href", "")
            apply_url = f"https://www.elitmus.com{href}" if href.startswith("/") else href

            comp_elem = r.select_one(".company, .employer, td:nth-child(2)")
            company = comp_elem.get_text(strip=True) if comp_elem else "eLitmus Corporate Partner"

            loc_elem = r.select_one(".location, td:nth-child(3)")
            location = loc_elem.get_text(strip=True) if loc_elem else "Bangalore"

            sal_elem = r.select_one(".salary, td:nth-child(4)")
            salary = sal_elem.get_text(strip=True) if sal_elem else "Best in Industry"

            results.append({
                "title": title,
                "company": company,
                "location": location,
                "site": "ELITMUS",
                "date_posted": datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": f"{title} at {company}. Location: {location} | Package: {salary}. Curated entry-level opening on eLitmus.",
                "opportunity_type": "INDIVIDUAL_FRESHER_JOB",
                "eligible_batches": ["2025", "2026"],
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": salary,
                "max_amount": salary,
                "deadline_status": "OPEN",
            })
    except Exception as exc:
        logger.warning("[elitmus] Parsing error: %s", exc)

    return results


# ==============================================================================
# 4. UseAstra Scraper (Off-Campus Drives)
# ==============================================================================
def scrape_useastra_drives(limit: int = 25) -> List[Dict[str, Any]]:
    """Extracts walk-in and off-campus drives from UseAstra."""
    url = "https://www.useastra.in/jobs/off-campus-drives"
    html = _safe_fetch(url)
    if not html:
        return []

    results = []
    seen_links = set()
    try:
        soup = BeautifulSoup(html, "lxml")
        links = soup.find_all("a", href=re.compile(r"/jobs/[a-zA-Z0-9_-]+"))
        for a in links:
            href = a["href"].split("?")[0].strip()
            if href in seen_links or href.endswith("/jobs/off-campus-drives"):
                continue

            title = a.get_text(strip=True)
            if len(title) < 8 or title.lower() in {"apply", "view job", "details", "read more"}:
                continue

            seen_links.add(href)
            apply_url = href if href.startswith("http") else f"https://www.useastra.in{href}"

            company = "Enterprise"
            if " at " in title:
                parts = title.split(" at ")
                company = parts[1].strip()
            elif "Off Campus" in title:
                company = title.split("Off Campus")[0].strip()
            elif title.split():
                company = title.split()[0].strip()

            parent = a.find_parent(["div", "article", "li"])
            snippet = parent.get_text(" ", strip=True) if parent else ""
            batches = re.findall(r"\b202\d\b", f"{title} {snippet}")

            results.append({
                "title": title,
                "company": company,
                "location": "Pan India",
                "site": "USEASTRA",
                "date_posted": datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": f"{title} - Off-campus drive by {company}. {snippet[:300]}",
                "opportunity_type": "OFF_CAMPUS_DRIVE",
                "eligible_batches": batches or ["2025", "2026"],
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": "Best in Industry",
                "max_amount": "Best in Industry",
                "deadline_status": "OPEN",
            })
            if len(results) >= limit:
                break
    except Exception as exc:
        logger.warning("[useastra] Parsing error: %s", exc)

    return results


# ==============================================================================
# 5. Jobs4Fresher Scraper
# ==============================================================================
def scrape_jobs4fresher(limit: int = 25) -> List[Dict[str, Any]]:
    """Extracts curated corporate fresher opportunities from Jobs4Fresher."""
    url = "https://jobs4fresher.com"
    html = _safe_fetch(url)
    if not html:
        return []

    results = []
    try:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article, .post, .entry-title a")
        for card in cards[:limit]:
            title_elem = card.select_one(".entry-title a") or card
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title or len(title) < 5:
                continue

            apply_url = title_elem.get("href") if title_elem.has_attr("href") else url

            company_match = re.search(r"^([A-Za-z0-9\s&]+?)(?:\s+Recruitment|\s+Off[\s-]?Campus|\s+Hiring|\s+is\s+Hiring)", title, re.I)
            company = company_match.group(1).strip() if company_match else title.split()[0]

            batches = re.findall(r"\b202\d\b", title)

            results.append({
                "title": title,
                "company": company,
                "location": "Pan India",
                "site": "JOBS4FRESHER",
                "date_posted": datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": f"{title} - Fresher hiring announcement on Jobs4Fresher for engineering and graduate freshers.",
                "opportunity_type": "OFF_CAMPUS_DRIVE" if "drive" in title.lower() else "INDIVIDUAL_FRESHER_JOB",
                "eligible_batches": batches or ["2025", "2026"],
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": "Best in Industry",
                "max_amount": "Best in Industry",
                "deadline_status": "OPEN",
            })
    except Exception as exc:
        logger.warning("[jobs4fresher] Parsing error: %s", exc)

    return results


# ==============================================================================
# 6. Hirastra Scraper
# ==============================================================================
def scrape_hirastra_drives(limit: int = 25) -> List[Dict[str, Any]]:
    """Scrapes off-campus recruitment announcements from Hirastra."""
    url = "https://hirastra.com/off-campus-drives"
    html = _safe_fetch(url)
    if not html:
        url = "https://hirastra.com"
        html = _safe_fetch(url)
    if not html:
        return []

    results = []
    try:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article, .post-card, .entry-card, h2.entry-title a")
        for card in cards[:limit]:
            title_elem = card.select_one(".entry-title a") or card
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title or len(title) < 5:
                continue

            apply_url = title_elem.get("href") if title_elem.has_attr("href") else url
            company = title.split()[0] if title.split() else "Enterprise"
            batches = re.findall(r"\b202\d\b", title)

            results.append({
                "title": title,
                "company": company,
                "location": "Pan India",
                "site": "HIRASTRA",
                "date_posted": datetime.utcnow().strftime("%Y-%m-%d"),
                "job_url_direct": apply_url,
                "job_url": apply_url,
                "description": f"{title} - Off-campus drive published on Hirastra.",
                "opportunity_type": "OFF_CAMPUS_DRIVE",
                "eligible_batches": batches or ["2025", "2026"],
                "experience_range": "Fresher (0-1 Years)",
                "min_amount": "Best in Industry",
                "max_amount": "Best in Industry",
                "deadline_status": "OPEN",
            })
    except Exception as exc:
        logger.warning("[hirastra] Parsing error: %s", exc)

    return results


# ==============================================================================
# 7. Amazon Careers Scraper (Official Public REST JSON Endpoint)
# ==============================================================================
def scrape_amazon_fresher_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Scrapes entry-level roles directly from Amazon's official JSON search API."""
    url = "https://www.amazon.jobs/en/search.json?base_query=Fresher&country=IND&result_limit=20"
    results = []
    try:
        if HAS_CURL_CFFI:
            resp = curl_requests.get(url, headers=HEADERS, timeout=12, impersonate="chrome120")
        else:
            resp = curl_requests.get(url, headers=HEADERS, timeout=12)

        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("jobs", [])
            for j in jobs[:limit]:
                title = j.get("title", "")
                job_id = j.get("id_icims") or j.get("id") or ""
                city = j.get("city") or "Bangalore"
                country = j.get("country_code") or "IND"
                location = f"{city}, {country}"
                desc = j.get("description") or j.get("basic_qualifications") or ""
                apply_url = f"https://www.amazon.jobs/en/jobs/{job_id}" if job_id else "https://www.amazon.jobs"

                results.append({
                    "title": title,
                    "company": "Amazon",
                    "location": location,
                    "site": "AMAZON_CAREERS",
                    "date_posted": j.get("posted_date") or datetime.utcnow().strftime("%Y-%m-%d"),
                    "job_url_direct": apply_url,
                    "job_url": apply_url,
                    "description": f"{title} at Amazon. Location: {location}. {desc[:500]}",
                    "opportunity_type": "INDIVIDUAL_FRESHER_JOB",
                    "eligible_batches": ["2025", "2026"],
                    "experience_range": "Fresher (0-1 Years)",
                    "min_amount": "Best in Industry",
                    "max_amount": "Best in Industry",
                    "deadline_status": "OPEN",
                    "raw_metadata": j,
                })
    except Exception as exc:
        logger.warning("[amazon_careers] Parsing error: %s", exc)

    return results


# ==============================================================================
# Master Dispatcher for All 7 Off-Campus & Corporate Sources
# ==============================================================================
def scrape_all_off_campus_sources(limit_per_source: int = 15) -> List[Dict[str, Any]]:
    """Executes all 7 off-campus and corporate fresher scrapers with error isolation."""
    all_opportunities: List[Dict[str, Any]] = []

    sources = [
        ("saarthi_drives", scrape_saarthi_drives),
        ("campusdrive", scrape_campusdrive_jobs),
        ("elitmus", scrape_elitmus_jobs),
        ("useastra", scrape_useastra_drives),
        ("jobs4fresher", scrape_jobs4fresher),
        ("hirastra", scrape_hirastra_drives),
        ("amazon_jobs", scrape_amazon_fresher_jobs),
    ]

    for name, scraper_fn in sources:
        try:
            logger.info("Executing off-campus scraper: %s (limit=%d)...", name, limit_per_source)
            items = scraper_fn(limit=limit_per_source)
            logger.info("-> [%s] Successfully collected %d opportunities.", name, len(items))
            all_opportunities.extend(items)
        except Exception as exc:
            logger.error("-> [%s] Scraper failed with error: %s", name, exc)

    return all_opportunities
