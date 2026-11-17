"""
Jobs4Fresher & FreshersDunia Scrapers & Detail Extractors
=========================================================
Lane 1 Discovery adapters for Jobs4Fresher and FreshersDunia.
Performs two-stage extraction: discovers individual post links, visits candidate
detail pages to extract true Job Role, Company, Qualifications, and Outbound Apply URLs.
Strictly filters out category archives, tag links, and site navigation menus.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from core.http_client import http_client
from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
)
from core.evidence import make_evidence

logger = logging.getLogger("scrapers.blogs")

IGNORED_URL_PATTERNS = [
    r"/category/", r"/tag/", r"/by-batch/", r"/by-qualification/", r"/by-location/",
    r"/resume-builder/", r"/free-courses/", r"/privacy-policy/", r"/contact-us/",
    r"/about-us/", r"/interview-questions/", r"/work-from-home/", r"/freshers-job/$",
    r"/off-campus-drive/$", r"/page/\d+",
]

SOCIAL_SHARE_DOMAINS = [
    "facebook.com", "twitter.com", "linkedin.com/share", "whatsapp:", "telegram.me",
    "pinterest.com", "reddit.com",
]


def _is_nav_or_category_url(url: str) -> bool:
    """Checks whether a URL is a navigation, category, or non-job page."""
    u_lower = url.lower()
    for pat in IGNORED_URL_PATTERNS:
        if re.search(pat, u_lower):
            return True
    return False


def extract_jobs4fresher_detail(detail_url: str) -> Optional[Dict[str, Any]]:
    """Fetches and parses a Jobs4Fresher detail page."""
    body, status, outcome = http_client.get(detail_url)
    if status != 200 or not body:
        logger.debug("[jobs4fresher] Detail fetch failed for %s: %s", detail_url, outcome)
        return None

    soup = BeautifulSoup(body, "html.parser")
    h1 = soup.find("h1")
    raw_h1 = h1.get_text(strip=True) if h1 else ""
    if not raw_h1:
        return None

    page_text = soup.get_text(" ", strip=True)

    # 1. Extract Role
    role = ""
    role_m = re.search(
        r"Job\s*Role\s*[:\-–—]?\s*([A-Za-z0-9\s/–—&+-]+?)(?:\s*(?:Qualification|Experience|Job\s*Location|Batch|Salary)|\.|\n|$)",
        page_text,
        re.I,
    )
    if role_m:
        role = role_m.group(1).strip()
    if not role:
        role = raw_h1

    # 2. Extract Company
    company = ""
    comp_m = re.search(r"^([^|–—-]+?)\s*(?:Recruitment|Hiring|Off\s*Campus|Careers|Internship)", raw_h1, re.I)
    if comp_m:
        company = comp_m.group(1).strip()
    if not company:
        comp_m2 = re.search(r"Company\s*[:\-–—]?\s*([A-Za-z0-9\s/–—&+-]+?)(?:\s*(?:Job\s*Role|Qualification|Experience)|\.|\n|$)", page_text, re.I)
        if comp_m2:
            company = comp_m2.group(1).strip()
    if not company and raw_h1.split():
        company = raw_h1.split()[0].strip()

    # 3. Extract Batches
    batches = [int(b) for b in re.findall(r"\b202[4-8]\b", page_text)]
    batches = sorted(list(set(batches)))

    # 4. Outbound Apply Link
    apply_url = detail_url
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text(strip=True).lower()
        if any(dom in href.lower() for dom in SOCIAL_SHARE_DOMAINS):
            continue
        if "jobs4fresher.com" in href.lower() or href.startswith("#"):
            continue
        if any(kw in link_text for kw in ["click here to apply", "apply now", "apply online", "official link", "direct link"]):
            apply_url = href
            break
        elif "jobs." in href or "careers." in href:
            apply_url = href

    # 5. Check premature closure in URL or text
    app_status = ApplicationStatus.OPEN
    deadline_status = DeadlineStatus.UNKNOWN
    if any(cl in apply_url.lower() for cl in ["closedjob", "/closed", "job-closed", "expired"]):
        app_status = ApplicationStatus.CLOSED
        deadline_status = DeadlineStatus.CLOSED
    elif re.search(r"\b(?:application[s]?|registration[s]?)\s+(?:are|is|now)\s+closed\b", page_text, re.I):
        app_status = ApplicationStatus.CLOSED
        deadline_status = DeadlineStatus.CLOSED

    # 6. Content description
    entry_content = soup.find("div", class_=lambda c: c and "entry-content" in c)
    desc = entry_content.get_text("\n", strip=True) if entry_content else page_text[:2000]

    return {
        "title": role if role != raw_h1 else raw_h1,
        "company": company,
        "role": role,
        "description": desc,
        "apply_url": apply_url,
        "batches": batches,
        "app_status": app_status,
        "deadline_status": deadline_status,
    }


def scrape_jobs4fresher(limit: int = 15) -> List[Opportunity]:
    """Scrapes candidate listings from Jobs4Fresher.com with detail parsing."""
    url = "https://jobs4fresher.com"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[jobs4fresher] Failed to fetch index: status %d (%s)", status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    opportunities: List[Opportunity] = []
    seen_urls = set()

    articles = soup.find_all("article")
    for art in articles:
        a = art.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if href in seen_urls or not href.startswith("http") or _is_nav_or_category_url(href):
            continue
        seen_urls.add(href)

        detail = extract_jobs4fresher_detail(href)
        if not detail:
            continue

        opp_id = f"j4f_{re.sub(r'[^a-zA-Z0-9]', '_', href)[-20:]}"
        opp = Opportunity(
            opportunity_id=opp_id,
            title=detail["title"],
            company=detail["company"] or "Unknown Employer",
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            role_family="TECHNOLOGY",
            role=detail["role"],
            description=detail["description"],
            source_name="JOBS4FRESHER",
            source_listing_url=url,
            source_detail_url=href,
            apply_url=detail["apply_url"],
            location=["India"],
            deadline_status=detail["deadline_status"],
            application_status=detail["app_status"],
            eligible_graduation_batches=detail["batches"],
            experience_min_years=0.0,
            experience_max_years=1.0,
            company_verification_status=CompanyVerificationStatus.AGGREGATOR_ONLY,
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )
        opp.raw_evidence.append(
            make_evidence("detail_page", detail["title"], href, f"Parsed detail page: {detail['title']} at {detail['company']}")
        )
        opportunities.append(opp)
        if len(opportunities) >= limit:
            break

    return opportunities


def extract_freshersdunia_detail(detail_url: str) -> Optional[Dict[str, Any]]:
    """Fetches and parses a FreshersDunia detail page."""
    body, status, outcome = http_client.get(detail_url)
    if status != 200 or not body:
        logger.debug("[freshersdunia] Detail fetch failed for %s: %s", detail_url, outcome)
        return None

    soup = BeautifulSoup(body, "html.parser")
    h1 = soup.find("h1")
    raw_h1 = h1.get_text(strip=True) if h1 else ""
    if not raw_h1:
        return None

    page_text = soup.get_text(" ", strip=True)

    # 1. Extract Role & Company from H1 (e.g. "Amazon Careers 2026 – Software Development Engineer | Freshers")
    company = ""
    role = raw_h1
    if " – " in raw_h1:
        parts = raw_h1.split(" – ", 1)
        comp_part = parts[0]
        role_part = parts[1].split("|")[0].strip()
        comp_m = re.search(r"^([A-Za-z0-9&.\s]+?)\s*(?:Recruitment|Careers|Off\s*Campus|Hiring|IT\s*Recruitment)", comp_part, re.I)
        company = comp_m.group(1).strip() if comp_m else comp_part.split()[0]
        role = role_part
    elif " Hiring " in raw_h1:
        parts = raw_h1.split(" Hiring ", 1)
        company = parts[0].strip()
        role = parts[1].split("|")[0].strip()
    elif raw_h1.split():
        company = raw_h1.split()[0]

    # 2. Extract Batches
    batches = [int(b) for b in re.findall(r"\b202[4-8]\b", page_text)]
    batches = sorted(list(set(batches)))

    # 3. Outbound Apply Link
    apply_url = detail_url
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text(strip=True).lower()
        if any(dom in href.lower() for dom in SOCIAL_SHARE_DOMAINS):
            continue
        if "freshersdunia.in" in href.lower() or href.startswith("#"):
            continue
        if any(kw in link_text for kw in ["click here", "apply link", "apply now", "how to apply", "registration link"]):
            apply_url = href
            break

    # 4. Content description
    entry_content = soup.find("div", class_=lambda c: c and "entry-content" in c)
    desc = entry_content.get_text("\n", strip=True) if entry_content else page_text[:2000]

    return {
        "title": role if role else raw_h1,
        "company": company,
        "role": role,
        "description": desc,
        "apply_url": apply_url,
        "batches": batches,
    }


def scrape_freshersdunia(limit: int = 15) -> List[Opportunity]:
    """Scrapes candidate listings from FreshersDunia.in with detail parsing."""
    url = "https://freshersdunia.in"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[freshersdunia] Failed to fetch index: status %d (%s)", status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    opportunities: List[Opportunity] = []
    seen_urls = set()

    # Strictly inspect <article> post items to avoid header/navbar links
    articles = soup.find_all("article")
    for art in articles:
        a = art.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if href in seen_urls or not href.startswith("http") or _is_nav_or_category_url(href):
            continue
        seen_urls.add(href)

        detail = extract_freshersdunia_detail(href)
        if not detail:
            continue

        opp_id = f"fd_{re.sub(r'[^a-zA-Z0-9]', '_', href)[-20:]}"
        opp = Opportunity(
            opportunity_id=opp_id,
            title=detail["title"],
            company=detail["company"] or "Unknown Employer",
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            role_family="TECHNOLOGY",
            role=detail["role"],
            description=detail["description"],
            source_name="FRESHERSDUNIA",
            source_listing_url=url,
            source_detail_url=href,
            apply_url=detail["apply_url"],
            location=["India"],
            deadline_status=DeadlineStatus.UNKNOWN,
            application_status=ApplicationStatus.OPEN,
            eligible_graduation_batches=detail["batches"],
            experience_min_years=0.0,
            experience_max_years=1.0,
            company_verification_status=CompanyVerificationStatus.AGGREGATOR_ONLY,
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )
        opp.raw_evidence.append(
            make_evidence("detail_page", detail["title"], href, f"Parsed detail page: {detail['title']} at {detail['company']}")
        )
        opportunities.append(opp)
        if len(opportunities) >= limit:
            break

    return opportunities
