"""
Unified Multi-Lane Discovery Package
====================================
Integrates Lane 1 (Public Aggregators), Lane 2 (Search Engine Discovery),
and Lane 3 (Verified Employer Feeds & ATS) with unified deduplication.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from core.models import Opportunity
from core.deduplication import OpportunityDeduplicator
from discovery.aggregator_discovery import discover_aggregators
from discovery.search_engine_discovery import discover_via_search
from discovery.employer_discovery import discover_employer_feeds

logger = logging.getLogger("discovery")


def run_discovery_pipeline(
    include_aggregators: bool = True,
    include_search: bool = False,  # Default off unless requested or in broad discovery
    include_employers: bool = True,
    selected_sources: Optional[List[str]] = None,
    max_per_source: int = 15,
) -> List[Opportunity]:
    """Runs configured discovery lanes and merges results with strict deduplication."""
    all_raw: List[Opportunity] = []

    if include_aggregators:
        agg_opps = discover_aggregators(selected_sources=selected_sources, max_per_source=max_per_source)
        all_raw.extend(agg_opps)

    if include_employers:
        emp_opps = discover_employer_feeds()
        all_raw.extend(emp_opps)

    if include_search:
        search_opps = discover_via_search(max_results_per_query=5)
        all_raw.extend(search_opps)

    logger.info("[discovery] Total discovered across lanes before dedup: %d", len(all_raw))

    deduplicator = OpportunityDeduplicator()
    deduped = deduplicator.deduplicate(all_raw)
    logger.info("[discovery] Discovered %d unique opportunities after deduplication", len(deduped))

    return deduped


__all__ = [
    "run_discovery_pipeline",
    "discover_aggregators",
    "discover_via_search",
    "discover_employer_feeds",
]
