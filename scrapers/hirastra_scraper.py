"""Hirastra Off-Campus Drives Scraper."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.hirastra")


class HirastraScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="hirastra",
            name="Hirastra Off-Campus",
            base_url="https://hirastra.com/off-campus-drives",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[hirastra] Failed to fetch listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_links = set()

        # Find drive cards or table rows
        rows = soup.find_all(["tr", "div", "article"], class_=re.compile(r"drive|item|card|row", re.I))
        for r in rows:
            a = r.find("a", href=True)
            if not a:
                continue
            href = a["href"].strip()
            if href in seen_links or len(href) < 5 or href == "#":
                continue

            title = a.get_text(strip=True)
            if len(title) < 8 or title.lower() in {"apply", "view", "details"}:
                continue

            seen_links.add(href)
            full_url = urljoin(self.base_url, href)

            row_text = r.get_text(" | ", strip=True)
            batches = re.findall(r"202\d", f"{title} {row_text}")

            # Extract company if formatted like "Company Off Campus Drive"
            company = "Enterprise"
            if "Off Campus" in title:
                company = title.split("Off Campus")[0].strip()
            elif "Hiring" in title:
                company = title.split("Hiring")[0].strip()

            results.append({
                "source_id": self.source_id,
                "raw_id": href.strip("/").split("/")[-1],
                "title": title,
                "company": company if company else "Hirastra Hiring Partner",
                "location": "India",
                "description": f"{title}. {row_text[:300]}",
                "batches": list(dict.fromkeys(batches)),
                "salary_raw": None,
                "listing_url": self.base_url,
                "apply_url": full_url,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": None,
                "raw_metadata": {"snippet": row_text[:200]},
            })

            if len(results) >= max_items:
                break

        logger.info("[hirastra] Extracted %d listings", len(results))
        return results
