"""Scrapers Subsystem for Fresher Job Scraper Coverage Lab."""
from typing import Dict, List, Optional
from scrapers.base_scraper import BaseScraper
from scrapers.saarthi_scraper import SaarthiScraper
from scrapers.campusdrive_scraper import CampusDriveScraper
from scrapers.elitmus_scraper import ELitmusScraper
from scrapers.astra_scraper import AstraScraper
from scrapers.jobs4fresher_scraper import Jobs4FresherScraper
from scrapers.hirastra_scraper import HirastraScraper
from scrapers.amazon_scraper import AmazonJobsScraper
from scrapers.freshersdunia_scraper import FreshersDuniaScraper
from scrapers.freshersnow_scraper import FreshersNowScraper
from scrapers.prepinsta_scraper import PrepInstaScraper
from scrapers.official_careers_scraper import OfficialCareersScraper
from scrapers.campusdrive_harvester import CampusDriveHarvester
from scrapers.freshersdunia_harvester import harvest_freshersdunia_jobs, ATSVerifier

SCRAPER_REGISTRY = {
    "saarthi_drives": SaarthiScraper,
    "campusdrive": CampusDriveScraper,
    "elitmus": ELitmusScraper,
    "useastra": AstraScraper,
    "jobs4fresher": Jobs4FresherScraper,
    "hirastra": HirastraScraper,
    "amazon_jobs": AmazonJobsScraper,
    "freshersdunia": FreshersDuniaScraper,
    "freshersnow": FreshersNowScraper,
    "prepinsta": PrepInstaScraper,
    "official_careers": OfficialCareersScraper,
}

def get_all_scrapers() -> List[BaseScraper]:
    """Returns instantiated scrapers for all approved active sources."""
    # Active default run targets Tier 1 and Tier 2 approved sources
    approved_ids = [
        "saarthi_drives",
        "campusdrive",
        "elitmus",
        "useastra",
        "jobs4fresher",
        "hirastra",
        "amazon_jobs",
    ]
    return [SCRAPER_REGISTRY[sid]() for sid in approved_ids if sid in SCRAPER_REGISTRY]

def get_scraper_by_id(source_id: str) -> Optional[BaseScraper]:
    """Instantiates a scraper by source_id."""
    cls = SCRAPER_REGISTRY.get(source_id)
    if cls:
        return cls()
    return None

__all__ = [
    "BaseScraper",
    "SaarthiScraper",
    "CampusDriveScraper",
    "ELitmusScraper",
    "AstraScraper",
    "Jobs4FresherScraper",
    "HirastraScraper",
    "AmazonJobsScraper",
    "FreshersDuniaScraper",
    "CampusDriveHarvester",
    "harvest_freshersdunia_jobs",
    "ATSVerifier",
    "FreshersNowScraper",
    "PrepInstaScraper",
    "OfficialCareersScraper",
    "get_all_scrapers",
    "get_scraper_by_id",
]
