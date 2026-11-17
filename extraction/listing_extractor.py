"""Generic Listing Page Extractor for Indian Fresher & Off-Campus Job Boards.

Extracts structured job cards, meta tags, and pagination links from HTML sources.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup, Tag


class ListingExtractor:
    """Extracts job listing items from generic aggregator HTML patterns."""

    @staticmethod
    def extract_cards(
        soup: BeautifulSoup,
        selectors: List[str],
    ) -> List[Tag]:
        """Finds candidate job card elements using fallback CSS selectors."""
        cards = []
        for sel in selectors:
            found = soup.select(sel)
            if found:
                cards = found
                break
        return cards

    @staticmethod
    def clean_text(element: Optional[Tag]) -> str:
        """Cleans and strips whitespace from a BeautifulSoup element."""
        if not element:
            return ""
        return re.sub(r"\s+", " ", element.get_text()).strip()

    @staticmethod
    def extract_link(element: Optional[Tag], base_url: str = "") -> Optional[str]:
        """Extracts and qualifies an href link from an element."""
        if not element:
            return None
        href = element.get("href")
        if not href:
            a_tag = element.find("a")
            if a_tag:
                href = a_tag.get("href")
        if not href or href.startswith("javascript:") or href.startswith("#"):
            return None
        if href.startswith("/"):
            return base_url.rstrip("/") + href
        return href
