"""eLitmus Fresher Jobs Scraper."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.elitmus")


class ELitmusScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="elitmus",
            name="eLitmus",
            base_url="https://www.elitmus.com/jobs",
            rate_limit_seconds=3.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[elitmus] Failed to fetch listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_links = set()

        links = soup.find_all("a", href=re.compile(r"/jobs/\d+"))
        for a in links:
            href = a["href"].split("?")[0].strip()
            if href in seen_links:
                continue

            title_text = a.get_text(strip=True)
            if not title_text or title_text.lower() in {"show details", "apply", "details"}:
                continue

            seen_links.add(href)
            full_url = urljoin(self.base_url, a["href"])

            # eLitmus slug format: /jobs/<id>-<company>-<title>-<location>
            # Example: /jobs/33259-elitmus-evaluation-software-developer-associate-consultant-bangalore
            match = re.match(r"/jobs/(\d+)-(.*)", href)
            job_id = match.group(1) if match else href
            slug_body = match.group(2) if match else ""
            slug_parts = slug_body.split("-") if slug_body else []

            company = "eLitmus Verified Employer"
            location = "India"
            if len(slug_parts) >= 2:
                # Often the first 1-2 words are the company
                company = slug_parts[0].capitalize()
                location = slug_parts[-1].capitalize()

            # Inspect card context if available
            parent = a.find_parent(["div", "li", "tr"])
            card_text = parent.get_text(" | ", strip=True) if parent else ""

            # Check salary mentions
            sal_match = re.search(r"(\d+(?:\.\d+)?\s*(?:lakh|lpa|inr))", card_text, re.IGNORECASE)
            salary_raw = sal_match.group(1) if sal_match else None

            # Check batches in text
            batches = re.findall(r"202\d", card_text)

            results.append({
                "source_id": self.source_id,
                "raw_id": job_id,
                "title": title_text,
                "company": company,
                "location": location,
                "description": f"{title_text} at {company}. {card_text}",
                "batches": list(dict.fromkeys(batches)),
                "salary_raw": salary_raw,
                "listing_url": self.base_url,
                "apply_url": full_url,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": None,
                "raw_metadata": {"slug": slug_body, "snippet": card_text[:300]},
            })

            if len(results) >= max_items:
                break

        logger.info("[elitmus] Extracted %d listings", len(results))
        return results
