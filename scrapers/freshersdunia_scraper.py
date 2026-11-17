"""FreshersDunia Scraper Adapter (Tier 3 Fallback).

Handles FreshersDunia listing cards with Cloudflare header emulation and fallback parsing.
"""
from __future__ import annotations

import logging
from typing import List
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from models.opportunity import Opportunity, OpportunityType

logger = logging.getLogger("coverage_lab.scrapers.freshersdunia")


class FreshersDuniaScraper(BaseScraper):
    def __init__(self):
        super().__init__(source_id="freshersdunia")

    def scrape(self, limit: int = 15) -> List[Opportunity]:
        url = self.source_metadata.listing_url
        resp = self.fetch_with_retry(url)
        if not resp or resp.status_code != 200:
            logger.warning("[freshersdunia] Listing page returned status %s", getattr(resp, "status_code", "None"))
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(".post, article, .entry-card, .td_module_wrap")
        if not cards:
            cards = soup.select("h2 a, h3 a")

        opportunities: List[Opportunity] = []
        for card in cards[:limit]:
            try:
                title_elem = card.select_one("h2, h3, .entry-title") or card
                title = title_elem.get_text(strip=True) if title_elem else ""
                if not title:
                    continue

                link_elem = card.find("a", href=True) if card.name != "a" else card
                link = link_elem["href"] if link_elem and link_elem.has_attr("href") else url

                opp = Opportunity(
                    id=f"freshersdunia-{abs(hash(link)) % 10000000}",
                    opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE if "drive" in title.lower() or "off campus" in title.lower() else OpportunityType.INDIVIDUAL_FRESHER_JOB,
                    title=title,
                    normalized_title=title,
                    company=self._infer_company(title),
                    location="Pan India",
                    description=f"{title} - Fresher opportunity announced on FreshersDunia",
                    source_id=self.source_id,
                    listing_url=link,
                    apply_url=link,
                    provenance=[self.source_id],
                )
                opportunities.append(opp)
            except Exception as e:
                logger.debug("[freshersdunia] Failed card parse: %s", e)

        return opportunities

    def _infer_company(self, title: str) -> str:
        words = title.split()
        for w in words:
            if w.lower() not in {"off", "campus", "drive", "hiring", "recruitment", "freshers", "2025", "2026", "batch"}:
                return w
        return "Unknown"
