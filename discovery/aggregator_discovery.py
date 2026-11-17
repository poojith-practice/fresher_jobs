"""
Lane 1: Curated Public Aggregator Discovery Orchestrator
========================================================
Runs public aggregator scrapers (CampusDrive, UseAstra, eLitmus, JoinSaarthi, Jobs4Fresher, FreshersDunia)
with fault-isolation, structured exception handling, and provenance tracking.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional
from core.models import Opportunity

from scrapers.campusdrive import scrape_campusdrive
from scrapers.useastra import scrape_useastra
from scrapers.elitmus import scrape_elitmus
from scrapers.joinsaarthi import scrape_joinsaarthi
from scrapers.blog_scrapers import scrape_jobs4fresher, scrape_freshersdunia

logger = logging.getLogger("discovery.aggregator")

AVAILABLE_AGGREGATORS = {
    "campusdrive": scrape_campusdrive,
    "useastra": scrape_useastra,
    "elitmus": scrape_elitmus,
    "joinsaarthi": scrape_joinsaarthi,
    "jobs4fresher": scrape_jobs4fresher,
    "freshersdunia": scrape_freshersdunia,
}


def discover_aggregators(
    selected_sources: Optional[List[str]] = None,
    max_per_source: int = 15,
) -> List[Opportunity]:
    """Runs all or selected Lane 1 aggregator scrapers with per-source isolation."""
    target_sources = selected_sources or list(AVAILABLE_AGGREGATORS.keys())
    all_opportunities: List[Opportunity] = []

    for src_name in target_sources:
        scraper_func = AVAILABLE_AGGREGATORS.get(src_name.lower())
        if not scraper_func:
            logger.warning("[aggregator_discovery] Unrecognized source: %s", src_name)
            continue

        try:
            logger.info("[aggregator_discovery] Executing scraper for '%s'...", src_name)
            try:
                opps = scraper_func(limit=max_per_source)
            except TypeError:
                opps = scraper_func()
            logger.info("[aggregator_discovery] Source '%s' discovered %d opportunities", src_name, len(opps))
            all_opportunities.extend(opps)
        except Exception as exc:
            logger.error("[aggregator_discovery] Source '%s' failed with exception: %s", src_name, exc, exc_info=True)

    return all_opportunities
