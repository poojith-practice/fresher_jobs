"""
CampusDrive.in Scraper & Detail Page Extractor
==============================================
Lane 1 Discovery adapter for CampusDrive.in.
Extracts genuine job posting slugs (excluding category archives and navbar menus),
visits candidate detail pages to parse true registration deadlines, real employer
names, roles, and outbound application links.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, unquote
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

logger = logging.getLogger("scrapers.campusdrive")

# Month name mapping for date parsing
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_string(text: str) -> Optional[datetime]:
    """Parses natural language dates like '20 October 2026' or 'October 20, 2026'."""
    clean = text.lower().strip()
    match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", clean)
    if match:
        day = int(match.group(1))
        month_str = match.group(2)
        year = int(match.group(3))
        month = MONTHS.get(month_str)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None

    match2 = re.search(r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", clean)
    if match2:
        month_str = match2.group(1)
        day = int(match2.group(2))
        year = int(match2.group(3))
        month = MONTHS.get(month_str)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None
    return None


def extract_campusdrive_detail(detail_url: str) -> Dict[str, Any]:
    """Fetches and parses a CampusDrive detail page with strict DOM isolation."""
    body, status, outcome = http_client.get(detail_url)
    if status != 200 or not body:
        return {"detail_status": outcome}

    # Classify page type before extracting
    from extraction.page_type_classifier import classify_page_type, PageType
    page_type, reason = classify_page_type(url=detail_url, html_content=body)
    if page_type not in (PageType.JOB_DETAIL, PageType.DRIVE_DETAIL):
        logger.info("[campusdrive] Skipping non-job page %s: %s (%s)", detail_url, page_type.value, reason)
        return {"detail_status": "REJECTED_PAGE_TYPE", "page_type": page_type.value, "reason": reason}

    soup = BeautifulSoup(body, "html.parser")

    # Clean boilerplate before extracting text
    for tag in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
        tag.decompose()
    for cl in [
        "sidebar", "navigation", "related-posts", "widget", "footer", "menu",
        "yarpp-related", "rp4wp-related-posts", "post-navigation", "nav-links",
        "comments-area", "comment-respond", "sharedaddy", "sd-sharing",
        "tagcloud", "tags-links", "widget-area", "wp-block-latest-posts",
        "wp-block-columns", "entry-meta", "author-bio", "related-articles"
    ]:
        for el in soup.find_all(class_=re.compile(cl, re.I)):
            el.decompose()

    # Target article or entry-content container
    article = soup.find("article") or soup.find("div", class_=re.compile(r"content|post-body|entry-content", re.I))
    clean_soup = article if article else soup
    clean_text = clean_soup.get_text(" ", strip=True)

    # 0. Extract Article Title and Cleaned Employer/Role
    h1 = clean_soup.find("h1") or soup.find("h1")
    raw_h1 = h1.get_text(strip=True) if h1 else ""
    company = ""
    role = ""
    if raw_h1:
        if " - " in raw_h1:
            comp_part, role_part = raw_h1.split(" - ", 1)
            comp_m = re.search(r"^([A-Za-z0-9&.\s]+?)\s*(?:Off\s*Campus|Recruitment|Hiring|Drives?|Careers)", comp_part, re.I)
            company = comp_m.group(1).strip() if comp_m else comp_part.split()[0]
            role = re.sub(r"\s*\([^)]*\)", "", role_part).strip()
        elif " Hiring " in raw_h1:
            comp_part, role_part = raw_h1.split(" Hiring ", 1)
            company = comp_part.strip()
            role = role_part.strip()
        elif " Off Campus " in raw_h1:
            comp_part, role_part = raw_h1.split(" Off Campus ", 1)
            company = comp_part.strip()
            role = role_part.strip()
        else:
            role = raw_h1

    # 1. Parse 'Last Date to Register'
    deadline_date_str = None
    deadline_status = DeadlineStatus.NOT_PUBLISHED
    deadline_evidence = ""

    last_date_match = re.search(
        r"(?:last\s*date\s*to\s*register|registration\s*deadline|deadline|apply\s*before)\s*[:\-–—]?\s*([^.]+?)(?:\.|$|\||\n|eligible)",
        clean_text,
        re.I,
    )
    if last_date_match:
        raw_deadline_text = last_date_match.group(1).strip()
        deadline_evidence = f"Last Date to Register: {raw_deadline_text}"
        parsed_dt = parse_date_string(raw_deadline_text)
        if parsed_dt:
            deadline_date_str = parsed_dt.strftime("%Y-%m-%d")
            now = datetime.utcnow()
            if parsed_dt < now:
                deadline_status = DeadlineStatus.EXPIRED
            else:
                deadline_status = DeadlineStatus.OPEN
        else:
            deadline_status = DeadlineStatus.NOT_PUBLISHED

    # 2. Extract Eligible Batches (Strictly within eligibility section only)
    batches = []
    batch_section = re.search(
        r"(?:eligible\s*batches?|batch(?:es)?\s*eligible|passing\s*out\s*year|batch\s*criteria)\s*[:\-–—]?\s*([^\n<|]+?)(?:passing|academic|qualification|minimum|salary|experience|$)",
        clean_text,
        re.I,
    )
    if batch_section:
        matches = re.findall(r"\b(202[0-9])\b", batch_section.group(1))
        if matches:
            batches = sorted(list(set(int(b) for b in matches)))

    # 2b. Extract Experience Requirement (Do not fabricate defaults)
    exp_min = None
    exp_max = None
    exp_status = "NOT_SPECIFIED"
    exp_m = re.search(r"(?:experience|work\s+experience|exp)\s*[:\-–—]?\s*([^\n<|]+?)(?:passing|academic|qualification|salary|skills|batch|$)", clean_text, re.I)
    if exp_m:
        exp_text = exp_m.group(1).lower().strip()
        if "fresher" in exp_text or "0 year" in exp_text or "0-0" in exp_text or "0 to 1" in exp_text or "0-1" in exp_text:
            exp_min = 0.0
            exp_max = 1.0
            exp_status = "FRESHER_ELIGIBLE"
        elif re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*years?", exp_text):
            m = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*years?", exp_text)
            exp_min = float(m.group(1))
            exp_max = float(m.group(2))
            exp_status = "FRESHER_ELIGIBLE" if exp_max <= 1.0 else "COMMERCIAL_EXPERIENCE_REQUIRED"
        elif re.search(r"(\d+)\+?\s*years?", exp_text):
            m = re.search(r"(\d+)\+?\s*years?", exp_text)
            val = float(m.group(1))
            exp_min = val
            exp_max = val
            exp_status = "FRESHER_ELIGIBLE" if val == 0 else "COMMERCIAL_EXPERIENCE_REQUIRED"

    # 3. Direct Apply Link (Never fallback to aggregator article URL)
    apply_url = None
    for a in clean_soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text(strip=True).lower()
        if any(w in link_text for w in ["apply now", "apply online", "official link", "registration link"]):
            if href.startswith("http") and "campusdrive.in" not in href:
                if "linkedin.com/safety/go" in href and "url=" in href:
                    parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    target_url = parsed_q.get("url", [href])[0]
                    apply_url = unquote(target_url)
                else:
                    apply_url = href
                break

    return {
        "detail_status": "SUCCESS",
        "title": role if role else raw_h1,
        "source_article_title": raw_h1,
        "company": company,
        "role": role if role else raw_h1,
        "description": clean_text[:4000],
        "deadline": deadline_date_str,
        "deadline_status": deadline_status,
        "deadline_evidence": deadline_evidence,
        "eligible_batches": batches,
        "experience_min_years": exp_min,
        "experience_max_years": exp_max,
        "experience_status": exp_status,
        "apply_url": apply_url,
    }


def scrape_campusdrive(limit: int = 20, fetch_details: bool = True) -> List[Opportunity]:
    """Scrapes candidate listings from CampusDrive.in and normalizes into Opportunity models."""
    url = "https://campusdrive.in/jobs"
    body, status, outcome = http_client.get(url)
    if status != 200 or not body:
        logger.warning("[campusdrive] Failed to load index: status %d (%s)", status, outcome)
        return []

    soup = BeautifulSoup(body, "html.parser")
    opportunities: List[Opportunity] = []
    seen_urls = set()

    links = soup.find_all("a", href=True)
    for a in links:
        href = a["href"].strip()
        if not href or href == "#" or href.startswith("javascript"):
            continue
        full_url = urljoin(url, href).rstrip("/")

        # Strictly ignore category archives, pills, tools, and non-job pages
        parsed_url = urllib.parse.urlparse(full_url)
        path = parsed_url.path
        if not full_url.startswith("https://campusdrive.in/") or full_url in seen_urls:
            continue
        if any(x in path for x in ["/jobs", "/tools", "/placement", "/category", "/tag", "/privacy", "/contact", "/about", "/disclaimer"]):
            continue
        # Candidate job posting slugs MUST have at least 2 hyphens
        if path.count("-") < 2:
            continue
        seen_urls.add(full_url)

        raw_title = a.get_text(strip=True)
        if len(raw_title) < 8 or raw_title.lower() in {"apply →", "view details", "read more"}:
            raw_title = path.strip("/").replace("-", " ").title()

        opp_id = f"cd_{re.sub(r'[^a-zA-Z0-9]', '_', full_url)[-20:]}"

        detail_data = {}
        if fetch_details:
            detail_data = extract_campusdrive_detail(full_url)
            if detail_data.get("detail_status") == "REJECTED_PAGE_TYPE":
                logger.info("[campusdrive] Ignoring rejected page %s: %s", full_url, detail_data.get("reason"))
                continue

        title = detail_data.get("title") or raw_title
        company = detail_data.get("company") or "Unknown Employer"
        role = detail_data.get("role") or title

        opp = Opportunity(
            opportunity_id=opp_id,
            title=title,
            company=company,
            opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
            role_family="TECHNOLOGY",
            role=role,
            description=detail_data.get("description"),
            source_name="CAMPUSDRIVE",
            source_listing_url=url,
            source_detail_url=full_url,
            apply_url=detail_data.get("apply_url"),
            location=["India"],
            deadline=detail_data.get("deadline"),
            deadline_status=detail_data.get("deadline_status", DeadlineStatus.UNKNOWN),
            eligible_graduation_batches=detail_data.get("eligible_batches", []),
            experience_min_years=detail_data.get("experience_min_years"),
            experience_max_years=detail_data.get("experience_max_years"),
            experience_status=detail_data.get("experience_status", "NOT_SPECIFIED"),
            company_verification_status=CompanyVerificationStatus.AGGREGATOR_ONLY,
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )

        if detail_data.get("deadline_evidence"):
            opp.raw_evidence.append(
                make_evidence("deadline", detail_data.get("deadline"), full_url, detail_data["deadline_evidence"])
            )
        opp.raw_evidence.append(
            make_evidence("title", title, full_url, f"Detail page H1: {title}")
        )

        opportunities.append(opp)
        if len(opportunities) >= limit:
            break

    return opportunities
