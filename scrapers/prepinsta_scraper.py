"""PrepInsta Scraper Adapter (Candidate Source).

Extracts off-campus drive notices and hiring challenges from PrepInsta.
"""
from __future__ import annotations

import logging
from typing import List
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from models.opportunity import Opportunity, OpportunityType

logger = logging.getLogger("coverage_lab.scrapers.prepinsta")


class PrepInstaScraper(BaseScraper):
    def __init__(self):
        super().__init__(source_id="prepinsta")

    def scrape(self, limit: int = 15) -> List[Opportunity]:
        url = self.source_metadata.listing_url
        resp = self.fetch_with_retry(url)
        if not resp or resp.status_code != 200:
            logger.warning("[prepinsta] Listing returned status %s", getattr(resp, "status_code", "None"))
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(".drive-card, .table tbody tr, article, .post-title a")
        opportunities: List[Opportunity] = []

        for card in cards[:limit]:
            try:
                title_elem = card.select_one("a, .title") or card
                title = title_elem.get_text(strip=True) if title_elem else ""
                if not title or len(title) < 5:
                    continue

                link = title_elem.get("href") if title_elem and title_elem.has_attr("href") else url

                opp = Opportunity(
                    id=f"prepinsta-{abs(hash(link)) % 10000000}",
                    opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
                    title=title,
                    normalized_title=title,
                    company=title.split()[0] if title.split() else "Various",
                    location="Pan India",
                    description=f"{title} - Recruitment drive notice from PrepInsta",
                    source_id=self.source_id,
                    listing_url=link,
                    apply_url=link,
                    provenance=[self.source_id],
                )
                opportunities.append(opp)
            except Exception as e:
                logger.debug("[prepinsta] Failed card parse: %s", e)

        return opportunities
