"""FreshersNow Scraper Adapter (Candidate Source).

Scrapes IT recruitment drives and fresher jobs from FreshersNow.
"""
from __future__ import annotations

import logging
from typing import List
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from models.opportunity import Opportunity, OpportunityType

logger = logging.getLogger("coverage_lab.scrapers.freshersnow")


class FreshersNowScraper(BaseScraper):
    def __init__(self):
        super().__init__(source_id="freshersnow")

    def scrape(self, limit: int = 15) -> List[Opportunity]:
        url = self.source_metadata.listing_url
        resp = self.fetch_with_retry(url)
        if not resp or resp.status_code != 200:
            logger.warning("[freshersnow] Listing returned status %s", getattr(resp, "status_code", "None"))
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(".td_module_wrap, .post-item, article, h3.entry-title a")
        opportunities: List[Opportunity] = []

        for card in cards[:limit]:
            try:
                title_elem = card.select_one(".entry-title a") or card
                title = title_elem.get_text(strip=True) if title_elem else ""
                if not title:
                    continue

                link = title_elem.get("href") if title_elem and title_elem.has_attr("href") else url

                opp = Opportunity(
                    id=f"freshersnow-{abs(hash(link)) % 10000000}",
                    opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE if "drive" in title.lower() else OpportunityType.INDIVIDUAL_FRESHER_JOB,
                    title=title,
                    normalized_title=title,
                    company=title.split()[0] if title.split() else "Various",
                    location="Pan India",
                    description=f"{title} - Aggregated listing from FreshersNow",
                    source_id=self.source_id,
                    listing_url=link,
                    apply_url=link,
                    provenance=[self.source_id],
                )
                opportunities.append(opp)
            except Exception as e:
                logger.debug("[freshersnow] Failed card parse: %s", e)

        return opportunities
