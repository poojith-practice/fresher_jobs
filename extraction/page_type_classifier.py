"""Page Type Classifier.

Distinguishes genuine single-opportunity job detail pages and recruitment drive postings
from category hubs, search result indices, navigation menus, and generic articles.
Prevents hub pages (e.g. "2027 Batch Drives") from masquerading as single job opportunities.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Tuple
from bs4 import BeautifulSoup


class PageType(str, Enum):
    JOB_DETAIL = "JOB_DETAIL"
    DRIVE_DETAIL = "DRIVE_DETAIL"
    CATEGORY_PAGE = "CATEGORY_PAGE"
    SEARCH_RESULTS = "SEARCH_RESULTS"
    NAVIGATION = "NAVIGATION"
    ARTICLE = "ARTICLE"
    UNKNOWN = "UNKNOWN"


CATEGORY_PATTERNS = [
    r"\b\d{4}\s+batch\s+drives\b",
    r"\boff[\s-]campus\s+drives\s+list\b",
    r"\bjopenings\s+in\s+[a-zA-Z]+\b",
    r"\ball\s+jobs\b",
    r"\bcategory\s*:\b",
    r"\bbrowse\s+jobs\b",
    r"\bview\s+all\s+(?:jobs|drives|openings)\b",
    r"\blatest\s+job\s+updates\b",
]

DETAIL_PATTERNS = [
    r"\bapply\s+(?:online|now|here|link)\b",
    r"\bjob\s+(?:description|responsibilities|overview|summary)\b",
    r"\beligibility\s+criteria\b",
    r"\brole\s+(?:and\s+responsibilities|overview)\b",
    r"\bkey\s+responsibilities\b",
    r"\bqualification[s]?\s*:\b",
]


def classify_page_type(url: str, html_content: str, title: str = "") -> Tuple[PageType, str]:
    """Classifies a page into its architectural type to gate extraction.
    
    Returns:
        (page_type, classification_reason)
    """
    if not html_content or len(html_content.strip()) < 100:
        return PageType.UNKNOWN, "Page content too short or empty"

    url_lower = url.lower()
    title_lower = title.lower()
    soup = BeautifulSoup(html_content[:30000], "html.parser")
    body_text = soup.get_text(" ", strip=True).lower()

    # 1. Check URL patterns for categories and archives
    if any(p in url_lower for p in ["/category/", "/tag/", "/batch/", "/archive/", "/search?", "/jobs-in-"]):
        return PageType.CATEGORY_PAGE, f"URL path indicates category or archive index: {url}"

    # 2. Check title for category patterns (e.g. "2027 Batch Drives")
    for pat in CATEGORY_PATTERNS:
        if re.search(pat, title_lower):
            return PageType.CATEGORY_PAGE, f"Title indicates category listing: '{title}'"

    # 3. Check for multi-listing cards / repeated article excerpts
    article_cards = soup.find_all(["article", "div"], class_=re.compile(r"post-item|job-card|listing-item|card-job", re.I))
    if len(article_cards) >= 4 and not any(re.search(p, body_text[:2000]) for p in DETAIL_PATTERNS):
        return PageType.CATEGORY_PAGE, f"Found {len(article_cards)} listing cards; page is a multi-job hub"

    # 4. Check for genuine job detail / drive detail signals
    has_apply_action = bool(re.search(r"\bapply\s+(?:online|now|link)\b", body_text))
    has_eligibility = bool(re.search(r"\beligibility\s*(?:criteria)?\b|\brole\s*:\b|\bqualification[s]?\b", body_text))
    has_job_id = bool(re.search(r"\b(?:job|req(?:uisition)?|position)\s*(?:id|number|#)?[:\s]+[a-zA-Z0-9_-]{4,}\b", body_text))

    if has_apply_action and (has_eligibility or has_job_id):
        if "off-campus" in title_lower or "drive" in title_lower:
            return PageType.DRIVE_DETAIL, "Specific off-campus drive announcement with application route"
        return PageType.JOB_DETAIL, "Individual job vacancy posting with verified description and apply route"

    if has_apply_action:
        return PageType.JOB_DETAIL, "Individual opportunity with direct apply link"

    return PageType.ARTICLE, "Generic informational or editorial page without verified job application route"
