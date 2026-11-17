"""Official Amazon Careers Public REST API Scraper."""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.amazon")


class AmazonJobsScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="amazon_jobs",
            name="Amazon Official Careers",
            base_url="https://www.amazon.jobs/en/search.json?base_query=Fresher&country=IND",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        data = self.fetch_json(self.base_url)
        if not data or not isinstance(data, dict):
            logger.warning("[amazon_jobs] Empty or invalid JSON response")
            return []

        jobs = data.get("jobs", [])
        logger.info("[amazon_jobs] Discovered %d jobs in JSON response", len(jobs))

        results: List[Dict[str, Any]] = []
        for j in jobs[:max_items]:
            title = str(j.get("title") or "").strip()
            job_id = str(j.get("id_icims") or j.get("id") or "")
            job_path = str(j.get("job_path") or "")
            city = str(j.get("city") or "India")
            posted = str(j.get("posted_date") or "")
            desc = str(j.get("description") or "")
            basic_quals = str(j.get("basic_qualifications") or "")

            apply_url = f"https://www.amazon.jobs{job_path}" if job_path else "https://www.amazon.jobs"

            full_desc = f"{desc}\n\nBasic Qualifications:\n{basic_quals}"

            results.append({
                "source_id": self.source_id,
                "raw_id": job_id,
                "title": title,
                "company": "Amazon",
                "location": f"{city}, India",
                "description": full_desc,
                "batches": ["2024", "2025", "2026"],
                "salary_raw": None,
                "listing_url": self.base_url,
                "apply_url": apply_url,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": posted,
                "raw_metadata": j,
            })

        return results
