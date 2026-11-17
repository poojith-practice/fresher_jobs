"""
Multi-Source Deduplication & Provenance Aggregator
=================================================
Identifies identical opportunities across distinct discovery channels,
synthesizes a single canonical opportunity, and merges provenance references.
"""
from __future__ import annotations

import re
from typing import List, Dict, Tuple
from core.models import Opportunity


from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def _clean_url_for_dedup(url: str) -> str:
    """Strips tracking query parameters (utm_*, ref, etc.) for resilient URL matching."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip().lower())
        query_params = parse_qsl(parsed.query)
        filtered_params = [
            (k, v) for k, v in query_params
            if not k.startswith("utm_") and k not in {"ref", "source", "origin"}
        ]
        clean_query = urlencode(filtered_params)
        clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.params, clean_query, ""))
        return clean_url
    except Exception:
        return url.strip().lower().rstrip("/")


def _clean_str(val: str) -> str:
    """Sanitizes text to alphanumeric characters for resilient key matching."""
    return re.sub(r"[^\w\s]", "", str(val or "").lower()).strip()


def _clean_company_for_dedup(company: str) -> str:
    """Normalizes company name by stripping legal entities and special characters."""
    c = _clean_str(company)
    c = re.sub(r"\b(limited|ltd|pvt|private|technologies|solutions|corp|corporation|inc|services)\b", "", c)
    return re.sub(r"\s+", " ", c).strip()


def _normalize_title_for_dedup(title: str) -> str:
    """Strips standard noise suffixes like 'Hiring 2026', 'Apply Online', 'Off Campus'."""
    t = _clean_str(title)
    t = re.sub(r"\b(off\s*campus(?:\s*drive)?|hiring|recruitment|apply\s*online|202[4-8]|batch|freshers?|jobs?)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


class OpportunityDeduplicator:
    """Cross-source deduplicator preserving all discovery references."""

    def __init__(self):
        self._seen_urls: Dict[str, Opportunity] = {}
        self._seen_composite: Dict[Tuple[str, str, str], Opportunity] = {}
        self._canonical_records: List[Opportunity] = []

    def process(self, opportunity: Opportunity) -> Opportunity:
        """
        Deduplicates an incoming opportunity. If already seen, merges evidence
        and source URLs into the existing canonical record. Returns the canonical record.
        """
        # Primary key: Exact Apply / Employer URL
        raw_url = (opportunity.employer_job_url or opportunity.apply_url or opportunity.source_detail_url or "").strip().lower()
        primary_url = _clean_url_for_dedup(raw_url)

        # Secondary key: Normalized (Company, Title)
        comp_key = _clean_company_for_dedup(opportunity.company)
        title_key = _normalize_title_for_dedup(opportunity.title)
        composite_key = (comp_key, title_key)

        matched_canonical: Opportunity | None = None

        if primary_url and primary_url in self._seen_urls:
            matched_canonical = self._seen_urls[primary_url]
        elif composite_key in self._seen_composite and comp_key and title_key:
            matched_canonical = self._seen_composite[composite_key]

        if matched_canonical is not None:
            # Merge source references and provenance
            candidate_urls = [opportunity.source_detail_url, opportunity.source_listing_url, opportunity.apply_url] + opportunity.all_source_urls
            for u in candidate_urls:
                if u and u not in matched_canonical.all_source_urls:
                    matched_canonical.all_source_urls.append(u)

            # If the new record has richer employer evidence or description, adopt it
            if not matched_canonical.employer_job_url and opportunity.employer_job_url:
                matched_canonical.employer_job_url = opportunity.employer_job_url
            if not matched_canonical.description and opportunity.description:
                matched_canonical.description = opportunity.description

            # Append distinct raw evidence
            existing_fields = {e.field for e in matched_canonical.raw_evidence}
            for ev in opportunity.raw_evidence:
                if ev.field not in existing_fields:
                    matched_canonical.raw_evidence.append(ev)

            return matched_canonical

        # Brand new unique opportunity
        if opportunity.source_detail_url and opportunity.source_detail_url not in opportunity.all_source_urls:
            opportunity.all_source_urls.append(opportunity.source_detail_url)
        if opportunity.apply_url and opportunity.apply_url not in opportunity.all_source_urls:
            opportunity.all_source_urls.append(opportunity.apply_url)

        if primary_url:
            self._seen_urls[primary_url] = opportunity
        if comp_key and title_key:
            self._seen_composite[composite_key] = opportunity

        self._canonical_records.append(opportunity)
        return opportunity

    def deduplicate(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        """Processes a list of opportunities and returns the canonical list."""
        for opp in opportunities:
            self.process(opp)
        return self.get_canonical_opportunities()

    def get_canonical_opportunities(self) -> List[Opportunity]:
        return list(self._canonical_records)
