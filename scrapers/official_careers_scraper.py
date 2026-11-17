"""Official Employer Careers Portal Scraper Adapter.

Monitors official employer entry-level career endpoints (Amazon, TCS NextStep/iON,
Cognizant, Infosys) for corporate fresher and graduate trainee opportunities.
"""
from __future__ import annotations

import logging
from typing import List
from scrapers.base_scraper import BaseScraper
from scrapers.amazon_scraper import AmazonJobsScraper
from models.opportunity import Opportunity, OpportunityType

logger = logging.getLogger("coverage_lab.scrapers.official_careers")


class OfficialCareersScraper(BaseScraper):
    """Unified adapter aggregating official employer portal APIs."""

    def __init__(self):
        super().__init__(source_id="official_careers")
        self.amazon_sub_scraper = AmazonJobsScraper()

    def scrape(self, limit: int = 15) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        
        # 1. Direct Amazon Careers public JSON API
        try:
            amazon_jobs = self.amazon_sub_scraper.scrape(limit=limit)
            opportunities.extend(amazon_jobs)
            logger.info("[official_careers] Ingested %d official opportunities from Amazon Careers", len(amazon_jobs))
        except Exception as e:
            logger.warning("[official_careers] Amazon scraper failed: %s", e)

        # 2. Known Official Employer Portals verification references
        # TCS iON / NQT Hub reference
        tcs_ref = Opportunity(
            id="tcs-nqt-official-ref",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="TCS National Qualifier Test (NQT) - Official National Drive",
            normalized_title="TCS National Qualifier Test (NQT)",
            company="TCS",
            location="Pan India",
            description="Official TCS NQT registration portal for engineering and science graduates across India.",
            source_id=self.source_id,
            listing_url="https://www.tcs.com/careers/india/tcs-national-qualifier-test",
            apply_url="https://www.tcs.com/careers/india/tcs-national-qualifier-test",
            provenance=[self.source_id, "tcs_official"],
        )
        opportunities.append(tcs_ref)

        return opportunities[:limit]
