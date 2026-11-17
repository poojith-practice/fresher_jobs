"""Job Detail Page & Description Extractor.

Extracts main content, qualification sections, eligible batches, and direct apply links.
"""
from __future__ import annotations

import re
from typing import Dict, Optional
from bs4 import BeautifulSoup


class DetailExtractor:
    """Parses full job description pages into clean structured sections."""

    CONTENT_SELECTORS = [
        "article",
        ".job-description",
        ".entry-content",
        ".post-content",
        "#job-details",
        ".details-content",
        "main",
    ]

    @classmethod
    def extract_full_text(cls, soup: BeautifulSoup) -> str:
        """Extracts text from primary content containers, ignoring nav/footer/ads."""
        # Decompose noisy elements
        for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
            tag.decompose()

        for sel in cls.CONTENT_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)

        body = soup.find("body")
        if body:
            return re.sub(r"\s+", " ", body.get_text(separator=" ", strip=True))
        return ""

    @classmethod
    def extract_direct_apply_link(cls, soup: BeautifulSoup, listing_url: str = "") -> Optional[str]:
        """Identifies direct application / registration outbound links."""
        apply_keywords = ["apply now", "register here", "official link", "application link", "apply online", "click here to apply"]
        
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip().lower()
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or "whatsapp" in href or "telegram" in href:
                continue
            if any(k in text for k in apply_keywords):
                return href
        return listing_url
