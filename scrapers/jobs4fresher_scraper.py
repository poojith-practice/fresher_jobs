"""Jobs4Fresher Recruitment Scraper."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.jobs4fresher")


class Jobs4FresherScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="jobs4fresher",
            name="Jobs4Fresher",
            base_url="https://jobs4fresher.com",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[jobs4fresher] Failed to fetch listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_urls = set()

        links = soup.find_all("a", href=True)
        for a in links:
            href = a["href"].strip()
            # Match recruitment posts
            if not any(k in href for k in ["recruitment", "hiring", "off-campus"]) or href in seen_urls:
                continue

            title_text = a.get_text(strip=True)
            if len(title_text) < 8 or title_text.lower() in {"apply", "read more"}:
                continue

            seen_urls.add(href)

            # E.g. "Slice Recruitment 2026 | Bangalore"
            parts = title_text.split("|")
            role_part = parts[0].strip()
            location = parts[1].strip() if len(parts) > 1 else "India"

            company = role_part.split("Recruitment")[0].split("Hiring")[0].split("Off Campus")[0].strip()
            if not company:
                company = "Jobs4Fresher Partner"

            batches = re.findall(r"202\d", title_text)

            parent = a.find_parent(["div", "article", "li"])
            snippet = parent.get_text(" ", strip=True) if parent else title_text

            results.append({
                "source_id": self.source_id,
                "raw_id": href.strip("/").split("/")[-1],
                "title": title_text,
                "company": company,
                "location": location,
                "description": f"{title_text}. {snippet[:350]}",
                "batches": list(dict.fromkeys(batches)),
                "salary_raw": None,
                "listing_url": self.base_url,
                "apply_url": href,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": None,
                "raw_metadata": {"snippet": snippet[:200]},
            })

            if len(results) >= max_items:
                break

        logger.info("[jobs4fresher] Extracted %d listings", len(results))
        return results
