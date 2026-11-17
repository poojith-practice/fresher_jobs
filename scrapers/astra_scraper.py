"""UseAstra Off-Campus Drives Scraper."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.astra")


class AstraScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="useastra",
            name="UseAstra Off-Campus",
            base_url="https://www.useastra.in/jobs/off-campus-drives",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[useastra] Failed to fetch listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_links = set()

        links = soup.find_all("a", href=re.compile(r"/jobs/[a-zA-Z0-9_-]+"))
        for a in links:
            href = a["href"].split("?")[0].strip()
            if href in seen_links or href.endswith("/jobs/off-campus-drives"):
                continue

            title_text = a.get_text(strip=True)
            if len(title_text) < 10 or title_text.lower() in {"apply", "view job", "details"}:
                continue

            seen_links.add(href)
            full_url = urljoin(self.base_url, href)

            # Try parsing "Role at Company" from title text
            # E.g. "Global Banking & Markets Operations - Equities Exe... at Goldman Sachs"
            company = "Enterprise Employer"
            role = title_text
            if " at " in title_text:
                parts = title_text.split(" at ")
                role = parts[0].strip()
                company = parts[1].strip()

            parent = a.find_parent(["div", "article", "li"])
            snippet = parent.get_text(" ", strip=True) if parent else ""

            batches = re.findall(r"202\d", f"{title_text} {snippet}")

            results.append({
                "source_id": self.source_id,
                "raw_id": href.strip("/").split("/")[-1],
                "title": role,
                "company": company,
                "location": "India",
                "description": f"{title_text}. {snippet[:400]}",
                "batches": list(dict.fromkeys(batches)),
                "salary_raw": None,
                "listing_url": self.base_url,
                "apply_url": full_url,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": None,
                "raw_metadata": {"raw_title": title_text},
            })

            if len(results) >= max_items:
                break

        logger.info("[useastra] Extracted %d listings", len(results))
        return results
